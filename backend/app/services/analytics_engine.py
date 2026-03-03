"""Analytics engine.

All analytic computations are pure functions over a list of GameSummary objects.
Adding new analytics = adding a new function here (no routing changes needed).
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from app.schemas import GameSummary, MoveTimeStats, MoveTimeTrendPoint


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
