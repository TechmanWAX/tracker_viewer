# Production Deployment Guide

## Prerequisites
- Domain:  points to your server IP
- SMTP: smtp relay with proper TLS certificate
- DB: PostgreSQL on `localhost:5432` (tracker) — already available
- Ubuntu 24.04 server, Python 3.12+

---

## 1. Production `.env`

Copy this to `backend/.env`. The values below are derived from the
current checked-in defaults with the production-readiness
deferments removed.

```bash
# ─── Database ───────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://tracker:YOUR_PASSWORD@localhost:5432/tracker

# ─── JWT / CSRF secrets (must be 64+ random chars) ────────
# Generate:  python3 -c "import secrets; print(secrets.token_urlsafe(64))"
JWT_SECRET_KEY=YOUR_JWT_SECRET
CSRF_SECRET_KEY=YOUR_CSRF_SECRET

# ─── Security ─────────────────────────────────────────────
COOKIE_SECURE=true
CSRF_ENABLED=true
RATE_LIMIT_ENABLED=true

# ─── Celery (background workers) ─────────────────────────
CELERY_TASK_ALWAYS_EAGER=false
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# ─── Uploads (DO NOT use /tmp) ───────────────────────────
UPLOAD_DIR=/var/lib/tracker/uploads

# ─── CORS ────────────────────────────────────────────────
CORS_ORIGINS=https://your.domain

# ─── App public URL (used for verification email links) ──
APP_BASE_URL=https://your.domain

# ─── Email ───────────────────────────────────────────────
MAIL_ENABLED=true
MAIL_HOST=mail.your.domain
MAIL_PORT=587
MAIL_USERNAME=noreply@your.domain
MAIL_PASSWORD=YOUR_SMTP_PASSWORD
MAIL_FROM=noreply@your.domain
MAIL_DEV_OUT_DIR=/var/lib/tracker/verification_emails
MAIL_TLS_VERIFY=true
```

**What changed vs dev:**

| Variable | Dev → Prod | Why |
|---|---|---|
| `COOKIE_SECURE` | `false` → `true` | AUTH cookies require HTTPS |
| `CSRF_ENABLED` | `false` → `true` | CSRF protection required |
| `RATE_LIMIT_ENABLED` | `false` → `true` | Rate-limiting required |
| `CELERY_TASK_ALWAYS_EAGER` | `true` → `false` | Background jobs to real workers |
| `CELERY_BROKER_URL` | (none) → `redis://localhost:6379/0` | Redis backend for Celery |
| `UPLOAD_DIR` | `/tmp/...` → `/var/lib/...` | Persistent storage |
| `CORS_ORIGINS` | `localhost` → `https://...` | Public origin |
| `APP_BASE_URL` | `localhost` → `https://...` | Public URL |

## 2. Install system dependencies

```bash
## Redis (Celery broker)
sudo apt install -y redis-server

## Nginx (reverse proxy + SSL terminate)
sudo apt install -y nginx

## Certbot (SSL certificates)
sudo apt install -y certbot

## PostgreSQL client (optional)
sudo apt install -y postgresql-client

## Python deps
pip3 install --user uvicorn[standard] gunicorn simple-websocket

## Verify imports
python3 -c "import celery; print(celery.__version__)"
python3 -c "import gunicorn; print(gunicorn.version)"
```

## 3. Build the frontend

```bash
cd backend/../../frontend  # or your project dir
npm ci
npm run build

# The build output is in frontend/dist/
```

## 4. Set up directories and permissions

```bash
# Create persistent directories
sudo mkdir -p /var/lib/tracker/uploads
sudo mkdir -p /var/lib/tracker/verification_emails
sudo mkdir -p /var/www/tracker
sudo chown $USER:$USER /var/lib/tracker/uploads /var/lib/tracker/verification_emails

# Copy frontend build to nginx
sudo cp -r dist/* /var/www/tracker/
```

## 5. Nginx configuration

Create `/etc/nginx/sites-available/tracker`:

```nginx
server {
    listen 80;
    server_name your.domain;

    # Let's Encrypt ACME challenge
    location /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
    }

    # Redirect HTTP to HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl http2;
    server_name your.domain;

    ssl_certificate /etc/letsencrypt/live/your.domain/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your.domain/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;

    # Frontend static files
    root /var/www/tracker;
    index index.html;

    # SPA routing — all non-/* requests go to index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Backend API proxy (gunicorn on 127.0.0.1:8000)
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Timeout for long-running API operations
        proxy_connect_timeout 3600s;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # Deny hidden files
    location ~ /\. {
        deny all;
    }
}
```

```bash
# Create the ACME challenge root
sudo mkdir -p /var/www/letsencrypt/.well-known/acme-challenge

# Enable the config and test
sudo ln -s /etc/nginx/sites-available/tracker /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

# Get the Let's Encrypt certificate (webroot mode)
sudo certbot certonly --webroot -w /var/www/letsencrypt -d your.domain

# Restart nginx to use the new certificate
sudo systemctl restart nginx
```

## 6. Gunicorn systemd service

Create `/etc/systemd/system/tracker.service`:

```ini
[Unit]
Description=GPS Log Tracker API (gunicorn + uvicorn workers)
After=network.target redis.service
Requires=network.target

[Service]
User=tracker
Group=tracker
WorkingDirectory=/home/tracker/backend
ExecStart=/home/tracker/.local/bin/gunicorn \
    --bind 127.0.0.1:8000 \
    --workers 3 \
    --worker-connections 100 \
    --timeout 3600 \
    --graceful-timeout 180 \
    --access-logfile /var/log/tracker/access.log \
    --error-logfile /var/log/tracker/gunicorn-error.log \
    app.main:app

ExecReload=/bin/kill -s HUP $MAINPID
Restart=always
RestartSec=3

LimitNOFILE=65536
AmbientCapabilities=CAP_NET_BIND_SERVICE
Environment=HOME=/home/tracker

[Install]
WantedBy=multi-user.target
```

## 7. Celery worker

Create `/etc/systemd/system/tracker-celery.service`:

```ini
[Unit]
Description=GPS Log Tracker Celery worker
After=network.target redis.service tracker.service
Requires=network.target tracker.service

[Service]
User=tracker
Group=tracker
WorkingDirectory=/home/tracker/GPS Log tracker/backend
ExecStart=/home/tracker/.local/bin/celery \
    -A app.workers.celery_app:celery_app \
    worker \
    --loglevel=info \
    --concurrency=2 \
    --max-tasks-per-child=50

ExecReload=/bin/kill -s HUP $MAINPID
Restart=always
RestartSec=10

LimitNOFILE=65536
Environment=HOME=/home/tracker

[Install]
WantedBy=multi-user.target
```

## 8. Start and verify

```bash
# Create log directories
sudo mkdir -p /var/log/tracker
sudo chown tracker:tracker /var/log/tracker

# Reload systemd and enable all services
sudo systemctl daemon-reload
sudo systemctl enable redis tracker tracker-celery

# Start them
sudo systemctl start redis
sudo systemctl start tracker
sudo systemctl start tracker-celery

# Check they're running
sudo systemctl status redis
sudo systemctl status tracker
sudo systemctl status tracker-celery

# Verify the API endpoint
curl https://your.domain/api/v1/health
```

## 9. Pre-flight checklist

| Item | Command |
|---|---|
| All services running | `sudo systemctl status redis tracker tracker-celery` |
| API responds | `curl https://your.domain/api/v1/health` |
| JWT secret | `grep JWT ./backend/.env` — 64+ random chars |
| CSRF secret | `grep CSRF ./backend/.env` |
| `COOKIE_SECURE=true` | `grep COOKIE backend/.env` |
| `CSRF_ENABLED=true` | `grep CSRF backend/.env` |
| `RATE_LIMIT_ENABLED=true` | `grep RATE_LIMIT backend/.env` |
| HTTPS works | `curl -k https://your.domain` |
| Frontend renders | Browser → `https://your.domain` |
| Full registration flow | Register → check email → verify → upload CSV |
| DB reachable | `psql postgresql://tracker:YOUR_PASSWORD@192.168.41.4:5432/tracker -c 'SELECT version();'` |

### Rollback

If something is misconfigured:

```bash
sudo systemctl stop tracker-celery tracker
sudo systemctl disable tracker-celery tracker

# Remove the nginx config
sudo rm /etc/nginx/sites-enabled/tracker
sudo systemctl reload nginx

# Restore your dev .env if needed
```
