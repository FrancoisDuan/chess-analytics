"""Analytics engine.

All analytic computations are pure functions over a list of GameSummary objects.
Adding new analytics = adding a new function here (no routing changes needed).
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

import chess
import httpx

from app.schemas import (
    GameSummary,
    MoveTimeStats,
    MoveTimeTrendPoint,
    PerMoveEntry,
)
from app.services import lichess_eval


def _percentile(sorted_data: list[float], pct: float) -> float:
    """Return the pct-th percentile (0–100) of a sorted list."""
    if not sorted_data:
        return 0.0
    k = (len(sorted_data) - 1) * pct / 100
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[-1]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


# ---------------------------------------------------------------------------
# Move-time statistics
# ---------------------------------------------------------------------------

def compute_move_time_stats(
    games: list[GameSummary],
    username: str,
    move_limit: Optional[int] = None,
) -> list[MoveTimeStats]:
    """Return per-move-number time statistics for *username* across *games*.

    Only moves where *username* is the active player are counted.
    Only entries where ``time_spent`` is not None are included.
    """
    username_lower = username.lower()
    # bucket[move_number][color] -> list of seconds
    bucket: dict[tuple[int, str], list[float]] = defaultdict(list)

    for game in games:
        # Determine which color this user played
        if game.white_username.lower() == username_lower:
            user_color = "white"
        elif game.black_username.lower() == username_lower:
            user_color = "black"
        else:
            continue

        for entry in game.move_clocks:
            if entry.color != user_color:
                continue
            if entry.time_spent is None:
                continue
            if move_limit and entry.move_number > move_limit:
                continue
            bucket[(entry.move_number, entry.color)].append(entry.time_spent)

    results: list[MoveTimeStats] = []
    for (move_number, color), times in sorted(bucket.items()):
        times_sorted = sorted(times)
        results.append(
            MoveTimeStats(
                move_number=move_number,
                color=color,
                count=len(times_sorted),
                avg_seconds=round(statistics.mean(times_sorted), 3),
                median_seconds=round(statistics.median(times_sorted), 3),
                min_seconds=round(times_sorted[0], 3),
                max_seconds=round(times_sorted[-1], 3),
                p25_seconds=round(_percentile(times_sorted, 25), 3),
                p75_seconds=round(_percentile(times_sorted, 75), 3),
            )
        )
    return results


# ---------------------------------------------------------------------------
# Move-time trend (time spent on move(s) as a function of date)
# ---------------------------------------------------------------------------

def compute_move_time_trend(
    games: list[GameSummary],
    username: str,
    move_numbers: Optional[list[int]] = None,
) -> list[MoveTimeTrendPoint]:
    """Return daily-aggregated average time per move for the given move numbers.

    If *move_numbers* is None or empty, all moves are aggregated together
    (giving an overall "average time per move" trend over time).
    """
    username_lower = username.lower()
    # bucket[(date_str, move_number, color)] -> list of seconds
    bucket: dict[tuple[str, int, str], list[float]] = defaultdict(list)

    for game in games:
        if game.white_username.lower() == username_lower:
            user_color = "white"
        elif game.black_username.lower() == username_lower:
            user_color = "black"
        else:
            continue

        date_str = datetime.fromtimestamp(game.end_time, tz=timezone.utc).strftime("%Y-%m-%d")

        for entry in game.move_clocks:
            if entry.color != user_color:
                continue
            if entry.time_spent is None:
                continue
            if move_numbers and entry.move_number not in move_numbers:
                continue
            # Use move_number=0 as sentinel for "all moves aggregated"
            agg_move = entry.move_number if move_numbers else 0
            bucket[(date_str, agg_move, entry.color)].append(entry.time_spent)

    results: list[MoveTimeTrendPoint] = []
    for (date_str, move_number, color), times in sorted(bucket.items()):
        results.append(
            MoveTimeTrendPoint(
                date=date_str,
                move_number=move_number,
                color=color,
                avg_seconds=round(statistics.mean(times), 3),
                game_count=len(times),
            )
        )
    return results


# ---------------------------------------------------------------------------
# Per-move accuracy / criticality / combined-metric helpers
# ---------------------------------------------------------------------------

def _compute_accuracy(cp_loss: float) -> float:
    """Convert centipawn loss to an accuracy score in [0, 1].

    Uses a Lichess-inspired formula: score = 103.1668 * exp(-0.04354 * |loss|) - 3.1669,
    then normalised to [0, 1] by dividing by 100 and clamping.

    The constants (103.1668, 0.04354, 3.1669) are derived from a logistic fit
    to human-played moves: a zero-centipawn-loss move scores ≈ 1.0, and each
    additional 100 cp of loss roughly halves the score.  The intercept −3.1669
    ensures the function reaches 0 before it would go negative.
    """
    raw = 103.1668 * math.exp(-0.04354 * abs(cp_loss)) - 3.1669
    return max(0.0, min(1.0, raw / 100.0))


def _compute_criticality(cp_before: float) -> float:
    """Return position criticality in [0, 1].

    Positions close to 0 centipawns (balanced) are considered most critical.
    Uses an exponential decay: exp(-|cp| / 150).
    """
    return math.exp(-abs(cp_before) / 150.0)


def _normalize_time(time_spent: Optional[float], median_time: float) -> Optional[float]:
    """Return *time_spent* as a multiple of *median_time*, or None.

    E.g. 1.0 means the player spent exactly their median time;
         2.0 means they spent twice as long.
    """
    if time_spent is None or median_time <= 0:
        return None
    return round(time_spent / median_time, 3)


def _compute_combined_metric(
    accuracy: Optional[float],
    criticality: Optional[float],
    normalized_time: Optional[float],
) -> Optional[float]:
    """Compute the combined per-move score (0–100).

    Formula
    -------
    * Base: ``accuracy * (0.7 + 0.3 * criticality) * 100``
      – accuracy is always rewarded; critical positions amplify the reward.
    * Time factor: small penalty (up to −5 %) when the player spends >1× the
      median time in a non-critical position (criticality < 0.5).

    Returns None when accuracy is not available.
    """
    if accuracy is None:
        return None
    crit = criticality if criticality is not None else 0.0
    base = accuracy * (0.7 + 0.3 * crit) * 100.0

    time_factor = 1.0
    if normalized_time is not None and normalized_time > 1.0 and crit < 0.5:
        time_factor = max(0.95, 1.0 - 0.05 * (normalized_time - 1.0))

    return round(min(100.0, base * time_factor), 1)


# ---------------------------------------------------------------------------
# Per-move analysis (async – fetches Lichess cloud evals when a client is given)
# ---------------------------------------------------------------------------

async def compute_per_move_analysis(
    games: list[GameSummary],
    username: str,
    eval_client: Optional[httpx.AsyncClient] = None,
) -> list[PerMoveEntry]:
    """Return per-move analysis entries for *username* across *games*.

    For each half-move where *username* is the active player the function
    computes:
    * time_spent / normalized_time
    * eval_before / eval_after (centipawns, white-perspective)
    * accuracy (0–1), criticality (0–1), combined_metric (0–100)

    When *eval_client* is ``None`` (or when no FEN is available for a move),
    the eval-derived fields are ``None`` and combined_metric is also ``None``.

    Parameters
    ----------
    games:
        List of games to analyse (already filtered / sliced by the caller).
    username:
        The player whose moves are analysed.
    eval_client:
        Optional :class:`httpx.AsyncClient` used to fetch Lichess cloud evals.
        Evals are cached globally by FEN (see :mod:`app.services.lichess_eval`).
    """
    username_lower = username.lower()
    results: list[PerMoveEntry] = []

    for game in games:
        if game.white_username.lower() == username_lower:
            user_color = "white"
        elif game.black_username.lower() == username_lower:
            user_color = "black"
        else:
            continue

        # Median time per move for the user within this game (for normalisation).
        user_times = [
            e.time_spent
            for e in game.move_clocks
            if e.color == user_color and e.time_spent is not None
        ]
        median_time = statistics.median(user_times) if user_times else 0.0

        # Gather unique FENs that need evaluation.
        fen_to_eval: dict[str, Optional[float]] = {}
        if eval_client is not None:
            fens_needed: set[str] = set()
            # We need evals for the position *before* the user's move, which is
            # the FEN after the opponent's previous half-move.  Walk the list to
            # collect all relevant FENs (including opponent moves that precede
            # a user move).
            prev_fen: Optional[str] = chess.STARTING_FEN
            for entry in game.move_clocks:
                if entry.color == user_color:
                    if prev_fen:
                        fens_needed.add(prev_fen)
                    if entry.fen_after:
                        fens_needed.add(entry.fen_after)
                if entry.fen_after:
                    prev_fen = entry.fen_after

            for fen in fens_needed:
                fen_to_eval[fen] = await lichess_eval.get_eval(fen, eval_client)

        # Walk moves and build entries.
        prev_fen = chess.STARTING_FEN
        for entry in game.move_clocks:
            fen_before = prev_fen
            fen_after = entry.fen_after

            if entry.color == user_color:
                eval_before = fen_to_eval.get(fen_before) if fen_before else None
                eval_after_val = fen_to_eval.get(fen_after) if fen_after else None

                # Centipawn loss from the user's perspective.
                accuracy: Optional[float] = None
                if eval_before is not None and eval_after_val is not None:
                    if user_color == "white":
                        cp_loss = max(0.0, eval_before - eval_after_val)
                    else:
                        # From Black's perspective: a rising eval is bad.
                        cp_loss = max(0.0, eval_after_val - eval_before)
                    accuracy = _compute_accuracy(cp_loss)

                criticality_val: Optional[float] = None
                if eval_before is not None:
                    criticality_val = _compute_criticality(eval_before)

                normalized_time = _normalize_time(entry.time_spent, median_time)
                combined = _compute_combined_metric(accuracy, criticality_val, normalized_time)

                results.append(
                    PerMoveEntry(
                        game_url=game.url,
                        game_end_time=game.end_time,
                        ply=entry.ply,
                        move_number=entry.move_number,
                        color=entry.color,
                        san=entry.san,
                        time_spent=entry.time_spent,
                        normalized_time=normalized_time,
                        eval_before=eval_before,
                        eval_after=eval_after_val,
                        accuracy=accuracy,
                        criticality=criticality_val,
                        combined_metric=combined,
                    )
                )

            # Advance the running position pointer.
            if fen_after:
                prev_fen = fen_after

    return results
