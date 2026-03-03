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

---

## Project structure

```
chess-analytics/
├── backend/          # FastAPI application (Python)
│   ├── app/
│   │   ├── main.py            # App entry-point & CORS
│   │   ├── schemas.py         # Pydantic models
│   │   ├── routers/
│   │   │   ├── games.py       # GET /api/games/{username}
│   │   │   └── analytics.py   # GET /api/analytics/…
│   │   └── services/
│   │       ├── chess_com.py       # Chess.com API client + PGN parser
│   │       └── analytics_engine.py # Pure analytics functions
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
uvicorn app.main:app --reload
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
