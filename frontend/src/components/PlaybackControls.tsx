import { useMemo } from 'react';
import { useTelemetryStore } from '../store/telemetryStore';
import { usePlayback } from '../hooks/usePlayback';

const SPEEDS = [1, 2, 4, 8] as const;

function fmtClock(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return '00:00';
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export default function PlaybackControls() {
  const points = useTelemetryStore((s) => s.points);
  const currentIndex = useTelemetryStore((s) => s.currentIndex);
  const isPlaying = useTelemetryStore((s) => s.isPlaying);
  const speed = useTelemetryStore((s) => s.speed);
  const { play, pause, setSpeed, seekToIndex } = usePlayback();

  const maxIndex = Math.max(0, points.length - 1);

  const { elapsedMs, totalMs } = useMemo(() => {
    if (points.length === 0) return { elapsedMs: 0, totalMs: 0 };
    const firstMs = new Date(points[0].ts).getTime();
    const lastMs = new Date(points[maxIndex].ts).getTime();
    const total = Math.max(0, lastMs - firstMs);
    if (currentIndex <= 0) return { elapsedMs: 0, totalMs: total };
    if (currentIndex >= maxIndex) return { elapsedMs: total, totalMs: total };
    const curMs = new Date(points[currentIndex].ts).getTime();
    return { elapsedMs: Math.max(0, curMs - firstMs), totalMs: total };
  }, [points, currentIndex, maxIndex]);

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
      <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
        <button
          onClick={isPlaying ? pause : play}
          disabled={points.length === 0}
          aria-label={isPlaying ? 'Pause' : 'Play'}
          className="btn-primary btn-sm"
        >
          {isPlaying ? '⏸' : '▶'}
        </button>
        <button
          onClick={() => { pause(); seekToIndex(0); }}
          disabled={points.length === 0}
          aria-label="Reset"
          className="btn-sm"
        >
          ⏮
        </button>
      </div>

      <div className="playback-speed-group">
        {SPEEDS.map((s) => (
          <button
            key={s}
            onClick={() => setSpeed(s)}
            aria-pressed={speed === s}
            className="playback-speed-btn"
          >
            {s}×
          </button>
        ))}
      </div>

      <input
        type="range"
        className="playback-scrubber"
        min={0}
        max={maxIndex}
        value={currentIndex}
        onChange={(e) => { pause(); seekToIndex(Number(e.target.value)); }}
        aria-label="Playback position"
        disabled={points.length === 0}
      />

      <span className="playback-time">
        {fmtClock(elapsedMs)} / {fmtClock(totalMs)}
      </span>
    </div>
  );
}
