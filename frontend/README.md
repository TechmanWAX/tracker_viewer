# GPS Tracker — Frontend

React 18 + TypeScript + Vite. Talks to the FastAPI backend over `withCredentials` cookies (HttpOnly access + refresh + CSRF).

## Run

```bash
cp .env.example .env       # adjust VITE_API_BASE_URL if needed
npm install
npm run dev                # http://localhost:5173
```

## Build

```bash
npm run build
npm run preview
```

## Typecheck

```bash
npm run typecheck
```

## Architecture

- `src/api/` — axios client with `withCredentials`, CSRF interceptor, 401-refresh-retry
- `src/store/` — Zustand stores: auth, trip, telemetry (high-frequency `currentIndex`)
- `src/lib/csrf.ts` — reads `csrf_token` cookie, sets `X-CSRF-Token` header
- `src/hooks/usePlayback.ts` — wraps `5 — Playback Engine.ts`
- `src/components/MapView.tsx` — wraps `6 — Map Rendering.tsx`
- `src/components/TelemetryDashboard.tsx` — wraps `7 — Telemetry UI.tsx`
- `src/pages/TripDetailPage.tsx` — composes map + telemetry + playback

## Auth flow

1. `POST /auth/login` → server sets `access_token`, `refresh_token`, `csrf_token` cookies.
2. Every state-changing request: client reads `csrf_token` cookie → sends in `X-CSRF-Token`.
3. On 401: client calls `POST /auth/refresh` once, retries; on 401 again → redirect `/login`.
