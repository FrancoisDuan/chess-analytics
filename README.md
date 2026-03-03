# Chess Analytics

A full-stack web application for exploring **time-per-move** analytics from [Chess.com](https://chess.com) games.

## Features

| Endpoint / Feature | Description |
|--------------------|-------------|
| Fetch games | Retrieve all (or filtered) games for any chess.com username |
| Filter by time class | `blitz`, `rapid`, `bullet`, `daily`, `classical` |
| Move-time stats | For each move number: avg / median / P25 / P75 seconds |
| Move-time trend | How time-per-move has evolved over calendar dates |
| Compare two players | Side-by-side move-time stats for two usernames |
| **Auto-refresh** | Game data for recently-active users is refreshed automatically in the background |

---

## Project structure

```
chess-analytics/
├── backend/          # FastAPI application (Python)
│   ├── app/
│   │   ├── main.py            # App entry-point, CORS, background refresh task
│   │   ├── config.py          # Env-var-backed settings (refresh interval, etc.)
│   │   ├── schemas.py         # Pydantic models (add new ones here for new analytics)
│   │   ├── routers/
│   │   │   ├── games.py       # GET /api/games/{username}
│   │   │   └── analytics.py   # GET /api/analytics/…
│   │   └── services/
│   │       ├── cache.py           # In-memory game cache + activity tracker
│   │       ├── chess_com.py       # Chess.com API client + PGN parser
│   │       └── analytics_engine.py # Pure analytics functions (extend here)
│   ├── tests/
│   └── requirements.txt
└── frontend/         # React + Vite application
    └── src/
        ├── App.jsx
        ├── components/
        │   ├── UserSearchForm.jsx
        │   ├── MoveTimeChart.jsx   # Bar chart: avg seconds per move #
        │   ├── MoveTrendChart.jsx  # Line chart: time over dates
        │   └── CompareChart.jsx    # Side-by-side bar chart
        └── services/api.js
```

---

## Quick start

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# API docs: http://localhost:8000/docs
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# UI: http://localhost:5173
```

### Tests

```bash
cd backend
pytest tests/ -v
```

---

## Automatic background refresh

On startup the backend launches a background task that periodically re-fetches
game data from chess.com for every **recently-active** user and updates the
in-memory cache.  All subsequent analytics requests are served directly from
the cache (no extra chess.com round-trip), so the data stays fresh without any
user-visible latency.

| Environment variable | Default | Description |
|---|---|---|
| `REFRESH_INTERVAL_MINUTES` | `30` | How often the refresh task runs |
| `ACTIVE_USER_DAYS` | `7` | How many days back to consider a user "active" |
| `CACHE_MAX_GAMES` | `500` | Max games fetched and cached per user |

Example – refresh every 15 minutes, keep users active for 14 days:

```bash
REFRESH_INTERVAL_MINUTES=15 ACTIVE_USER_DAYS=14 uvicorn app.main:app
```

---

## Adding new analytics

The codebase is structured so that each new analytic requires changes in
exactly three small places:

1. **`app/schemas.py`** – add a Pydantic response model (or reuse an existing one).
2. **`app/services/analytics_engine.py`** – add a pure function with the
   signature `(games: list[GameSummary], ...) -> YourModel | list[YourModel]`.
   No data-fetching logic belongs here.
3. **`app/routers/analytics.py`** – add a `@router.get` endpoint that calls
   `_load_games` (handles caching automatically) and then your new engine
   function.

**No changes** to `chess_com.py`, `cache.py`, or `main.py` are required for
new analytics.

### Example – win-rate analytic

```python
# 1. schemas.py
class WinRateStats(BaseModel):
    username: str
    wins: int
    draws: int
    losses: int
    win_rate: float

# 2. analytics_engine.py
def compute_win_rate(games: list[GameSummary], username: str) -> WinRateStats:
    username_lower = username.lower()
    wins = draws = losses = 0
    for g in games:
        if g.white_username.lower() == username_lower:
            result = g.white_result
        elif g.black_username.lower() == username_lower:
            result = g.black_result
        else:
            continue
        if result == "win":
            wins += 1
        elif result in ("agreed", "repetition", "stalemate", "insufficient", "timevsinsufficient", "50move"):
            draws += 1
        else:
            losses += 1
    total = wins + draws + losses
    return WinRateStats(
        username=username, wins=wins, draws=draws, losses=losses,
        win_rate=round(wins / total, 4) if total else 0.0,
    )

# 3. analytics.py – add one endpoint
@router.get("/{username}/win-rate", response_model=WinRateStats)
async def win_rate(
    username: str,
    time_class: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    games = await _load_games(username, time_class, limit)
    return analytics_engine.compute_win_rate(games, username)
```

---

## API Reference

### Games

```
GET /api/games/{username}
  ?time_class=blitz        # filter by time class
  ?limit=50                # max games (1–500, default 50)
```

### Analytics

```
GET /api/analytics/{username}/move-time
  ?time_class=blitz
  ?limit=100
  ?move_limit=20           # only analyse first N moves

GET /api/analytics/{username}/move-time-trend
  ?time_class=rapid
  ?limit=200
  ?move_numbers=1,2,3      # track specific moves; omit for overall

GET /api/analytics/compare/{username1}/{username2}
  ?time_class=blitz
  ?limit=100
  ?move_limit=20
```

Interactive docs at **http://localhost:8000/docs** after starting the backend.
