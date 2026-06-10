import { useEffect, useState, type FormEvent } from 'react';
import { useNavigate, useParams, Link } from 'react-router-dom';
import MapView from '../components/MapView';
import TelemetryDashboard from '../components/TelemetryDashboard';
import PlaybackControls from '../components/PlaybackControls';
import AppHeader from '../components/AppHeader';
import { usePlaybackEngine } from '../hooks/usePlayback';
import { getTrip, updateTrip, deleteTrip } from '../api/trips';
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

export default function TripDetailPage() {
  usePlaybackEngine();
  const { tripId = '' } = useParams<{ tripId: string }>();
  const navigate = useNavigate();

  const [trip, setTrip] = useState<Trip | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState('');
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setTrip(null);
    setLoadError(null);
    if (!tripId) return;
    getTrip(tripId)
      .then((t) => {
        if (!cancelled) {
          setTrip(t);
          setEditName(t.name);
        }
      })
      .catch((e) => {
        if (!cancelled) setLoadError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [tripId]);

  async function onSaveEdit(e: FormEvent) {
    e.preventDefault();
    if (!trip || !editName.trim()) return;
    setSaving(true);
    try {
      const updated = await updateTrip(trip.id, { name: editName.trim() });
      setTrip(updated);
      setEditing(false);
    } catch (err) {
      setLoadError(String(err));
    } finally {
      setSaving(false);
    }
  }

  async function onDelete() {
    if (!trip) return;
    if (!window.confirm(`Delete trip "${trip.name}"?\nAll telemetry will be removed.`)) return;
    setDeleting(true);
    try {
      await deleteTrip(trip.id);
      navigate('/trips', { replace: true });
    } catch (err) {
      setLoadError(String(err));
      setDeleting(false);
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <AppHeader />
      <div
        style={{
          padding: '10px 16px',
          background: 'var(--bg-2)',
          borderBottom: '1px solid #000',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
        }}
      >
        <Link to="/trips" style={{ color: 'var(--accent)' }}>
          ← Trips
        </Link>
        <div style={{ flex: 1, minWidth: 0 }}>
          {editing ? (
            <form
              onSubmit={onSaveEdit}
              style={{ display: 'flex', gap: 6, alignItems: 'center' }}
            >
              <input
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                required
                minLength={1}
                maxLength={255}
                autoFocus
                style={{ flex: 1, padding: 6, minWidth: 200 }}
              />
              <button type="submit" disabled={saving}>
                {saving ? 'Saving…' : 'Save'}
              </button>
              <button
                type="button"
                onClick={() => {
                  setEditing(false);
                  setEditName(trip?.name ?? '');
                }}
                disabled={saving}
              >
                Cancel
              </button>
            </form>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
              <strong style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {trip?.name ?? (loadError ? 'Trip' : 'Loading…')}
              </strong>
              {trip && (
                <button onClick={() => setEditing(true)} aria-label="Rename trip" style={{ fontSize: 12 }}>
                  Rename
                </button>
              )}
            </div>
          )}
          {trip && !editing && (
            <div style={{ fontSize: 11, opacity: 0.6, marginTop: 2 }}>
              {fmtDate(trip.startTime)} → {fmtDate(trip.endTime)} · {fmtDuration(trip.startTime, trip.endTime)} · {fmtDistance(trip.totalDistanceMeters)}
            </div>
          )}
        </div>
        {trip && (
          <button
            onClick={onDelete}
            disabled={deleting}
            style={{ color: 'var(--danger)' }}
            aria-label="Delete trip"
          >
            {deleting ? 'Deleting…' : 'Delete'}
          </button>
        )}
      </div>
      {loadError && (
        <div style={{ padding: 12, color: 'var(--danger)' }}>
          {loadError} <Link to="/trips">Back to trips</Link>
        </div>
      )}
      <div style={{ flex: 1, display: 'grid', gridTemplateRows: '1fr auto', minHeight: 0 }}>
        <div className="trip-detail-main" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1, background: '#000' }}>
          <MapView tripId={tripId} hasGps={trip?.hasGps ?? true} />
          <div style={{ background: 'var(--bg)', overflow: 'auto' }}>
            <TelemetryDashboard />
          </div>
        </div>
        <div style={{ padding: 8, background: 'var(--bg-2)' }}>
          <PlaybackControls />
        </div>
      </div>
    </div>
  );
}
