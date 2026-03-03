"""Unit tests for PGN clock parsing and analytics engine.

These tests are fully offline – no chess.com API calls are made.
"""
from __future__ import annotations

import pytest

from app.schemas import GameSummary, MoveClockEntry
from app.services.chess_com import _parse_clock, _extract_move_clocks
from app.services.analytics_engine import compute_move_time_stats, compute_move_time_trend


# ---------------------------------------------------------------------------
# _parse_clock
# ---------------------------------------------------------------------------

class TestParseClock:
    def test_hms(self):
        assert _parse_clock("{ [%clk 0:05:00] }") == 300.0

    def test_hms_with_hours(self):
        assert _parse_clock("{ [%clk 1:30:00] }") == 5400.0

    def test_fractional_seconds(self):
        assert _parse_clock("{ [%clk 0:04:57.3] }") == pytest.approx(297.3)

    def test_no_annotation(self):
        assert _parse_clock("{ just a comment }") is None

    def test_empty(self):
        assert _parse_clock("") is None


# ---------------------------------------------------------------------------
# _extract_move_clocks
# ---------------------------------------------------------------------------

SAMPLE_PGN = """\
[Event "Live Chess"]
[White "alice"]
[Black "bob"]
[TimeControl "300"]

1. e4 { [%clk 0:05:00] } 1... e5 { [%clk 0:05:00] } 2. Nf3 { [%clk 0:04:55] } \
2... Nc6 { [%clk 0:04:52] } 3. Bb5 { [%clk 0:04:48] } 3... a6 { [%clk 0:04:45] } \
1/2-1/2
"""


class TestExtractMoveClocks:
    def setup_method(self):
        self.entries = _extract_move_clocks(SAMPLE_PGN)

    def test_entry_count(self):
        # 3 moves × 2 colors = 6 entries
        assert len(self.entries) == 6

    def test_first_white_move_no_time_spent(self):
        # White's first move: no prior clock so time_spent is None
        first_white = next(e for e in self.entries if e.color == "white" and e.move_number == 1)
        assert first_white.clock_after == 300.0
        assert first_white.time_spent is None

    def test_white_move2_time_spent(self):
        m2_white = next(e for e in self.entries if e.color == "white" and e.move_number == 2)
        # 300 - 295 = 5 seconds
        assert m2_white.time_spent == pytest.approx(5.0)

    def test_black_move2_time_spent(self):
        m2_black = next(e for e in self.entries if e.color == "black" and e.move_number == 2)
        # 300 - 292 = 8 seconds
        assert m2_black.time_spent == pytest.approx(8.0)

    def test_ply_ordering(self):
        plies = [e.ply for e in self.entries]
        assert plies == sorted(plies)

    def test_move_number_assignment(self):
        assert self.entries[0].move_number == 1
        assert self.entries[1].move_number == 1
        assert self.entries[2].move_number == 2


# ---------------------------------------------------------------------------
# compute_move_time_stats
# ---------------------------------------------------------------------------

def _make_game(white: str, black: str, clocks: list[MoveClockEntry], end_time: int = 1700000000) -> GameSummary:
    return GameSummary(
        url="https://chess.com/game/1",
        time_class="blitz",
        time_control="300",
        white_username=white,
        black_username=black,
        white_result="win",
        black_result="lose",
        end_time=end_time,
        rated=True,
        move_clocks=clocks,
    )


def _clocks(white_times: list[float], black_times: list[float]) -> list[MoveClockEntry]:
    """Build a list of MoveClockEntry from per-move seconds-spent lists."""
    entries = []
    white_clock = 300.0
    black_clock = 300.0
    for i, (wt, bt) in enumerate(zip(white_times, black_times)):
        move_num = i + 1
        ply_w = 2 * i + 1
        ply_b = 2 * i + 2
        white_clock -= wt
        entries.append(MoveClockEntry(ply=ply_w, move_number=move_num, color="white",
                                      clock_after=white_clock, time_spent=wt))
        black_clock -= bt
        entries.append(MoveClockEntry(ply=ply_b, move_number=move_num, color="black",
                                      clock_after=black_clock, time_spent=bt))
    return entries


class TestComputeMoveTimeStats:
    def setup_method(self):
        # Two games where alice (white) spends 5 or 10 sec on move 1
        game1 = _make_game("alice", "bob", _clocks([5.0, 3.0], [4.0, 6.0]))
        game2 = _make_game("alice", "bob", _clocks([10.0, 2.0], [8.0, 1.0]))
        self.games = [game1, game2]

    def test_avg_move1_white(self):
        stats = compute_move_time_stats(self.games, "alice")
        m1_white = next(s for s in stats if s.move_number == 1 and s.color == "white")
        assert m1_white.avg_seconds == pytest.approx(7.5)

    def test_count(self):
        stats = compute_move_time_stats(self.games, "alice")
        m1_white = next(s for s in stats if s.move_number == 1 and s.color == "white")
        assert m1_white.count == 2

    def test_move_limit(self):
        stats = compute_move_time_stats(self.games, "alice", move_limit=1)
        move_numbers = {s.move_number for s in stats}
        assert move_numbers == {1}

    def test_only_user_color(self):
        # Stats for "alice" (white) should not include black's times
        stats = compute_move_time_stats(self.games, "alice")
        assert all(s.color == "white" for s in stats)

    def test_unknown_user_returns_empty(self):
        stats = compute_move_time_stats(self.games, "charlie")
        assert stats == []


# ---------------------------------------------------------------------------
# compute_move_time_trend
# ---------------------------------------------------------------------------

class TestComputeMoveTimeTrend:
    def setup_method(self):
        # game on day 1, game on day 2
        game1 = _make_game("alice", "bob", _clocks([5.0, 3.0], [4.0, 6.0]), end_time=1700000000)
        game2 = _make_game("alice", "bob", _clocks([10.0, 2.0], [8.0, 1.0]), end_time=1700086400)
        self.games = [game1, game2]

    def test_two_dates(self):
        trend = compute_move_time_trend(self.games, "alice")
        dates = {p.date for p in trend}
        assert len(dates) == 2

    def test_specific_move_filter(self):
        trend = compute_move_time_trend(self.games, "alice", move_numbers=[1])
        assert all(p.move_number == 1 for p in trend)

    def test_all_moves_aggregated_move_number_zero(self):
        trend = compute_move_time_trend(self.games, "alice")
        assert all(p.move_number == 0 for p in trend)

    def test_avg_values(self):
        trend = compute_move_time_trend(self.games, "alice", move_numbers=[1])
        # Day 1: only move 1 = 5.0 sec; Day 2: only move 1 = 10.0 sec
        avgs = sorted(p.avg_seconds for p in trend)
        assert avgs == pytest.approx([5.0, 10.0])
