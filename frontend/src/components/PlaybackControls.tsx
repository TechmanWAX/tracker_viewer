import { useMemo } from 'react';
import { useTelemetryStore } from '../store/telemetryStore';
import { usePlayback } from '../hooks/usePlayback';

const SPEEDS = [0.5, 1, 2, 5, 10] as const;

function fmtClock(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return '00:00';
  const total = Math.floor(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export default function PlaybackControls() {
  const isPlaying = useTelemetryStore((s) => s.isPlaying);
  const speed = useTelemetryStore((s) => s.speed);
  const setSpeed = useTelemetryStore((s) => s.setSpeed);
  const points = useTelemetryStore((s) => s.points);
  const currentIndex = useTelemetryStore((s) => s.currentIndex);
  const setCurrentIndex = useTelemetryStore((s) => s.setCurrentIndex);
  const setIsPlaying = useTelemetryStore((s) => s.setIsPlaying);
  const { seekToIndex } = usePlayback();

  const maxIndex = Math.max(0, points.length - 1);

  const { elapsedMs, totalMs } = useMemo(() => {
    if (points.length === 0) return { elapsedMs: 0, totalMs: 0 };
    const first = new Date(points[0].ts).getTime();
    const last = new Date(points[points.length - 1].ts).getTime();
    const total = last - first;
    if (currentIndex <= 0) return { elapsedMs: 0, totalMs: total };
    if (currentIndex >= maxIndex) return { elapsedMs: total, totalMs: total };
    const cur = new Date(points[currentIndex].ts).getTime();
    return { elapsedMs: cur - first, totalMs: total };
  }, [points, currentIndex, maxIndex]);

  function onScrub(e: React.ChangeEvent<HTMLInputElement>) {
    const idx = Number(e.target.value);
    setIsPlaying(false);
    seekToIndex(idx);
  }

  return (
    <div
      role="region"
      aria-label="Playback controls"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        padding: 8,
        background: 'var(--bg-2)',
        borderRadius: 8,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <button
          onClick={isPlaying ? () => setIsPlaying(false) : () => setIsPlaying(true)}
          disabled={points.length === 0}
          aria-label={isPlaying ? 'Pause' : 'Play'}
        >
          {isPlaying ? '⏸ Pause' : '▶ Play'}
        </button>
        <button
          onClick={() => {
            setIsPlaying(false);
            setCurrentIndex(0);
          }}
          disabled={points.length === 0}
          aria-label="Reset to start"
          title="Reset"
        >
          ⏮ Reset
        </button>
        <div role="group" aria-label="Playback speed" style={{ display: 'flex', gap: 2 }}>
          {SPEEDS.map((s) => (
            <button
              key={s}
              onClick={() => setSpeed(s)}
              aria-pressed={speed === s}
              style={{
                marginLeft: 0,
                fontWeight: speed === s ? 700 : 400,
                minWidth: 40,
              }}
            >
              {s}×
            </button>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        <div style={{ fontFamily: 'monospace', fontSize: 12, opacity: 0.8 }}>
          {fmtClock(elapsedMs)} / {fmtClock(totalMs)}
        </div>
      </div>
      <input
        type="range"
        min={0}
        max={maxIndex}
        value={Math.min(currentIndex, maxIndex)}
        onChange={onScrub}
        disabled={points.length === 0}
        aria-label="Seek"
        style={{ width: '100%' }}
      />
    </div>
  );
}
