import { type ChangeEvent, useState } from 'react';
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
    <div style={{ marginTop: 6 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontSize: 12,
          opacity: 0.8,
          marginBottom: 2,
        }}
      >
        <span>{label}</span>
        <span>{formatPct(value)}</span>
      </div>
      <div
        style={{
          height: 6,
          width: '100%',
          background: 'var(--bg-3, #222)',
          borderRadius: 3,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            height: '100%',
            width: `${pct * 100}%`,
            background: 'var(--accent, #4a9eff)',
            transition: 'width 200ms ease',
          }}
        />
      </div>
    </div>
  );
}

export default function TripUploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const {
    upload,
    job,
    isBusy,
    uploadProgress,
    parseProgress,
    error,
    reset,
  } = useTripUpload();
  const navigate = useNavigate();

  function onChange(e: ChangeEvent<HTMLInputElement>) {
    setFile(e.target.files?.[0] ?? null);
    if (job) reset();
  }

  async function onSubmit() {
    if (!file) return;
    await upload(file);
  }

  // Decide which progress bar to show. We only show one at a time
  // so the UI doesn't double up during the brief window where the
  // HTTP upload is at 100% but the server hasn't started reporting
  // parse progress yet.
  const showUploadBar = isBusy && (uploadProgress ?? 0) < 1;
  const showParseBar =
    isBusy &&
    (job?.status === 'pending' || job?.status === 'processing');

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <AppHeader />
      <div style={{ padding: 24, maxWidth: 560, flex: 1 }}>
        <h1>Upload trip CSV</h1>
        <p style={{ opacity: 0.7, fontSize: 13 }}>
          CSV with timestamp + latitude + longitude columns. Other telemetry (speed, voltage, current, power,
          battery_level) is optional.
        </p>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '12px 0' }}>
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={onChange}
            disabled={isBusy}
          />
          <button onClick={onSubmit} disabled={!file || isBusy}>
            {isBusy ? 'Uploading…' : 'Upload'}
          </button>
        </div>

        {/* Progress bars — visible only while busy. */}
        {(showUploadBar || showParseBar) && (
          <div
            style={{
              marginTop: 8,
              padding: 10,
              background: 'var(--bg-2, #181818)',
              borderRadius: 6,
              border: '1px solid #333',
            }}
          >
            {showUploadBar && (
              <ProgressBar value={uploadProgress} label="Uploading" />
            )}
            {showParseBar && parseProgress !== null && (
              <ProgressBar
                value={parseProgress}
                label={
                  job?.status === 'pending'
                    ? 'Queued for parsing'
                    : 'Parsing CSV'
                }
              />
            )}
            {showParseBar && parseProgress === null && (
              <div style={{ fontSize: 12, opacity: 0.7, marginTop: 4 }}>
                Waiting for the parser to start…
              </div>
            )}
          </div>
        )}

        {job && (
          <div
            style={{
              marginTop: 16,
              padding: 12,
              background: 'var(--bg-2)',
              borderRadius: 6,
              border: `1px solid ${job.status === 'failed' ? 'var(--danger)' : '#333'}`,
            }}
          >
            <div>
              Status: <strong>{job.status}</strong>{' '}
              <span style={{ opacity: 0.6, fontSize: 12 }}>({job.filename})</span>
            </div>
            {job.status === 'pending' && (
              <div style={{ fontSize: 12, opacity: 0.7, marginTop: 4 }}>
                Job queued. The server will start processing shortly.
              </div>
            )}
            {job.status === 'processing' && (
              <div style={{ fontSize: 12, opacity: 0.7, marginTop: 4 }}>
                Parsing CSV and ingesting telemetry points…
                {parseProgress !== null && ` ${formatPct(parseProgress)}`}
              </div>
            )}
            {job.status === 'done' && job.result && (
              <div style={{ marginTop: 8, fontSize: 13 }}>
                <div>
                  {job.result.validRows} / {job.result.totalRows} rows ingested
                  {job.result.errorRows > 0 && (
                    <span style={{ color: 'var(--danger)' }}>
                      {' '}({job.result.errorRows} rejected)
                    </span>
                  )}
                </div>
                {job.result.tripId && (
                  <button
                    onClick={() => navigate(`/trips/${job.result!.tripId}`)}
                    style={{ marginTop: 8 }}
                  >
                    Open trip
                  </button>
                )}
                {job.result.parsingReport && (
                  <details style={{ marginTop: 8, fontSize: 12, opacity: 0.8 }}>
                    <summary>Parsing report</summary>
                    <pre style={{ whiteSpace: 'pre-wrap', marginTop: 6 }}>
                      {job.result.parsingReport}
                    </pre>
                  </details>
                )}
              </div>
            )}
            {job.status === 'failed' && (
              <div style={{ marginTop: 8, color: 'var(--danger)' }}>
                <div>{job.result?.error || 'Upload failed.'}</div>
                <button
                  onClick={() => {
                    reset();
                    setFile(null);
                  }}
                  style={{ marginTop: 8 }}
                >
                  Try again
                </button>
              </div>
            )}
          </div>
        )}
        {error && (
          <div style={{ color: 'var(--danger)', marginTop: 8 }}>
            {error}
            <button
              onClick={reset}
              style={{ marginLeft: 8, fontSize: 12 }}
            >
              Dismiss
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
