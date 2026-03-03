"""Application configuration loaded from environment variables.

Override any value by setting the corresponding environment variable before
starting the server, e.g.::

    REFRESH_INTERVAL_MINUTES=15 ACTIVE_USER_DAYS=14 uvicorn app.main:app

All variables have sensible defaults so no configuration is required for a
standard local run.
"""
from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Background-refresh settings
# ---------------------------------------------------------------------------

# How often (in minutes) the background task re-fetches game data from
# chess.com for every recently active user.
REFRESH_INTERVAL_MINUTES: int = int(os.getenv("REFRESH_INTERVAL_MINUTES", "30"))

# A user is considered "active" – and therefore eligible for auto-refresh –
# if they have made at least one API request within this many days.
ACTIVE_USER_DAYS: int = int(os.getenv("ACTIVE_USER_DAYS", "7"))

# Maximum number of games fetched (and cached) per user during a refresh.
# Requests that ask for fewer games are served directly from this cached set.
CACHE_MAX_GAMES: int = int(os.getenv("CACHE_MAX_GAMES", "500"))
