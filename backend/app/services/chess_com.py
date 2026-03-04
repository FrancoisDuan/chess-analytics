"""Chess.com public API client.

Fetches monthly game archives and parses per-move clock times from PGN.
"""
from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from typing import Optional

import chess
import chess.pgn
import httpx

from app.schemas import GameSummary, MoveClockEntry

# Chess.com rate-limiting is lenient for the public API; no auth required.
_BASE = "https://api.chess.com/pub/player"
_HEADERS = {"User-Agent": "chess-analytics-app/1.0 (contact: dev@chess-analytics.local)"}

# Regex to capture [%clk H:MM:SS] or [%clk MM:SS] annotations inside PGN comments.
_CLK_RE = re.compile(r"\[%clk\s+(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)\]")


def _parse_clock(annotation: str) -> Optional[float]:
    """Return seconds from a '[%clk …]' annotation string, or None."""
    m = _CLK_RE.search(annotation)
    if not m:
        return None
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2))
    seconds = float(m.group(3))
    return hours * 3600 + minutes * 60 + seconds


def _extract_move_clocks(pgn: str) -> list[MoveClockEntry]:
    """Parse PGN text and return a MoveClockEntry per half-move that has a clock.

    Uses python-chess to walk through the game so that SAN notation and the FEN
    after each move can be captured alongside the clock information.

    Falls back to the legacy regex parser if python-chess cannot read the PGN.
    """
    try:
        game = chess.pgn.read_game(io.StringIO(pgn))
    except Exception:
        game = None

    if game is not None:
        return _extract_move_clocks_pgn(game)

    # Fallback: regex-only (no SAN / FEN, but clock values are correct).
    return _extract_move_clocks_regex(pgn)


def _extract_move_clocks_pgn(game: chess.pgn.Game) -> list[MoveClockEntry]:
    """Walk a parsed python-chess game and build MoveClockEntry objects."""
    entries: list[MoveClockEntry] = []
    board = game.board()
    prev_clock: dict[str, Optional[float]] = {"white": None, "black": None}
    ply = 0

    for node in game.mainline():
        color = "white" if board.turn == chess.WHITE else "black"
        move_number = board.fullmove_number
        san = board.san(node.move)
        board.push(node.move)
        fen_after = board.fen()
        ply += 1

        clock_val = _parse_clock(node.comment)
        if clock_val is None:
            # Skip half-moves that carry no clock annotation.
            # Note: ply is still incremented so that the ply field in each
            # returned entry reflects the actual half-move position in the
            # game (not just a sequential counter over clock-annotated moves).
            continue

        spent: Optional[float] = None
        if prev_clock[color] is not None:
            diff = prev_clock[color] - clock_val  # type: ignore[operator]
            if diff >= 0:
                spent = diff

        entries.append(
            MoveClockEntry(
                ply=ply,
                move_number=move_number,
                color=color,
                clock_after=clock_val,
                time_spent=spent,
                san=san,
                fen_after=fen_after,
            )
        )
        prev_clock[color] = clock_val

    return entries


def _extract_move_clocks_regex(pgn: str) -> list[MoveClockEntry]:
    """Legacy regex-based clock extractor (no SAN / FEN)."""
    half_move_re = re.compile(
        r"(\d+)(\.{1,3})\s+\S+\s*"  # move-number, dots, SAN
        r"\{[^}]*\[%clk\s+(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)\][^}]*\}"  # clock comment
    )

    entries: list[MoveClockEntry] = []
    prev_clock: dict[str, Optional[float]] = {"white": None, "black": None}
    ply = 0

    for m in half_move_re.finditer(pgn):
        move_number = int(m.group(1))
        color = "black" if len(m.group(2)) > 1 else "white"
        hours = int(m.group(3) or 0)
        minutes = int(m.group(4))
        seconds = float(m.group(5))
        clock_val = hours * 3600 + minutes * 60 + seconds

        ply += 1
        spent: Optional[float] = None
        if prev_clock[color] is not None:
            diff = prev_clock[color] - clock_val  # type: ignore[operator]
            if diff >= 0:
                spent = diff

        entries.append(
            MoveClockEntry(
                ply=ply,
                move_number=move_number,
                color=color,
                clock_after=clock_val,
                time_spent=spent,
            )
        )
        prev_clock[color] = clock_val

    return entries


async def fetch_archives(username: str, client: httpx.AsyncClient) -> list[str]:
    """Return list of archive URLs for a chess.com user (oldest first)."""
    url = f"{_BASE}/{username}/games/archives"
    resp = await client.get(url, headers=_HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json().get("archives", [])


async def fetch_games_from_archive(archive_url: str, client: httpx.AsyncClient) -> list[dict]:
    """Return raw game dicts from a single monthly archive URL."""
    resp = await client.get(archive_url, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json().get("games", [])


def _build_game_summary(raw: dict) -> Optional[GameSummary]:
    """Convert a raw chess.com game dict into a GameSummary, or None if invalid."""
    try:
        pgn = raw.get("pgn", "")
        move_clocks = _extract_move_clocks(pgn)
        return GameSummary(
            url=raw["url"],
            time_class=raw.get("time_class", "unknown"),
            time_control=raw.get("time_control", "unknown"),
            white_username=raw["white"]["username"],
            black_username=raw["black"]["username"],
            white_result=raw["white"]["result"],
            black_result=raw["black"]["result"],
            end_time=raw.get("end_time", 0),
            rated=raw.get("rated", False),
            move_clocks=move_clocks,
        )
    except (KeyError, TypeError):
        return None


async def get_user_games(
    username: str,
    time_class: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[GameSummary]:
    """Fetch and return all (or a limited number of) games for a chess.com user.

    Parameters
    ----------
    username:
        Chess.com username (case-insensitive).
    time_class:
        Optional filter: 'blitz', 'rapid', 'bullet', 'daily', 'classical'.
    limit:
        Maximum number of games to return (most recent first).
    """
    username = username.lower()
    games: list[GameSummary] = []

    async with httpx.AsyncClient() as client:
        archives = await fetch_archives(username, client)
        # Process most-recent archives first so we can respect the limit early.
        for archive_url in reversed(archives):
            raw_games = await fetch_games_from_archive(archive_url, client)
            for raw in reversed(raw_games):  # most recent within month first
                summary = _build_game_summary(raw)
                if summary is None:
                    continue
                if time_class and summary.time_class.lower() != time_class.lower():
                    continue
                games.append(summary)
                if limit and len(games) >= limit:
                    return games

    return games
