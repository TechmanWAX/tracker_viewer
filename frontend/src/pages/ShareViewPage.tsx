import { useEffect, useState, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import MapView from '../components/MapView';
import TelemetryDashboard from '../components/TelemetryDashboard';
import PlaybackControls from '../components/PlaybackControls';
import { usePlaybackEngine } from '../hooks/usePlayback';
import { useTelemetryStore } from '../store/telemetryStore';
import { getPublicTrip, getPublicTripPoints } from '../api/public';
import type { Trip } from '../types/trip';

function fmtDate(iso: string): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function fmtDuration(startIso: string, endIso: string): string {
  const s = new Date(startIso).getTime();
  const e = new Date(endIso).getTime();
  if (!Number.isFinite(s) || !Number.isFinite(e) || e <= s) return '—';
  const sec = Math.round((e - s) / 1000);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const ss = sec % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${ss}s`;
  return `${ss}s`;
}

function fmtDistance(meters: number | null): string {
  if (meters == null) return '—';
  if (meters < 1000) return `${Math.round(meters)} m`;
  return `${(meters / 1000).toFixed(2)} km`;
}

export default function ShareViewPage() {
  const { token = '' } = useParams<{ token: string }>();
  const [trip, setTrip] = useState<Trip | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [theme, setTheme] = useState<'light' | 'dark'>(
    () => (document.documentElement.getAttribute('data-theme') as 'light' | 'dark') || 'light',
  );
  const setPoints = useTelemetryStore((s) => s.setPoints);
  usePlaybackEngine();

  const toggleTheme = useCallback(() => {
    const next = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('tracker-theme', next);
    setTheme(next);
  }, [theme]);

  useEffect(() => {
    let cancelled = false;
    setTrip(null);
    setLoadError(null);
    if (!token) return;

    getPublicTrip(token)
      .then((t) => {
        if (cancelled) return;
        setTrip(t);
        if (t.hasGps) {
          getPublicTripPoints(token, 50000).then(({ points, total }) => {
            if (!cancelled) setPoints(points, total);
          });
        }
      })
      .catch((e) => {
        if (!cancelled) setLoadError(String(e));
      });
    return () => { cancelled = true; };
  }, [token, setPoints]);

  return (
    <div className="page-shell" style={{ height: '100dvh' }}>
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '8px 18px',
          background: 'var(--glass-bg)',
          backdropFilter: 'blur(12px)',
          WebkitBackdropFilter: 'blur(12px)',
          borderBottom: '1px solid var(--glass-border)',
        }}
      >
        <Link to="/" style={{ color: 'var(--fg-secondary)', fontSize: 13, textDecoration: 'none' }}>
          GPS Trip Tracker
        </Link>
        <span className="badge badge-accent" style={{ fontSize: 11 }}>Shared trip</span>
        {trip && (
          <div style={{ flex: 1, minWidth: 0 }}>
            <strong style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 14 }}>
              {trip.name}
            </strong>
            <div style={{ fontSize: 11, color: 'var(--fg-muted)' }}>
              {fmtDate(trip.startTime)} → {fmtDate(trip.endTime)} · {fmtDuration(trip.startTime, trip.endTime)} · {fmtDistance(trip.totalDistanceMeters)}
            </div>
          </div>
        )}
        <button onClick={toggleTheme} className="theme-toggle" aria-label="Toggle theme" title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}>
          {theme === 'dark' ? '☀️' : '🌙'}
        </button>
      </header>
      {loadError && (
        <div style={{ padding: 24, textAlign: 'center' }}>
          <h1 style={{ color: 'var(--danger)' }}>Trip not found</h1>
          <p style={{ color: 'var(--fg-secondary)' }}>This link may have expired or been revoked.</p>
        </div>
      )}
      {trip && (
        <div style={{ flex: 1, display: 'grid', gridTemplateRows: '1fr auto', minHeight: 0, overflow: 'hidden' }}>
          <div className="trip-detail-main" style={{ overflow: 'hidden' }}>
            <MapView tripId={trip.id} hasGps={trip.hasGps} skipFetch />
            <div style={{ background: 'var(--bg-primary)', overflow: 'auto', minHeight: 0 }}>
              <TelemetryDashboard />
            </div>
          </div>
          <div className="playback-bar">
            <PlaybackControls />
          </div>
        </div>
      )}
    </div>
  );
}
