"""Games router: fetch chess.com games for a user."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.schemas import GameSummary
from app.services import chess_com

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
