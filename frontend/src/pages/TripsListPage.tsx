import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { listTrips, deleteTrip } from '../api/trips';
import type { Trip } from '../types/trip';
import AppHeader from '../components/AppHeader';

function fmtDate(iso: string): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
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

/**
 * Status of a per-row delete attempt. We track this in component
 * state (not a local `useRef`) so that the React tree re-renders
 * when a row enters the "confirming" / "deleting" / "error" state —
 * and so the inline message stays visible.
 */
type RowDeleteState =
  | { kind: 'idle' }
  | { kind: 'confirming' }
  | { kind: 'deleting' }
  | { kind: 'error'; message: string };

function rowErrorMessage(e: unknown): string {
  // Map the most common backend errors onto a one-liner the user can
  // act on, instead of dumping a multi-line AxiosError string.
  const anyE = e as {
    response?: { status?: number; data?: { detail?: string } };
    message?: string;
  };
  const status = anyE.response?.status;
  const detail = anyE.response?.data?.detail;
  if (status === 401) return 'Session expired. Please sign in again.';
  if (status === 403) {
    return detail
      ? `Permission denied: ${detail}`
      : 'Permission denied (CSRF token missing or invalid). Try reloading the page.';
  }
  if (status === 404) return 'Trip no longer exists (it may have been deleted from another tab).';
  if (status === 429) return 'Too many requests. Wait a few seconds and try again.';
  if (status && status >= 500) return `Server error (${status}). Please try again.`;
  return anyE.message || 'Delete failed. Please try again.';
}

export default function TripsListPage() {
  const [trips, setTrips] = useState<Trip[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // Map<tripId, RowDeleteState>. We use a map instead of a single
  // `deletingId` so that:
  //   1. The "Delete" button can flip to "Sure?" without hiding other
  //      rows' buttons (a single `deletingId` would block all rows).
  //   2. The row can show a per-trip error message that persists
  //      until the user does something about it.
  const [rowState, setRowState] = useState<Record<string, RowDeleteState>>({});
  const navigate = useNavigate();

  const setRow = (id: string, s: RowDeleteState) =>
    setRowState((cur) => ({ ...cur, [id]: s }));
  const clearRow = (id: string) =>
    setRowState((cur) => {
      if (!(id in cur)) return cur;
      const { [id]: _, ...rest } = cur;
      return rest;
    });

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const ts = await listTrips();
      setTrips(ts);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  /**
   * First click on "Delete": flip the row into the `confirming` state.
   * Second click on "Sure?": actually fire the DELETE.
   * We deliberately avoid `window.confirm` here because:
   *   - It can be silently blocked by some browsers / extensions.
   *   - It blocks the JS event loop, which makes it feel laggy.
   *   - The user can't tell which row the prompt is for (a
   *     second confirmation can also pop up over the wrong row).
   * Inline confirmation keeps the action bound to the row that was
   * clicked and gives us full styling control.
   */
  function onDeleteClick(t: Trip) {
    const current = rowState[t.id]?.kind;
    if (current === 'deleting') return; // already in flight
    if (current === 'confirming') {
      void onDeleteConfirmed(t);
      return;
    }
    setRow(t.id, { kind: 'confirming' });
  }

  function onCancelConfirm(t: Trip) {
    setRow(t.id, { kind: 'idle' });
  }

  async function onDeleteConfirmed(t: Trip) {
    setRow(t.id, { kind: 'deleting' });
    try {
      await deleteTrip(t.id);
      // Drop the row from the local list. We do this on success
      // (not optimistically) so the user always sees the explicit
      // "Deleting…" state during the network call — there's no
      // possibility of the row "blipping" out and back in.
      setTrips((cur) => cur.filter((x) => x.id !== t.id));
      clearRow(t.id);
    } catch (e: unknown) {
      // 404 means the trip was already gone (e.g. deleted in another
      // tab). Treat that as success: drop the row, no error to show.
      const status = (e as { response?: { status?: number } })?.response?.status;
      if (status === 404) {
        setTrips((cur) => cur.filter((x) => x.id !== t.id));
        clearRow(t.id);
        return;
      }
      setRow(t.id, { kind: 'error', message: rowErrorMessage(e) });
    }
  }

  return (
    <div className="page-shell">
      <AppHeader />
      <div className="page-main fade-in">
        <h1 style={{ marginBottom: 20 }}>Trips</h1>
        {loading && <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>{[1, 2, 3].map((i) => <div key={i} className="skeleton" style={{ height: 60 }} />)}</div>}
        {error && (
          <div style={{ color: 'var(--danger)', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
            {error}{' '}
            <button onClick={refresh} className="btn-sm">Retry</button>
          </div>
        )}
        {!loading && trips.length === 0 && (
          <div className="card" style={{ padding: 32, textAlign: 'center' }}>
            <div style={{ fontSize: 36, marginBottom: 8, opacity: 0.3 }}>📂</div>
            <p style={{ color: 'var(--fg-secondary)' }}>No trips yet.</p>
            <Link to="/trips/upload" className="btn-primary" style={{ display: 'inline-flex', marginTop: 12, textDecoration: 'none' }}>
              Upload your first CSV
            </Link>
          </div>
        )}
        {trips.length > 0 && trips.map((t) => {
          const state = rowState[t.id]?.kind ?? 'idle';
          const errMsg = rowState[t.id]?.kind === 'error'
            ? (rowState[t.id] as { kind: 'error'; message: string }).message
            : null;
          return (
            <div key={t.id} className="trip-card">
              <div className="trip-card-body">
                <Link to={`/trips/${t.id}`} className="trip-card-name">
                  {t.name}
                </Link>
                <div className="trip-card-meta">
                  <span>{fmtDate(t.startTime)} → {fmtDate(t.endTime)}</span>
                  <span>{fmtDuration(t.startTime, t.endTime)}</span>
                  <span>{fmtDistance(t.totalDistanceMeters)}</span>
                  {t.hasGps ? (
                    <span className="badge badge-accent" style={{ fontSize: 10 }}>GPS</span>
                  ) : (
                    <span className="badge" style={{ fontSize: 10 }}>No GPS</span>
                  )}
                </div>
              </div>
              <div className="trip-card-actions">
                <button onClick={() => navigate(`/trips/${t.id}`)}>Open</button>
                {state === 'confirming' ? (
                  <>
                    <span style={{ fontSize: 12, color: 'var(--danger)' }}>Delete?</span>
                    <button onClick={() => onDeleteClick(t)} className="btn-danger btn-sm">Yes</button>
                    <button onClick={() => onCancelConfirm(t)} className="btn-sm">No</button>
                  </>
                ) : (
                  <button onClick={() => onDeleteClick(t)} disabled={state === 'deleting'} className="btn-ghost btn-sm">
                    {state === 'deleting' ? 'Deleting…' : 'Delete'}
                  </button>
                )}
              </div>
              {errMsg && (
                <div style={{ fontSize: 11, color: 'var(--danger)', marginTop: 4 }}>{errMsg}</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
