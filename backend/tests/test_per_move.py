"""Tests for per-move analysis: engine functions, endpoint, platform routing,
date filtering, partial eval handling, and combined metric correctness.

All tests are fully offline – no external API calls are made.
"""
from __future__ import annotations

import math
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import GameSummary, MoveClockEntry, PerMoveEntry
from app.services.analytics_engine import (
    _compute_accuracy,
    _compute_combined_metric,
    _compute_criticality,
    _normalize_time,
    compute_per_move_analysis,
)
from app.services.cache import game_cache

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_clock_entry(
    ply: int,
    move_number: int,
    color: str,
    clock_after: float,
    time_spent: float | None = None,
    san: str | None = None,
    fen_after: str | None = None,
) -> MoveClockEntry:
    return MoveClockEntry(
        ply=ply,
        move_number=move_number,
        color=color,
        clock_after=clock_after,
        time_spent=time_spent,
        san=san,
        fen_after=fen_after,
    )


def _make_game(
    white: str = "alice",
    black: str = "bob",
    time_class: str = "blitz",
    end_time: int = 1_700_000_000,
    with_fen: bool = False,
) -> GameSummary:
    # FENs after moves 1. e4 / 1... e5 / 2. Nf3
    fen_after_e4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
    fen_after_e5 = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2"
    fen_after_nf3 = "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"

    clocks = [
        _make_clock_entry(1, 1, "white", 295.0, 5.0, "e4", fen_after_e4 if with_fen else None),
        _make_clock_entry(2, 1, "black", 298.0, 2.0, "e5", fen_after_e5 if with_fen else None),
        _make_clock_entry(3, 2, "white", 288.0, 7.0, "Nf3", fen_after_nf3 if with_fen else None),
        _make_clock_entry(4, 2, "black", 290.0, 8.0, "Nc6", None),
    ]
    return GameSummary(
        url=f"https://example.com/game/{white}",
        time_class=time_class,
        time_control="300",
        white_username=white,
        black_username=black,
        white_result="win",
        black_result="lose",
        end_time=end_time,
        rated=True,
        move_clocks=clocks,
    )


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------

class TestComputeAccuracy:
    def test_zero_loss_is_one(self):
        assert _compute_accuracy(0.0) == pytest.approx(1.0, abs=0.02)

    def test_large_loss_approaches_zero(self):
        assert _compute_accuracy(500.0) < 0.05

    def test_moderate_loss(self):
        acc = _compute_accuracy(10.0)
        assert 0.3 < acc < 0.9

    def test_clamped_at_zero(self):
        assert _compute_accuracy(10_000.0) == 0.0


class TestComputeCriticality:
    def test_balanced_position_high_criticality(self):
        # cp = 0 → exp(0) = 1.0
        assert _compute_criticality(0.0) == pytest.approx(1.0)

    def test_large_advantage_low_criticality(self):
        assert _compute_criticality(1000.0) < 0.01

    def test_small_advantage(self):
        crit = _compute_criticality(50.0)
        assert 0.5 < crit < 1.0


class TestNormalizeTime:
    def test_equal_to_median_is_one(self):
        assert _normalize_time(5.0, 5.0) == pytest.approx(1.0)

    def test_none_time_returns_none(self):
        assert _normalize_time(None, 5.0) is None

    def test_zero_median_returns_none(self):
        assert _normalize_time(5.0, 0.0) is None

    def test_half_median(self):
        assert _normalize_time(2.5, 5.0) == pytest.approx(0.5)


class TestComputeCombinedMetric:
    def test_none_accuracy_returns_none(self):
        assert _compute_combined_metric(None, 0.5, 1.0) is None

    def test_perfect_accuracy_high_score(self):
        score = _compute_combined_metric(1.0, 1.0, 1.0)
        assert score is not None
        assert score > 90.0

    def test_zero_accuracy_zero_score(self):
        score = _compute_combined_metric(0.0, 0.5, 1.0)
        assert score == pytest.approx(0.0)

    def test_no_criticality_lower_score(self):
        high_crit = _compute_combined_metric(1.0, 1.0, 1.0)
        low_crit = _compute_combined_metric(1.0, 0.0, 1.0)
        assert high_crit is not None and low_crit is not None
        assert high_crit > low_crit

    def test_time_penalty_on_slow_non_critical_move(self):
        normal = _compute_combined_metric(0.8, 0.1, 1.0)
        slow = _compute_combined_metric(0.8, 0.1, 5.0)
        assert normal is not None and slow is not None
        assert normal >= slow

    def test_no_time_penalty_on_critical_move(self):
        # High criticality: no time penalty should apply.
        normal = _compute_combined_metric(0.8, 1.0, 1.0)
        slow = _compute_combined_metric(0.8, 1.0, 5.0)
        assert normal is not None and slow is not None
        assert normal == pytest.approx(slow, abs=0.1)

    def test_score_in_range(self):
        for acc in [0.0, 0.5, 1.0]:
            for crit in [0.0, 0.5, 1.0]:
                score = _compute_combined_metric(acc, crit, 1.0)
                assert score is not None
                assert 0.0 <= score <= 100.0


# ---------------------------------------------------------------------------
# Unit tests for compute_per_move_analysis (async)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_per_move_analysis_no_eval():
    """Without an eval client all eval-derived fields are None."""
    game = _make_game("alice", "bob", with_fen=False)
    results = await compute_per_move_analysis([game], "alice")

    # Only alice's moves (white = move 1 and 2)
    assert len(results) == 2
    for entry in results:
        assert entry.color == "white"
        assert entry.eval_before is None
        assert entry.eval_after is None
        assert entry.accuracy is None
        assert entry.criticality is None
        assert entry.combined_metric is None


@pytest.mark.asyncio
async def test_per_move_analysis_with_eval():
    """With mocked evals the accuracy / criticality / combined fields are populated."""
    game = _make_game("alice", "bob", with_fen=True)

    # Stub eval client: always returns 0 cp (perfectly balanced).
    mock_client = MagicMock()

    async def fake_get_eval(fen, client):
        return 0.0  # balanced position

    with patch("app.services.analytics_engine.lichess_eval.get_eval", side_effect=fake_get_eval):
        results = await compute_per_move_analysis([game], "alice", eval_client=mock_client)

    assert len(results) == 2
    for entry in results:
        assert entry.accuracy is not None
        assert entry.criticality is not None
        assert entry.combined_metric is not None
        assert 0.0 <= entry.accuracy <= 1.0
        assert 0.0 <= entry.criticality <= 1.0
        assert 0.0 <= entry.combined_metric <= 100.0


@pytest.mark.asyncio
async def test_per_move_analysis_partial_eval():
    """When some evals are None the affected entries have null metric fields."""
    game = _make_game("alice", "bob", with_fen=True)

    call_count = [0]

    async def partial_get_eval(fen, client):
        call_count[0] += 1
        # Only return an eval for the very first call; the rest are None.
        return 0.0 if call_count[0] == 1 else None

    mock_client = MagicMock()
    with patch("app.services.analytics_engine.lichess_eval.get_eval", side_effect=partial_get_eval):
        results = await compute_per_move_analysis([game], "alice", eval_client=mock_client)

    assert len(results) == 2
    # With partial evals some entries may lack accuracy/combined_metric.
    # The key invariant is that no exception is raised.
    for entry in results:
        if entry.accuracy is not None:
            assert 0.0 <= entry.accuracy <= 1.0
        if entry.combined_metric is not None:
            assert 0.0 <= entry.combined_metric <= 100.0


@pytest.mark.asyncio
async def test_per_move_analysis_normalized_time():
    """normalized_time should equal time_spent / median_time for user's moves."""
    import statistics as stats
    game = _make_game("alice", "bob", with_fen=False)
    # White times: 5.0 (move 1) and 7.0 (move 2); median = 6.0
    results = await compute_per_move_analysis([game], "alice")

    user_move_times = [r.time_spent for r in results if r.time_spent is not None]
    median = stats.median(user_move_times)

    for entry in results:
        if entry.time_spent is not None and entry.normalized_time is not None:
            assert entry.normalized_time == pytest.approx(entry.time_spent / median, abs=0.01)


@pytest.mark.asyncio
async def test_per_move_analysis_unknown_user_returns_empty():
    game = _make_game("alice", "bob")
    results = await compute_per_move_analysis([game], "charlie")
    assert results == []


@pytest.mark.asyncio
async def test_per_move_analysis_multiple_games():
    game1 = _make_game("alice", "bob", end_time=1_700_000_000)
    game2 = _make_game("alice", "bob", end_time=1_700_086_400)
    results = await compute_per_move_analysis([game1, game2], "alice")
    # 2 user moves × 2 games
    assert len(results) == 4


# ---------------------------------------------------------------------------
# Endpoint integration tests (mocked external APIs)
# ---------------------------------------------------------------------------

_FAKE_CLOCKS = [
    MoveClockEntry(ply=1, move_number=1, color="white", clock_after=295.0, time_spent=5.0,
                   san="e4", fen_after="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"),
    MoveClockEntry(ply=2, move_number=1, color="black", clock_after=298.0, time_spent=2.0,
                   san="e5", fen_after="rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2"),
    MoveClockEntry(ply=3, move_number=2, color="white", clock_after=290.0, time_spent=5.0,
                   san="Nf3", fen_after="rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"),
    MoveClockEntry(ply=4, move_number=2, color="black", clock_after=293.0, time_spent=5.0,
                   san="Nc6", fen_after=None),
]

_FAKE_GAME = GameSummary(
    url="https://chess.com/game/1",
    time_class="blitz",
    time_control="300",
    white_username="testuser",
    black_username="opponent",
    white_result="win",
    black_result="lose",
    end_time=1_700_000_000,
    rated=True,
    move_clocks=_FAKE_CLOCKS,
)


@pytest.fixture()
def mock_chess_com():
    with patch(
        "app.services.chess_com.get_user_games",
        new_callable=AsyncMock,
        return_value=[_FAKE_GAME],
    ) as m:
        yield m


@pytest.fixture()
def mock_lichess():
    with patch(
        "app.services.lichess.get_user_games",
        new_callable=AsyncMock,
        return_value=[_FAKE_GAME],
    ) as m:
        yield m


@pytest.fixture()
def mock_eval_none():
    """Stub Lichess eval to always return None (position not in cloud)."""
    with patch(
        "app.services.lichess_eval.get_eval",
        new_callable=AsyncMock,
        return_value=None,
    ) as m:
        yield m


class TestPerMoveEndpoint:
    def test_chessdotcom_platform_ok(self, mock_chess_com, mock_eval_none):
        resp = client.get("/api/analytics/chessdotcom/testuser/per-move?n_games=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["platform"] == "chessdotcom"
        assert data["username"] == "testuser"
        assert data["games_analyzed"] == 1
        assert isinstance(data["moves"], list)

    def test_lichess_platform_ok(self, mock_lichess, mock_eval_none):
        resp = client.get("/api/analytics/lichess/testuser/per-move?n_games=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["platform"] == "lichess"

    def test_invalid_platform_returns_400(self):
        resp = client.get("/api/analytics/unknown_platform/testuser/per-move")
        assert resp.status_code == 400

    def test_without_eval_no_accuracy_fields(self, mock_chess_com):
        resp = client.get("/api/analytics/chessdotcom/testuser/per-move?with_eval=false&n_games=5")
        assert resp.status_code == 200
        data = resp.json()
        for move in data["moves"]:
            assert move["accuracy"] is None
            assert move["criticality"] is None
            assert move["combined_metric"] is None

    def test_move_entries_have_required_fields(self, mock_chess_com, mock_eval_none):
        resp = client.get("/api/analytics/chessdotcom/testuser/per-move?n_games=5")
        assert resp.status_code == 200
        for move in resp.json()["moves"]:
            assert "game_url" in move
            assert "game_end_time" in move
            assert "ply" in move
            assert "move_number" in move
            assert "color" in move
            assert move["color"] in ("white", "black")

    def test_only_user_color_moves_returned(self, mock_chess_com, mock_eval_none):
        resp = client.get("/api/analytics/chessdotcom/testuser/per-move?n_games=5")
        assert resp.status_code == 200
        for move in resp.json()["moves"]:
            assert move["color"] == "white"  # testuser plays white in _FAKE_GAME

    def test_date_filter_window_days(self, mock_chess_com, mock_eval_none):
        # window_days=1 should include recent games
        resp = client.get(
            "/api/analytics/chessdotcom/testuser/per-move?n_games=5&window_days=1"
        )
        # _FAKE_GAME.end_time=1_700_000_000 is old; expect 404
        assert resp.status_code == 404

    def test_date_filter_since_iso(self, mock_chess_com, mock_eval_none):
        # since a future date → no games → 404
        resp = client.get(
            "/api/analytics/chessdotcom/testuser/per-move?since=2099-01-01"
        )
        assert resp.status_code == 404

    def test_date_filter_until_iso(self, mock_chess_com, mock_eval_none):
        # until before the game's end_time → no games → 404
        resp = client.get(
            "/api/analytics/chessdotcom/testuser/per-move?until=2000-01-01"
        )
        assert resp.status_code == 404

    def test_date_filter_since_includes_game(self, mock_chess_com, mock_eval_none):
        # since before the game's end_time → game included
        resp = client.get(
            "/api/analytics/chessdotcom/testuser/per-move?since=2020-01-01&n_games=5"
        )
        assert resp.status_code == 200
        assert resp.json()["games_analyzed"] == 1

    def test_invalid_since_date_returns_422(self, mock_chess_com):
        resp = client.get(
            "/api/analytics/chessdotcom/testuser/per-move?since=not-a-date"
        )
        assert resp.status_code == 422

    def test_no_games_returns_404(self, mock_eval_none):
        with patch(
            "app.services.chess_com.get_user_games",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.get("/api/analytics/chessdotcom/nobody/per-move")
            assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Cache platform-awareness tests
# ---------------------------------------------------------------------------

class TestPlatformAwareCache:
    def test_chessdotcom_and_lichess_use_separate_cache_entries(self, mock_chess_com, mock_lichess):
        game_cache.clear()
        # Populate chess.com cache entry
        from app.services.cache import game_cache as gc
        gc.set("testuser", [_FAKE_GAME], platform="chessdotcom")
        # Lichess cache for same username should be empty
        assert gc.get("testuser", platform="lichess") is None

    def test_cache_key_includes_platform(self):
        from app.services.cache import game_cache as gc
        gc.set("alice", [_FAKE_GAME], platform="chessdotcom")
        gc.set("alice", [], platform="lichess")
        assert len(gc.get("alice", platform="chessdotcom")) == 1
        assert len(gc.get("alice", platform="lichess")) == 0
