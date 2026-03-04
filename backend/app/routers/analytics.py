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

from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query

from app import config
from app.schemas import ComparisonData, MoveTimeStats, MoveTimeTrendPoint, PerMoveResponse
from app.services import analytics_engine, chess_com, lichess
from app.services.cache import game_cache

router = APIRouter(prefix="/analytics", tags=["analytics"])

_SUPPORTED_PLATFORMS = ("chessdotcom", "lichess")


def _parse_date_filters(
    window_days: Optional[int],
    since: Optional[str],
    until: Optional[str],
) -> tuple[Optional[int], Optional[int]]:
    """Convert date-filter query params to Unix timestamps (seconds).

    Priority: ``window_days`` > ``since`` / ``until``.
    Returns ``(since_ts, until_ts)`` where either may be ``None``.
    """
    since_ts: Optional[int] = None
    until_ts: Optional[int] = None

    if window_days is not None:
        since_ts = int(
            (datetime.now(timezone.utc) - timedelta(days=window_days)).timestamp()
        )
    else:
        if since:
            try:
                dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                since_ts = int(dt.timestamp())
            except ValueError as exc:
                raise HTTPException(
                    status_code=422, detail=f"Invalid 'since' datetime: {since}"
                ) from exc
        if until:
            try:
                dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
                until_ts = int(dt.timestamp())
            except ValueError as exc:
                raise HTTPException(
                    status_code=422, detail=f"Invalid 'until' datetime: {until}"
                ) from exc

    return since_ts, until_ts


async def _load_games(username: str, time_class: Optional[str], limit: int):
    """Return games for *username* (Chess.com), using the in-memory cache when available.

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


async def _load_games_platform(
    platform: str,
    username: str,
    time_class: Optional[str],
    limit: int,
    since_ts: Optional[int],
    until_ts: Optional[int],
):
    """Return games for *username* on *platform*, using platform-aware cache.

    Applies date (since/until), time_class, and limit filters after retrieval
    so the full cached dataset can serve varied query combinations.
    """
    game_cache.touch(username, platform=platform)

    games = game_cache.get(username, platform=platform)
    if games is None:
        try:
            if platform == "chessdotcom":
                games = await chess_com.get_user_games(username, limit=config.CACHE_MAX_GAMES)
            else:  # lichess
                games = await lichess.get_user_games(username, limit=config.CACHE_MAX_GAMES)
        except Exception as exc:
            platform_label = "Chess.com" if platform == "chessdotcom" else "Lichess"
            raise HTTPException(
                status_code=502, detail=f"{platform_label} API error: {exc}"
            ) from exc
        game_cache.set(username, games, platform=platform)

    if since_ts is not None:
        games = [g for g in games if g.end_time >= since_ts]
    if until_ts is not None:
        games = [g for g in games if g.end_time <= until_ts]
    if time_class:
        games = [g for g in games if g.time_class.lower() == time_class.lower()]
    games = games[:limit]

    if not games:
        raise HTTPException(
            status_code=404,
            detail=f"No games found for user '{username}' on platform '{platform}'"
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


# ---------------------------------------------------------------------------
# Per-move analysis endpoint (platform-aware)
# ---------------------------------------------------------------------------

@router.get("/{platform}/{username}/per-move", response_model=PerMoveResponse)
async def per_move_analysis(
    platform: str,
    username: str,
    n_games: int = Query(
        default=20,
        ge=1,
        le=1000,
        description="Number of most-recent games to analyse",
    ),
    time_class: Optional[str] = Query(
        default=None,
        description="blitz | rapid | bullet | daily | classical",
    ),
    window_days: Optional[int] = Query(
        default=None,
        ge=1,
        description="Limit to games played within the last N days (overrides since/until)",
    ),
    since: Optional[str] = Query(
        default=None,
        description="Include games played on or after this ISO datetime (e.g. 2024-01-01)",
    ),
    until: Optional[str] = Query(
        default=None,
        description="Include games played on or before this ISO datetime (e.g. 2024-12-31)",
    ),
    with_eval: bool = Query(
        default=True,
        description="Fetch Lichess cloud evaluations to compute accuracy and criticality",
    ),
):
    """Return per-move analysis for *username*'s most recent *n_games* games.

    Platform
    --------
    * ``chessdotcom`` – Chess.com
    * ``lichess``     – Lichess

    Each move in the response includes:
    * ``time_spent`` / ``normalized_time`` (relative to player median in that game)
    * ``eval_before`` / ``eval_after`` centipawns (white perspective, from Lichess cloud)
    * ``accuracy`` (0–1), ``criticality`` (0–1), ``combined_metric`` (0–100)
    * Identifiers: ``game_url``, ``game_end_time``, ``ply``, ``move_number``,
      ``color``, ``san``

    Eval-derived fields are ``null`` when the position is absent from the
    Lichess cloud database or ``with_eval=false`` is passed.

    Date filtering
    --------------
    Pass ``window_days`` **or** ``since`` / ``until`` to restrict the games
    included.  The backend applies the filter; the frontend can do additional
    aggregation on the returned data.
    """
    platform_lower = platform.lower()
    if platform_lower not in _SUPPORTED_PLATFORMS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported platform '{platform}'. Use 'chessdotcom' or 'lichess'.",
        )

    since_ts, until_ts = _parse_date_filters(window_days, since, until)
    games = await _load_games_platform(
        platform_lower, username, time_class, n_games, since_ts, until_ts
    )

    if with_eval:
        async with httpx.AsyncClient() as eval_client:
            moves = await analytics_engine.compute_per_move_analysis(
                games, username, eval_client=eval_client
            )
    else:
        moves = await analytics_engine.compute_per_move_analysis(games, username)

    return PerMoveResponse(
        platform=platform_lower,
        username=username,
        games_analyzed=len(games),
        moves=moves,
    )
