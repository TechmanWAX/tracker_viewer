import { type ChangeEvent, useState, useRef, useCallback, type DragEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTripUpload } from '../hooks/useTripUpload';
import AppHeader from '../components/AppHeader';

function formatPct(n: number | null): string {
  if (n === null || !Number.isFinite(n)) return '0%';
  return `${Math.round(n * 100)}%`;
}

function ProgressBar({ value, label }: { value: number | null; label: string }) {
  const pct = value === null ? 0 : Math.max(0, Math.min(1, value));
  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--fg-secondary)', marginBottom: 4 }}>
        <span>{label}</span>
        <span>{formatPct(value)}</span>
      </div>
      <div style={{ height: 6, width: '100%', background: 'var(--bg-tertiary)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct * 100}%`, background: 'var(--accent)', borderRadius: 3, transition: 'width 300ms ease' }} />
      </div>
    </div>
  );
}

export default function TripUploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const { upload, job, isBusy, uploadProgress, parseProgress, error, reset } = useTripUpload();
  const navigate = useNavigate();
  const dropRef = useRef<HTMLDivElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const onDrag = useCallback((e: DragEvent, over: boolean) => {
    e.preventDefault();
    setDragOver(over);
  }, []);

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) { setFile(f); if (job) reset(); }
  }

  const showUploadBar = isBusy && (uploadProgress ?? 0) < 1;
  const showParseBar = isBusy && (job?.status === 'pending' || job?.status === 'processing');

  return (
    <div className="page-shell">
      <AppHeader />
      <div className="page-main fade-in" style={{ maxWidth: 560 }}>
        <h1 style={{ marginBottom: 8 }}>Upload trip CSV</h1>
        <p style={{ color: 'var(--fg-secondary)', fontSize: 14, marginBottom: 20 }}>
          Upload a CSV file with timestamp, latitude, longitude, and optional telemetry columns.
        </p>

        <div
          ref={dropRef}
          className="upload-zone"
          style={{ borderColor: dragOver ? 'var(--accent)' : undefined, background: dragOver ? 'var(--accent-soft)' : undefined }}
          onDragEnter={(e) => onDrag(e, true)}
          onDragOver={(e) => onDrag(e, true)}
          onDragLeave={(e) => onDrag(e, false)}
          onDrop={onDrop}
          onClick={() => { if (!isBusy) document.querySelector<HTMLInputElement>('input[type="file"]')?.click(); }}
        >
          <div className="upload-zone-icon">{dragOver ? '📥' : '📁'}</div>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>
            {file ? file.name : dragOver ? 'Drop to upload' : 'Drag CSV here or click to browse'}
          </div>
          <div style={{ fontSize: 13, color: 'var(--fg-muted)' }}>
            {file ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : 'Supports .csv files up to 100 MB'}
          </div>
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(e: ChangeEvent<HTMLInputElement>) => {
              setFile(e.target.files?.[0] ?? null);
              if (job) reset();
            }}
            disabled={isBusy}
            style={{ display: 'none' }}
          />
        </div>

        <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
          <button onClick={() => file && upload(file)} disabled={!file || isBusy} className="btn-primary">
            {isBusy ? 'Uploading…' : 'Upload'}
          </button>
          {file && !isBusy && (
            <button onClick={() => { setFile(null); reset(); }} className="btn-ghost btn-sm">
              Clear
            </button>
          )}
        </div>

        {(showUploadBar || showParseBar) && (
          <div className="card" style={{ marginTop: 12 }}>
            {showUploadBar && <ProgressBar value={uploadProgress} label="Uploading" />}
            {showParseBar && parseProgress !== null && (
              <ProgressBar value={parseProgress} label={job?.status === 'pending' ? 'Queued' : 'Parsing CSV'} />
            )}
          </div>
        )}

        {job && (
          <div className="card" style={{ marginTop: 12, borderColor: job.status === 'failed' ? 'var(--danger)' : undefined }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontWeight: 600, textTransform: 'capitalize' }}>{job.status}</span>
              <span className={`status-pill status-pill-${job.status}`}>{job.status}</span>
            </div>
            {job.status === 'done' && job.result && (
              <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: 14 }}>
                  {job.result.validRows.toLocaleString()} / {job.result.totalRows.toLocaleString()} rows ingested
                  {job.result.errorRows > 0 && (
                    <span style={{ color: 'var(--danger)' }}> ({job.result.errorRows} rejected)</span>
                  )}
                </div>
                {job.result.tripId && (
                  <button onClick={() => navigate(`/trips/${job.result!.tripId}`)} className="btn-primary" style={{ marginTop: 10 }}>
                    Open trip
                  </button>
                )}
              </div>
            )}
            {job.status === 'failed' && (
              <div style={{ marginTop: 8, color: 'var(--danger)' }}>
                {job.result?.error || 'Upload failed.'}
                <button onClick={() => { reset(); setFile(null); }} style={{ marginTop: 8 }}>Try again</button>
              </div>
            )}
          </div>
        )}

        {error && (
          <div style={{ color: 'var(--danger)', marginTop: 8 }}>
            {error} <button onClick={reset} className="btn-sm">Dismiss</button>
          </div>
        )}
      </div>
    </div>
  );
}
