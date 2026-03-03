"""Analytics router.

All analytics endpoints share a common pattern:
  1. Serve games from the in-memory cache (populated on first access and
     refreshed periodically by the background task in ``main.py``).
  2. Run a pure analytics function over those games.
  3. Return structured results.

Adding new analytics
--------------------
1. Define a response schema in ``schemas.py``.
2. Add a pure function in ``analytics_engine.py`` that accepts
   ``list[GameSummary]`` and returns your new schema (or a list of it).
3. Add a new ``@router.get`` endpoint below that calls ``_load_games``
   and then your new engine function.  No changes to the data layer are
   required.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app import config
from app.schemas import ComparisonData, MoveTimeStats, MoveTimeTrendPoint
from app.services import analytics_engine, chess_com
from app.services.cache import game_cache

router = APIRouter(prefix="/analytics", tags=["analytics"])


async def _load_games(username: str, time_class: Optional[str], limit: int):
    """Return games for *username*, using the in-memory cache when available.

    Side-effects
    ------------
    * Calls ``game_cache.touch(username)`` so the background refresh task
      knows this user is active and should be kept up-to-date.
    * On a cache miss, fetches up to ``CACHE_MAX_GAMES`` games from
      chess.com and stores them in the cache before filtering/slicing.

    The in-process ``time_class`` filter and ``limit`` slice are applied
    *after* retrieval so the cached dataset can serve any combination of
    query parameters without additional chess.com round-trips.
    """
    game_cache.touch(username)

    games = game_cache.get(username)
    if games is None:
        try:
            games = await chess_com.get_user_games(username, limit=config.CACHE_MAX_GAMES)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Chess.com API error: {exc}") from exc
        game_cache.set(username, games)

    if time_class:
        games = [g for g in games if g.time_class.lower() == time_class.lower()]
    games = games[:limit]

    if not games:
        raise HTTPException(
            status_code=404,
            detail=f"No games found for user '{username}'"
            + (f" with time_class='{time_class}'" if time_class else ""),
        )
    return games


@router.get("/{username}/move-time", response_model=list[MoveTimeStats])
async def move_time_stats(
    username: str,
    time_class: Optional[str] = Query(default=None, description="blitz | rapid | bullet | daily | classical"),
    limit: int = Query(default=100, ge=1, le=500, description="Max games to analyse"),
    move_limit: Optional[int] = Query(default=None, ge=1, description="Only analyse moves up to this move number"),
):
    """Return average / median / percentile time-per-move for each move number.

    Results are broken down by move number and color (white / black).
    """
    games = await _load_games(username, time_class, limit)
    return analytics_engine.compute_move_time_stats(games, username, move_limit=move_limit)


@router.get("/{username}/move-time-trend", response_model=list[MoveTimeTrendPoint])
async def move_time_trend(
    username: str,
    time_class: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    move_numbers: Optional[str] = Query(
        default=None,
        description="Comma-separated move numbers to track, e.g. '1,2,3'. "
        "Omit to aggregate all moves.",
    ),
):
    """Return how average time-per-move has evolved over calendar dates.

    Use ``move_numbers`` to focus on specific moves (e.g. first 3 moves of the
    opening).  Omit it to get an overall average across all moves.
    """
    games = await _load_games(username, time_class, limit)
    parsed_moves: Optional[list[int]] = None
    if move_numbers:
        try:
            parsed_moves = [int(m.strip()) for m in move_numbers.split(",") if m.strip()]
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="move_numbers must be comma-separated integers") from exc
    return analytics_engine.compute_move_time_trend(games, username, move_numbers=parsed_moves)


@router.get("/compare/{username1}/{username2}", response_model=ComparisonData)
async def compare_users(
    username1: str,
    username2: str,
    time_class: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    move_limit: Optional[int] = Query(default=None, ge=1),
):
    """Compare move-time statistics between two chess.com users."""
    games1 = await _load_games(username1, time_class, limit)
    games2 = await _load_games(username2, time_class, limit)

    stats1 = analytics_engine.compute_move_time_stats(games1, username1, move_limit=move_limit)
    stats2 = analytics_engine.compute_move_time_stats(games2, username2, move_limit=move_limit)

    return ComparisonData(
        username1=username1,
        username2=username2,
        move_time_stats1=stats1,
        move_time_stats2=stats2,
    )
