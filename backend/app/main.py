"""FastAPI application entry-point."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.routers import analytics, games
from app.services import chess_com, lichess
from app.services.cache import game_cache

logger = logging.getLogger(__name__)


async def _background_refresh() -> None:
    """Periodically re-fetch game data for active users.

    Runs forever as a background asyncio task.  On each iteration it:
    1. Waits ``REFRESH_INTERVAL_MINUTES`` minutes.
    2. Finds every user who has accessed the app within ``ACTIVE_USER_DAYS``.
    3. Fetches their latest games (up to ``CACHE_MAX_GAMES``) from the
       appropriate platform and updates the in-memory cache.

    Cache keys have the form ``"<platform>:<username>"``; the platform
    determines which API client is used for the refresh.
    """
    while True:
        await asyncio.sleep(config.REFRESH_INTERVAL_MINUTES * 60)
        active_keys = game_cache.get_active_usernames(within_days=config.ACTIVE_USER_DAYS)
        for key in active_keys:
            platform, _, username = key.partition(":")
            if not username:
                continue
            try:
                if platform == "chessdotcom":
                    fresh_games = await chess_com.get_user_games(
                        username, limit=config.CACHE_MAX_GAMES
                    )
                elif platform == "lichess":
                    fresh_games = await lichess.get_user_games(
                        username, limit=config.CACHE_MAX_GAMES
                    )
                else:
                    continue
                game_cache.set(username, fresh_games, platform=platform)
                logger.info(
                    "Auto-refreshed %d games for %s/%s", len(fresh_games), platform, username
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Failed to auto-refresh games for %s/%s: %s", platform, username, exc
                )


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    """Start the background refresh task on startup; cancel it on shutdown."""
    task = asyncio.create_task(_background_refresh())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Chess Analytics API",
    description=(
        "Fetch chess.com games and compute time-per-move analytics. "
        "Filter by time class (blitz, rapid, …), track time evolution over dates, "
        "and compare two players side-by-side."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Allow the local Vite dev server and any production origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(games.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")


@app.get("/", tags=["health"])
async def root():
    return {"status": "ok", "docs": "/docs"}
