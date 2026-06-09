# GPS Log Tracker Backend

Production-grade FastAPI backend for GPS trip tracking with TimescaleDB and PostGIS.

## Features

- ✅ Async FastAPI with SQLAlchemy 2.0
- ✅ TimescaleDB hypertables for time-series telemetry
- ✅ PostGIS for spatial queries
- ✅ JWT authentication with HttpOnly cookies
- ✅ CSRF protection (double-submit pattern)
- ✅ Rate limiting with SlowAPI
- ✅ Async CSV parsing with Celery workers
- ✅ Bulk insert for high-performance data ingestion

## Architecture

```
Frontend (React) → FastAPI → Celery Worker → TimescaleDB + PostGIS
                              ↓
                         Redis (Broker)
```

## Prerequisites

- Python 3.11+
- PostgreSQL 14+ with TimescaleDB and PostGIS extensions
- Redis 6+ (for Celery broker)
- uv (Python package manager)

## Installation

```bash
cd backend

# Install dependencies
uv sync

# Set up environment variables
cp .env.example .env
# Edit .env with your database and Redis connection strings

# Run migrations
uv run alembic upgrade head

# Start the development server
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Start Celery worker
uv run celery -A app.workers.celery_app.celery_app worker --loglevel=info

# Start Celery beat (for periodic tasks)
uv run celery -A app.workers.celery_app.celery_app beat --loglevel=info
```

## API Documentation

Once the server is running, visit:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Project Structure

```
backend/
├── app/
│   ├── api/          # API endpoints
│   ├── core/         # Core utilities (config, security)
│   ├── db/           # Database session management
│   ├── models/       # SQLAlchemy models
│   ├── schemas/      # Pydantic schemas
│   ├── services/     # Business logic
│   ├── repositories/ # Data access layer
│   ├── workers/      # Celery tasks
│   └── tests/        # Test suite
├── alembic/          # Database migrations
└── pyproject.toml    # Project dependencies
```

## Environment Variables

```env
# Application
APP_NAME="GPS Log Tracker API"
DEBUG=false

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/gps_tracker

# JWT
JWT_SECRET_KEY=your-secret-key
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# CORS
CORS_ORIGINS=http://localhost:3000,http://localhost:8080

# Rate Limiting
RATE_LIMIT_REQUESTS=10
RATE_LIMIT_WINDOW_SECONDS=60

# Celery
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# File Upload
MAX_UPLOAD_SIZE_MB=100
UPLOAD_DIR=/tmp/gps_tracker_uploads
```

## Development

```bash
# Run tests
uv run pytest

# Run linter
uv run ruff check .

# Format code
uv run ruff format .
```

## Production Deployment

1. Set `DEBUG=false` in environment
2. Use a production-grade WSGI server (Gunicorn + Uvicorn workers)
3. Configure proper CORS origins
4. Enable HTTPS
5. Use environment variables for all secrets
6. Set up database backups
7. Monitor Celery worker health

## License

MIT