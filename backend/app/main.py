"""FastAPI application entry-point."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import analytics, games

app = FastAPI(
    title="Chess Analytics API",
    description=(
        "Fetch chess.com games and compute time-per-move analytics. "
        "Filter by time class (blitz, rapid, …), track time evolution over dates, "
        "and compare two players side-by-side."
    ),
    version="1.0.0",
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
