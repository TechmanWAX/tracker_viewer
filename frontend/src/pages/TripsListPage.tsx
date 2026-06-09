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
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <AppHeader />
      <div style={{ padding: 24, flex: 1 }}>
        <h1>Trips</h1>
        {loading && <p style={{ opacity: 0.6 }}>Loading…</p>}
        {error && (
          <div style={{ color: 'var(--danger)', marginBottom: 12 }}>
            {error}{' '}
            <button onClick={refresh} style={{ marginLeft: 8 }}>
              Retry
            </button>
          </div>
        )}
        {!loading && trips.length === 0 && (
          <p>
            No trips yet. <Link to="/trips/upload">Upload your first CSV</Link>.
          </p>
        )}
        {trips.length > 0 && (
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {trips.map((t) => {
              const state = rowState[t.id]?.kind ?? 'idle';
              const errMsg =
                rowState[t.id]?.kind === 'error'
                  ? (rowState[t.id] as { kind: 'error'; message: string }).message
                  : null;
              return (
                <li
                  key={t.id}
                  style={{
                    padding: 12,
                    margin: '8px 0',
                    background: 'var(--bg-2)',
                    borderRadius: 6,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 12,
                    flexWrap: 'wrap',
                  }}
                >
                  <div style={{ flex: 1, minWidth: 200 }}>
                    <Link
                      to={`/trips/${t.id}`}
                      style={{ color: 'var(--accent)', textDecoration: 'none', fontWeight: 600 }}
                    >
                      {t.name}
                    </Link>
                    <div style={{ fontSize: 12, opacity: 0.65, marginTop: 4 }}>
                      {fmtDate(t.startTime)} → {fmtDate(t.endTime)} · {fmtDuration(t.startTime, t.endTime)} · {fmtDistance(t.totalDistanceMeters)}
                    </div>
                  </div>
                  <button
                    onClick={() => navigate(`/trips/${t.id}`)}
                    aria-label={`Open ${t.name}`}
                    disabled={state === 'deleting'}
                  >
                    Open
                  </button>
                  {state === 'confirming' && (
                    <span
                      role="alert"
                      style={{ fontSize: 12, opacity: 0.85, marginRight: 4 }}
                    >
                      Delete "{t.name}" and all its telemetry?
                    </span>
                  )}
                  {state === 'confirming' && (
                    <button
                      onClick={() => onCancelConfirm(t)}
                      aria-label={`Cancel deleting ${t.name}`}
                    >
                      Cancel
                    </button>
                  )}
                  {state === 'confirming' && (
                    <button
                      onClick={() => onDeleteClick(t)}
                      aria-label={`Confirm delete ${t.name}`}
                      style={{ color: 'var(--danger)' }}
                    >
                      Sure, delete
                    </button>
                  )}
                  {state === 'idle' && (
                    <button
                      onClick={() => onDeleteClick(t)}
                      aria-label={`Delete ${t.name}`}
                      style={{ color: 'var(--danger)' }}
                    >
                      Delete
                    </button>
                  )}
                  {state === 'deleting' && (
                    <button
                      disabled
                      aria-busy="true"
                      aria-label={`Deleting ${t.name}`}
                      style={{ color: 'var(--danger)' }}
                    >
                      Deleting…
                    </button>
                  )}
                  {state === 'error' && errMsg && (
                    <div
                      role="alert"
                      data-testid="delete-error"
                      style={{
                        flexBasis: '100%',
                        color: 'var(--danger)',
                        fontSize: 12,
                        display: 'flex',
                        gap: 8,
                        alignItems: 'center',
                      }}
                    >
                      <span>{errMsg}</span>
                      <button
                        onClick={() => onDeleteClick(t)}
                        aria-label={`Retry delete ${t.name}`}
                        style={{ color: 'var(--danger)' }}
                      >
                        Retry
                      </button>
                      <button
                        onClick={() => clearRow(t.id)}
                        aria-label={`Dismiss error for ${t.name}`}
                      >
                        Dismiss
                      </button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
