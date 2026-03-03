"""Games router: fetch chess.com games for a user."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app import config
from app.schemas import GameSummary
from app.services import chess_com
from app.services.cache import game_cache

router = APIRouter(prefix="/games", tags=["games"])


@router.get("/{username}", response_model=list[GameSummary])
async def get_games(
    username: str,
    time_class: Optional[str] = Query(
        default=None,
        description="Filter by time class: blitz, rapid, bullet, daily, classical",
    ),
    limit: Optional[int] = Query(
        default=50,
        ge=1,
        le=500,
        description="Maximum number of games to return (most recent first)",
    ),
):
    """Return chess.com games for *username*, optionally filtered by time class."""
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
