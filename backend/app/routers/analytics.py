"""Analytics router.

All analytics endpoints share a common pattern:
  1. Fetch games from chess.com (with optional time_class / limit filters).
  2. Run a pure analytics function over those games.
  3. Return structured results.

Adding new analytics = adding a new endpoint that calls a new function in
``analytics_engine``.  No changes to the data layer are required.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ComparisonData, MoveTimeStats, MoveTimeTrendPoint
from app.services import analytics_engine, chess_com

router = APIRouter(prefix="/analytics", tags=["analytics"])


async def _load_games(username: str, time_class: Optional[str], limit: int):
    """Helper: fetch games and raise 404/502 on error."""
    try:
        games = await chess_com.get_user_games(username, time_class=time_class, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Chess.com API error: {exc}") from exc
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
