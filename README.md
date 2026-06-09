# GPS Trip Tracker

Upload, parse, and visualize EV controller CSVs — GPS route, real-time playback, full telemetry dashboard with all 24 CSV metrics.

Works with real-world controller firmware: some emit full GPS coords, others only speed/power/battery. No-GPS trips are supported — the map shows a placeholder, the telemetry dashboard still works.

## Quick start (dev)

### Prerequisites

- Python 3.12+
- Node.js 18+
- PostgreSQL 15+ (PostGIS extension)

### Backend

```bash
cd backend

# Install dependencies
pip install -e .

# Create .env with at minimum: DATABASE_URL, JWT_SECRET_KEY, CSRF_SECRET_KEY

# Run migrations
python -m alembic upgrade head

# Start (auto-reload)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# Vite dev proxy: /api/ → http://localhost:8000
```

Open `http://localhost:5173`

### Tests

```bash
# Backend (pytest)
cd backend
python -m pytest app/tests/ -q

# Frontend (tsc — noEmit)
cd frontend
npx tsc --noEmit
```

## Architecture

```
┌─────────────────────────────────────────────┐
│ Browser (React 18 + Vite + TypeScript)      │
│ Leaflet (map) | recharts (charts) | zustand │
└───────────┬─────────────────────────────────┘
            │ HTTPS
┌───────────┴─────────────────────────────────┐
│ Nginx (reverse proxy + SSL termination)     │
│ /api/ → gunicorn → FastAPI                  │
└───────────┬─────────────────────────────────┘
            │
┌───────────┴─────────────────────────────────┐
│ Backend (FastAPI + Async SQLAlchemy 2.0)    │
│  ├── API /trips, /points (HTTPS)            │
│  ├── Celery task: process_csv_async()       │
│  ├── Alembic migrations (01..08)            │
└───────────┬────────────────────┬────────────┘
            │                    │
┌───────────┴──────────┐  ┌──────┴────────────┐
│ PostgreSQL + PostGIS │  │ Redis (broker)    │
│ + TimescaleDB        │  └───────────────────┘
│ hypertable           │
└──────────────────────┘
```

## Tech stack

| Layer | Tech |
|---|---|
| **Frontend** | React 18, TypeScript, Vite, Leaflet, recharts, zustand |
| **Backend** | FastAPI, SQLAlchemy 2.0 (async), Pydantic |
| **Database** | PostgreSQL 15+, PostGIS, TimescaleDB |
| **Background** | Celery, Redis |
| **Deployment** | gunicorn (uvicorn workers), Nginx, Let's Encrypt, systemd |

## Features

- **CSV upload** — any EV controller CSV (24 columns). Skips corrupted rows, `ON CONFLICT` dedup.
- **GPS map** — Leaflet canvas, polyline, auto-fit, RDP simplification (5000 pts cap)
- **Playback** — time-based replay (1x/2x/4x/8x), seek, pause/resume, cursor sync with map + dashboard
- **Telemetry dashboard** — all 24 CSV fields: speed, GPS speed, voltage, current, phase current, power, torque, PWM, battery level, distance, system temp, temp2, tilt, roll, mode, alert (GPS alt/heading/distance, lifetime odometer). Trip summary: avg/max speed, peak power, max/min battery.
- **Email verification** — SMTP (STARTTLS/implicit TLS), dev-fallback to files
- **Security** — JWT auth, CSRF, rate limiting, cookie rotation, production-readiness gate
- **No-GPS firmware** — trips without lat/lng: schema (nullable lat/lon, `has_gps` flag), placeholder UI, telemetry works

## Directory structure

```
backend/
├── app/
│   ├── api/v1/endpoints/   # routes
│   ├── core/               # config, dependencies
│   ├── models/             # SQLAlchemy ORM
│   ├── repositories/       # data access
│   ├── services/           # core logic
│   ├── workers/            # Celery tasks
│   ├── alembic/            # migrations
│   └── tests/              # pytest
├── pyproject.toml
└── .env                    # ⚠️ secrets (gitignored)

frontend/
├── src/
│   ├── api/                # axios client
│   ├── components/         # MapView, TelemetryDashboard
│   ├── hooks/              # usePlayback, useTripUpload
│   ├── pages/              # TripListPage, TripDetailPage
│   ├── store/              # zustand
│   └── types/              # TS interfaces
├── vite.config.ts          # dev proxy: /api → localhost:8000
└── package.json
```

## Production

See **`PROD_DEPLOY.md`** for the complete deployment guide.

| Service | Command |
|---|---|
| **Backend** | `sudo systemctl start tracklog` (gunicorn + uvicorn, 3 workers) |
| **Celery** | `sudo systemctl start tracklog-celery` (CSV parser worker) |
| **Nginx** | HTTPS/SSL, `/api/` → gunicorn, SPA routing |
| **Redis** | `sudo systemctl start redis` (broker) |

