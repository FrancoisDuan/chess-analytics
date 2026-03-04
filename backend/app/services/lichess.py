"""Lichess public API client.

Fetches user games via the Lichess NDJSON API and converts them to the shared
GameSummary model used by the analytics engine.

Clock data comes from the ``clocks`` array (centiseconds, alternating
white/black) returned when the ``clocks=true`` query parameter is set.
FEN after each half-move is computed locally with python-chess so that
Lichess cloud evaluations can be retrieved without an extra round-trip.
"""
from __future__ import annotations

import json
from typing import Optional

import chess
import httpx

from app.schemas import GameSummary, MoveClockEntry

_BASE = "https://lichess.org/api"
_HEADERS = {
    "User-Agent": "chess-analytics-app/1.0",
    "Accept": "application/x-ndjson",
}

# Map Lichess speed names to the common time_class values used internally.
_SPEED_TO_TIME_CLASS: dict[str, str] = {
    "bullet": "bullet",
    "blitz": "blitz",
    "rapid": "rapid",
    "classical": "classical",
    "correspondence": "daily",
    "ultrabullet": "bullet",
}

# Map common time_class → Lichess perfType filter.
_TIME_CLASS_TO_PERF: dict[str, str] = {
    "bullet": "bullet",
    "blitz": "blitz",
    "rapid": "rapid",
    "classical": "classical",
    "daily": "correspondence",
}


def _build_move_clocks(raw: dict) -> list[MoveClockEntry]:
    """Build MoveClockEntry list from a Lichess NDJSON game object.

    Lichess returns:
    * ``moves``: space-separated SAN string
    * ``clocks``: list of centisecond clock values, alternating white / black
      (index 0 = white after move 1, index 1 = black after move 1, …)

    FEN after each half-move is computed by replaying moves with python-chess.
    """
    moves_str = raw.get("moves", "")
    moves_san = moves_str.split() if moves_str else []
    clocks_cs: list[int] = raw.get("clocks", [])

    if not moves_san:
        return []

    board = chess.Board()
    entries: list[MoveClockEntry] = []
    prev_clock: dict[str, Optional[float]] = {"white": None, "black": None}

    for ply_0, san in enumerate(moves_san):
        color = "white" if ply_0 % 2 == 0 else "black"
        move_number = ply_0 // 2 + 1
        ply = ply_0 + 1

        # Advance the board to get FEN and validate the SAN.
        try:
            move = board.parse_san(san)
            board.push(move)
            fen_after: Optional[str] = board.fen()
        except Exception:
            # Unrecognised SAN: skip this move and all subsequent ones
            # to avoid corrupting the board state and FEN values.
            break

        # Clock value (centiseconds → seconds).
        clock_sec: Optional[float] = None
        if ply_0 < len(clocks_cs):
            clock_sec = clocks_cs[ply_0] / 100.0

        spent: Optional[float] = None
        if clock_sec is not None and prev_clock[color] is not None:
            diff = prev_clock[color] - clock_sec  # type: ignore[operator]
            if diff >= 0:
                spent = diff

        entries.append(
            MoveClockEntry(
                ply=ply,
                move_number=move_number,
                color=color,
                clock_after=clock_sec if clock_sec is not None else 0.0,
                time_spent=spent,
                san=san,
                fen_after=fen_after,
            )
        )

        if clock_sec is not None:
            prev_clock[color] = clock_sec

    return entries


def _build_game_summary(raw: dict) -> Optional[GameSummary]:
    """Convert a Lichess NDJSON game object into a GameSummary, or None."""
    try:
        players = raw.get("players", {})
        white_info = players.get("white", {})
        black_info = players.get("black", {})

        white_username = (white_info.get("user") or {}).get("name", "unknown")
        black_username = (black_info.get("user") or {}).get("name", "unknown")

        winner = raw.get("winner")  # "white", "black", or absent (draw)
        white_result = "win" if winner == "white" else ("lose" if winner == "black" else "agreed")
        black_result = "win" if winner == "black" else ("lose" if winner == "white" else "agreed")

        speed = raw.get("speed", "unknown")
        time_class = _SPEED_TO_TIME_CLASS.get(speed, speed)

        clock_info = raw.get("clock", {})
        initial = clock_info.get("initial", 0) if clock_info else 0
        increment = clock_info.get("increment", 0) if clock_info else 0
        time_control = f"{initial}+{increment}" if clock_info else "unknown"

        game_id = raw.get("id", "")
        url = f"https://lichess.org/{game_id}"

        # Lichess timestamps are in milliseconds; convert to seconds.
        end_time = (raw.get("lastMoveAt") or raw.get("createdAt") or 0) // 1000

        move_clocks = _build_move_clocks(raw)

        return GameSummary(
            url=url,
            time_class=time_class,
            time_control=time_control,
            white_username=white_username,
            black_username=black_username,
            white_result=white_result,
            black_result=black_result,
            end_time=end_time,
            rated=raw.get("rated", False),
            move_clocks=move_clocks,
        )
    except (KeyError, TypeError):
        return None


async def get_user_games(
    username: str,
    time_class: Optional[str] = None,
    limit: Optional[int] = None,
    since: Optional[int] = None,
    until: Optional[int] = None,
) -> list[GameSummary]:
    """Fetch and return games for a Lichess user.

    Parameters
    ----------
    username:
        Lichess username (case-insensitive).
    time_class:
        Optional filter: 'blitz', 'rapid', 'bullet', 'daily', 'classical'.
    limit:
        Maximum number of games to return.
    since:
        Include only games played on or after this Unix timestamp (seconds).
    until:
        Include only games played on or before this Unix timestamp (seconds).
    """
    params: dict[str, str] = {
        "clocks": "true",
        "max": str(limit or 100),
    }
    if time_class:
        perf = _TIME_CLASS_TO_PERF.get(time_class.lower())
        if perf:
            params["perfType"] = perf
    # Lichess API uses milliseconds for since/until.
    if since is not None:
        params["since"] = str(since * 1000)
    if until is not None:
        params["until"] = str(until * 1000)

    url = f"{_BASE}/games/user/{username}"
    games: list[GameSummary] = []

    async with httpx.AsyncClient() as client:
        async with client.stream("GET", url, headers=_HEADERS, params=params, timeout=60) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                summary = _build_game_summary(raw)
                if summary is None:
                    continue
                games.append(summary)
                if limit and len(games) >= limit:
                    break

    return games
