"""Pydantic schemas for request/response models."""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class MoveClockEntry(BaseModel):
    """Clock time remaining after a single half-move (ply)."""

    ply: int  # half-move number (1 = white's 1st move, 2 = black's 1st move, …)
    move_number: int  # full-move number (1-based)
    color: str  # "white" or "black"
    clock_after: float  # seconds remaining on clock after this move
    time_spent: Optional[float] = None  # seconds spent on this move (None for first move if no start clock)
    san: Optional[str] = None  # SAN notation of the move
    fen_after: Optional[str] = None  # FEN string of the position after this move


class GameSummary(BaseModel):
    """Lightweight representation of a single chess.com game."""

    url: str
    time_class: str
    time_control: str
    white_username: str
    black_username: str
    white_result: str
    black_result: str
    end_time: int  # Unix timestamp
    rated: bool
    move_clocks: list[MoveClockEntry]


class MoveTimeStats(BaseModel):
    """Aggregated time statistics for a given move number."""

    move_number: int
    color: str
    count: int
    avg_seconds: float
    median_seconds: float
    min_seconds: float
    max_seconds: float
    p25_seconds: float
    p75_seconds: float


class MoveTimeTrendPoint(BaseModel):
    """Average time spent on a specific move, aggregated per day."""

    date: str  # ISO date YYYY-MM-DD
    move_number: int
    color: str
    avg_seconds: float
    game_count: int


class ComparisonData(BaseModel):
    """Side-by-side analytics for two users."""

    username1: str
    username2: str
    move_time_stats1: list[MoveTimeStats]
    move_time_stats2: list[MoveTimeStats]


class PerMoveEntry(BaseModel):
    """Per-move analysis for a single half-move in a game."""

    game_url: str
    game_end_time: int  # Unix timestamp
    ply: int  # half-move number within the game
    move_number: int  # full-move number (1-based)
    color: str  # "white" or "black"
    san: Optional[str] = None  # SAN notation
    time_spent: Optional[float] = None  # seconds spent on this move
    normalized_time: Optional[float] = None  # time_spent / player median time per move
    eval_before: Optional[float] = None  # centipawns (white perspective) before the move
    eval_after: Optional[float] = None  # centipawns (white perspective) after the move
    accuracy: Optional[float] = None  # 0.0–1.0 move quality score
    criticality: Optional[float] = None  # 0.0–1.0 position criticality
    combined_metric: Optional[float] = None  # 0–100 combined score


class PerMoveResponse(BaseModel):
    """Response for the per-move analysis endpoint."""

    platform: str  # "chessdotcom" or "lichess"
    username: str
    games_analyzed: int
    moves: list[PerMoveEntry]
