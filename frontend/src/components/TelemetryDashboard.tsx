import { useMemo } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Brush,
} from 'recharts';
import { useTelemetryStore } from '../store/telemetryStore';
import type { TelemetryPoint } from '../types/telemetry';

// All numeric telemetry columns that we render in the charts / cards.
// The keys are the camelCased names from `TelemetryPoint`; the
// `toChartData` mapper applies the same keys. Keeping this in one
// place avoids the cards and the chart array drifting apart.
type NumericKey =
  | 'speed'
  | 'gpsSpeed'
  | 'voltage'
  | 'current'
  | 'phaseCurrent'
  | 'power'
  | 'torque'
  | 'pwm'
  | 'batteryLevel'
  | 'systemTemp'
  | 'temp2';

interface ChartDatum {
  xIndex: number;
  ms: number;
  isGap?: boolean;
  speed: number;
  gpsSpeed: number;
  voltage: number;
  current: number;
  phaseCurrent: number;
  power: number;
  torque: number;
  pwm: number;
  batteryLevel: number;
  systemTemp: number;
  temp2: number;
  // Non-numeric, kept out of the chart data — they're displayed
  // as text indicators below the metric grid.
  distance: number | null;
  totalDistance: number | null;
  tilt: number | null;
  roll: number | null;
  gpsAlt: number | null;
  gpsHeading: number | null;
  gpsDistance: number | null;
  mode: string | null;
  alert: string | null;
}

// One source of truth for the metric cards. The dashboard renders
// this entire array in a 3-column grid; nothing else should hand-
// roll a card. To add a new numeric metric to the dashboard:
//   1. Add the field to the `TelemetryPoint` type.
//   2. Add a `toChartData` mapping (numeric fields are coerced to
//      0, non-numeric pass through as-is).
//   3. Add a row to this array.
const METRIC_CARDS: { key: NumericKey; label: string; suffix: string; digits?: number }[] = [
  { key: 'speed', label: 'Speed', suffix: 'km/h', digits: 1 },
  { key: 'gpsSpeed', label: 'GPS Speed', suffix: 'km/h', digits: 1 },
  { key: 'voltage', label: 'Voltage', suffix: 'V', digits: 2 },
  { key: 'current', label: 'Current', suffix: 'A', digits: 2 },
  { key: 'phaseCurrent', label: 'Phase Current', suffix: 'A', digits: 2 },
  { key: 'power', label: 'Power', suffix: 'W', digits: 1 },
  { key: 'torque', label: 'Torque', suffix: 'Nm', digits: 2 },
  { key: 'pwm', label: 'PWM', suffix: '%', digits: 1 },
  { key: 'batteryLevel', label: 'Battery', suffix: '%', digits: 1 },
  { key: 'systemTemp', label: 'Controller Temp', suffix: '°C', digits: 1 },
  { key: 'temp2', label: 'Motor/Battery Temp', suffix: '°C', digits: 1 },
];

function medianInterval(points: TelemetryPoint[]): number {
  const intervals: number[] = [];
  for (let i = 1; i < points.length; i++) {
    const dt = new Date(points[i].ts).getTime() - new Date(points[i - 1].ts).getTime();
    if (Number.isFinite(dt) && dt > 0) intervals.push(dt);
  }
  if (intervals.length === 0) return 1000;
  intervals.sort((a, b) => a - b);
  return intervals[Math.floor(intervals.length / 2)];
}

function makeDatum(p: TelemetryPoint, ms: number, xi: number): ChartDatum {
  return {
    xIndex: xi,
    ms,
    speed: p.speed ?? 0,
    gpsSpeed: p.gpsSpeed ?? 0,
    voltage: p.voltage ?? 0,
    current: p.current ?? 0,
    phaseCurrent: p.phaseCurrent ?? 0,
    power: p.power ?? 0,
    torque: p.torque ?? 0,
    pwm: p.pwm ?? 0,
    batteryLevel: p.batteryLevel ?? 0,
    systemTemp: p.systemTemp ?? 0,
    temp2: p.temp2 ?? 0,
    distance: p.distance ?? null,
    totalDistance: p.totalDistance ?? null,
    tilt: p.tilt ?? null,
    roll: p.roll ?? null,
    gpsAlt: p.gpsAlt ?? null,
    gpsHeading: p.gpsHeading ?? null,
    gpsDistance: p.gpsDistance ?? null,
    mode: p.mode ?? null,
    alert: p.alert ?? null,
  };
}

function makeGapEntry(ms: number, xi: number): ChartDatum {
  return {
    xIndex: xi,
    ms,
    isGap: true,
    speed: NaN, gpsSpeed: NaN, voltage: NaN, current: NaN, phaseCurrent: NaN,
    power: NaN, torque: NaN, pwm: NaN, batteryLevel: NaN, systemTemp: NaN,
    temp2: NaN,
    distance: null, totalDistance: null, tilt: null, roll: null,
    gpsAlt: null, gpsHeading: null, gpsDistance: null, mode: null, alert: null,
  };
}

const GAP_MULTIPLIER = 5;

/**
 * Build ChartDatum[] with sequential xIndex (no time-based gaps on
 * the x-axis).  When the firmware stops logging for a while, we
 * insert a sentinel NaN entry flagged `isGap` so the chart line
 * breaks cleanly and the component can render a gap marker.
 */
function toChartData(points: TelemetryPoint[]): ChartDatum[] {
  if (points.length === 0) return [];
  const out: ChartDatum[] = [];
  let xi = 0;
  out.push(makeDatum(points[0], new Date(points[0].ts).getTime(), xi++));
  if (points.length < 3) {
    for (let i = 1; i < points.length; i++) {
      out.push(makeDatum(points[i], new Date(points[i].ts).getTime(), xi++));
    }
    return out;
  }
  const med = medianInterval(points);
  const gapThreshold = med * GAP_MULTIPLIER;
  for (let i = 1; i < points.length; i++) {
    const ms = new Date(points[i].ts).getTime();
    const prevMs = new Date(points[i - 1].ts).getTime();
    const dt = ms - prevMs;
    if (Number.isFinite(dt) && dt > gapThreshold) {
      out.push(makeGapEntry(prevMs + 1, xi++));
    }
    out.push(makeDatum(points[i], ms, xi++));
  }
  return out;
}

/**
 * Downsample a ChartDatum array for recharts rendering only.
 *
 * A 40k+ point trip fetches into the store, but recharts struggles
 * with >10k elements in a single <Line> — the SVG→canvas conversion
 * takes seconds and the tooltip/scroll becomes laggy. This function
 * keeps the first and last point intact and evenly samples the
 * remainder, preserving the x-axis (ms) domain so the playback
 * cursor's ReferenceLine still lands on the right time.
 *
 * The full-resolution `chartData` array still powers the metric
 * cards (`point = chartData[currentIndex]`) and the playback
 * engine; only the <TelemetryChart> line rendering uses the
 * downsampled version.
 */
const CHART_DECI_CAP = 10000;

function decimateChart(data: ChartDatum[]): ChartDatum[] {
  if (data.length <= CHART_DECI_CAP) return data;
  const step = (data.length - 1) / (CHART_DECI_CAP - 1);
  const out = new Array<ChartDatum>(CHART_DECI_CAP);
  for (let i = 0; i < CHART_DECI_CAP; i++) {
    out[i] = data[Math.round(i * step)];
  }
  return out;
}

// Aggressively small helper used in two places so the rendering of
// `0` vs "—" stays consistent.
function formatVal(v: number | null, digits: number = 2): string {
  return typeof v === 'number' ? v.toFixed(digits) : '—';
}

function TelemetryChart({
  data,
  dataKey,
  label,
  color,
  cursorX,
  hoverX,
  height = 140,
  setHoverMs,
}: {
  data: ChartDatum[];
  dataKey: keyof ChartDatum;
  label: string;
  color: string;
  cursorX: number | null;
  hoverX: number | null;
  height?: number;
  setHoverMs: (ms: number | null) => void;
}) {
  // All hooks must come before any early return (React Rules of
  // Hooks). The chart component always calls useMemo for gap
  // markers, even when data is empty — the early return below
  // just skips rendering the chart JSX.
  const gapLines = useMemo(() => {
    if (data.length === 0) return [];
    const seen = new Set<number>();
    const out: { x: number }[] = [];
    for (const d of data) {
      if (d.isGap && !seen.has(d.xIndex)) {
        seen.add(d.xIndex);
        out.push({ x: d.xIndex });
      }
    }
    return out;
  }, [data]);

  if (data.length === 0) {
    return (
      <div style={{ background: 'var(--bg-2)', padding: 12, borderRadius: 8, height }}>
        <div style={{ fontSize: 12, opacity: 0.7, marginBottom: 8 }}>{label}</div>
        <div style={{ fontSize: 12, opacity: 0.4 }}>No data</div>
      </div>
    );
  }

  const displayMs = hoverX != null
    ? data.find((d) => d.xIndex === hoverX)?.ms ?? null
    : null;

  return (
    <div style={{ background: 'var(--bg-2)', padding: 12, borderRadius: 8, height }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
        <span style={{ opacity: 0.85 }}>{label}</span>
        <span style={{ opacity: 0.5, fontFamily: 'monospace' }}>
          {displayMs != null ? new Date(displayMs).toISOString().slice(11, 19) : '—'}
        </span>
      </div>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart
          data={data}
          margin={{ top: 6, right: 12, bottom: 20, left: 0 }}
          onMouseMove={(e) => {
            if (e?.activePayload?.[0]?.payload?.ms != null) {
              setHoverMs(e.activePayload[0].payload.ms);
            }
          }}
          onMouseLeave={() => setHoverMs(null)}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#2a2f3a" />
          <XAxis dataKey="xIndex" hide type="number" domain={['dataMin', 'dataMax']} />
          <YAxis
            stroke="#64748b"
            fontSize={10}
            width={36}
            tickFormatter={(v: number) => v.toFixed(1)}
          />
          <Tooltip
            contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155', color: '#f1f5f9', fontSize: 12 }}
            labelFormatter={(xi) => {
              const d = data[Number(xi) - (data[0]?.xIndex ?? 0)];
              return d ? new Date(d.ms).toISOString().slice(11, 19) : String(xi);
            }}
            itemStyle={{ color }}
          />
          <Line
            type="monotone"
            dataKey={dataKey}
            stroke={color}
            dot={false}
            strokeWidth={2}
            isAnimationActive={false}
            connectNulls={false}
          />
          {cursorX != null && (
            <ReferenceLine
              x={cursorX}
              stroke="#ef4444"
              strokeWidth={2}
              label={{ value: 'NOW', position: 'top', fill: '#ef4444', fontSize: 10 }}
            />
          )}
          {hoverX != null && (
            <ReferenceLine
              x={hoverX}
              stroke="#fbbf24"
              strokeWidth={1.5}
              strokeDasharray="4 2"
              label={{ value: '✦', position: 'top', fill: '#fbbf24', fontSize: 10 }}
            />
          )}
          {gapLines.length > 0 && gapLines.map((g) => (
            <ReferenceLine
              key={g.x}
              x={g.x}
              stroke="#64748b"
              strokeWidth={1}
              strokeDasharray="2 2"
              label={{ value: '∥', position: 'top', fill: '#64748b', fontSize: 9 }}
            />
          ))}
          <Brush dataKey="xIndex" height={20} stroke="#4f9eff" fill="var(--bg-2)" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

const SPEED_COLOR = '#60a5fa';
const POWER_COLOR = '#fbbf24';
const BATTERY_COLOR = '#a855f7';
const VOLTAGE_COLOR = '#34d399';
const CURRENT_COLOR = '#f472b6';

function fmtDistance(meters: number | null): string {
  if (meters == null) return '—';
  if (meters < 1000) return `${Math.round(meters)} m`;
  return `${(meters / 1000).toFixed(2)} km`;
}

function fmtDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return '—';
  const totalSec = Math.floor(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

export default function TelemetryDashboard() {
  const points = useTelemetryStore((s) => s.points);
  const currentIndex = useTelemetryStore((s) => s.currentIndex);
  const hoverMs = useTelemetryStore((s) => s.hoverMs);
  const setHoverMs = useTelemetryStore((s) => s.setHoverMs);

  const chartData = useMemo(() => toChartData(points), [points]);
  // Decimated copy used ONLY for the <TelemetryChart> line rendering.
  // The metric cards and playback engine still read from `chartData`
  // (full resolution) via `point = chartData[currentIndex]`.
  const chartDataDecimated = useMemo(() => decimateChart(chartData), [chartData]);
  const point = chartData[currentIndex];

  // Find the closest chart entry to the hover timestamp.
  const hoverPoint = useMemo(() => {
    if (hoverMs == null || chartDataDecimated.length === 0) return null;
    let lo = 0;
    let hi = chartDataDecimated.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (chartDataDecimated[mid].ms < hoverMs) lo = mid + 1;
      else hi = mid;
    }
    return chartDataDecimated[lo];
  }, [hoverMs, chartDataDecimated]);
  const displayPoint = hoverPoint ?? point;

  // ---- trip-level aggregates (whole trip, not just cursor) --------
  // We compute the summary stats over the full set so they don't
  // flicker as the user scrubs. All metrics are null-safe: a
  // trip where the firmware never reported `phaseCurrent` will
  // show "—" everywhere for that stat.
  const summary = useMemo(() => {
    if (points.length === 0) return null;
    let maxSpeed = 0;
    let maxGpsSpeed = 0;
    let maxPower = -Infinity;
    let minPower = Infinity;
    let maxCurrent = 0;
    let maxPhaseCurrent = 0;
    let minBattery = Infinity;
    let maxBattery = -Infinity;
    let maxTemp = -Infinity;
    let maxTemp2 = -Infinity;
    let maxTilt = 0;
    let maxRoll = 0;
    let maxAlt = -Infinity;
    let totalOdo: number | null = null;
    let movingRows = 0;
    for (const p of points) {
      if (p.speed != null && p.speed > maxSpeed) maxSpeed = p.speed;
      if (p.gpsSpeed != null && p.gpsSpeed > maxGpsSpeed) maxGpsSpeed = p.gpsSpeed;
      if (p.power != null) {
        if (p.power > maxPower) maxPower = p.power;
        if (p.power < minPower) minPower = p.power;
      }
      if (p.current != null && Math.abs(p.current) > Math.abs(maxCurrent)) maxCurrent = p.current;
      if (p.phaseCurrent != null && Math.abs(p.phaseCurrent) > Math.abs(maxPhaseCurrent)) maxPhaseCurrent = p.phaseCurrent;
      if (p.batteryLevel != null) {
        if (p.batteryLevel < minBattery) minBattery = p.batteryLevel;
        if (p.batteryLevel > maxBattery) maxBattery = p.batteryLevel;
      }
      if (p.systemTemp != null && p.systemTemp > maxTemp) maxTemp = p.systemTemp;
      if (p.temp2 != null && p.temp2 > maxTemp2) maxTemp2 = p.temp2;
      if (p.tilt != null && Math.abs(p.tilt) > maxTilt) maxTilt = Math.abs(p.tilt);
      if (p.roll != null && Math.abs(p.roll) > maxRoll) maxRoll = Math.abs(p.roll);
      if (p.gpsAlt != null && p.gpsAlt > maxAlt) maxAlt = p.gpsAlt;
      if (p.totalDistance != null) {
        totalOdo = p.totalDistance;
      }
      if ((p.speed ?? 0) > 0.5) movingRows++;
    }
    // For trip distance: MAX - MIN of the running odometer (same
    // formula the worker uses to fill `trips.total_distance_meters`).
    let tripDistanceMeters: number | null = null;
    let minD = Infinity;
    let maxD = -Infinity;
    for (const p of points) {
      if (p.distance != null) {
        if (p.distance < minD) minD = p.distance;
        if (p.distance > maxD) maxD = p.distance;
      }
    }
    if (Number.isFinite(minD) && Number.isFinite(maxD)) {
      tripDistanceMeters = maxD - minD;
    }
    const first = points[0];
    const last = points[points.length - 1];
    const startMs = new Date(first.ts).getTime();
    const endMs = new Date(last.ts).getTime();
    const durationMs = Number.isFinite(startMs) && Number.isFinite(endMs)
      ? Math.max(0, endMs - startMs)
      : 0;
    const avgSpeed = movingRows > 0
      ? points.reduce((s, p) => s + (p.speed ?? 0), 0) / points.length
      : 0;
    return {
      pointCount: points.length,
      durationMs,
      tripDistanceMeters,
      totalOdo,
      maxSpeed,
      maxGpsSpeed,
      maxPower: Number.isFinite(maxPower) ? maxPower : null,
      minPower: Number.isFinite(minPower) ? minPower : null,
      maxCurrent,
      maxPhaseCurrent,
      minBattery: Number.isFinite(minBattery) ? minBattery : null,
      maxBattery: Number.isFinite(maxBattery) ? maxBattery : null,
      maxTemp: Number.isFinite(maxTemp) ? maxTemp : null,
      maxTemp2: Number.isFinite(maxTemp2) ? maxTemp2 : null,
      maxTilt,
      maxRoll,
      maxAlt: Number.isFinite(maxAlt) ? maxAlt : null,
      avgSpeed,
    };
  }, [points]);

  if (points.length === 0) {
    return <div style={{ padding: 16, opacity: 0.6 }}>Loading telemetry…</div>;
  }

  const cursorMs = point?.ms ?? chartData[0]?.ms ?? 0;

  // Map cursor / hover timestamps to sequential xIndex for the
  // decimated chart (the charts use xIndex as the X axis).
  const cursorX = useMemo(() => {
    if (chartDataDecimated.length === 0) return null;
    let best = chartDataDecimated[0].xIndex;
    let bestDist = Infinity;
    for (const d of chartDataDecimated) {
      const dist = Math.abs(d.ms - cursorMs);
      if (dist < bestDist) { bestDist = dist; best = d.xIndex; }
    }
    return best;
  }, [cursorMs, chartDataDecimated]);

  const hoverX = hoverPoint?.xIndex ?? null;

  return (
    <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 12, height: '100%' }}>
      {/* ---- Trip summary ---------------------------------------- */}
      {/* The user asked for "общий пробег поездки" (total trip
          mileage); we surface it here along with the other
          whole-trip aggregates that make sense next to it. The
          per-sample values stay in the cards below the summary
          and follow the playback cursor. */}
      {summary && (
        <div
          className="telemetry-summary"
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: 8,
            background: 'var(--bg-2)',
            padding: 10,
            borderRadius: 8,
          }}
          aria-label="Trip summary"
        >
          <SummaryStat label="Distance" value={fmtDistance(summary.tripDistanceMeters)} accent />
          <SummaryStat label="Duration" value={fmtDuration(summary.durationMs)} />
          <SummaryStat label="Avg Speed" value={summary.avgSpeed > 0 ? `${summary.avgSpeed.toFixed(1)} km/h` : '—'} />
          <SummaryStat label="Max Speed" value={summary.maxSpeed > 0 ? `${summary.maxSpeed.toFixed(1)} km/h` : '—'} />
          <SummaryStat
            label="Peak Power"
            value={summary.maxPower != null ? `${summary.maxPower.toFixed(0)} W` : '—'}
          />
          <SummaryStat
            label="Min Battery"
            value={summary.minBattery != null ? `${summary.minBattery.toFixed(1)}%` : '—'}
          />
          <SummaryStat
            label="Peak Current"
            value={summary.maxCurrent != null ? `${summary.maxCurrent.toFixed(1)} A` : '—'}
          />
          <SummaryStat
            label="Peak Temp"
            value={summary.maxTemp != null ? `${summary.maxTemp.toFixed(0)}°C` : '—'}
          />
          {summary.totalOdo != null && (
            <SummaryStat
              label="Lifetime Odo"
              value={fmtDistance(summary.totalOdo)}
              hint="device total"
            />
          )}
          {summary.maxAlt != null && (
            <SummaryStat
              label="Max Alt"
              value={`${summary.maxAlt.toFixed(0)} m`}
            />
          )}
          {summary.maxTilt > 0 && (
            <SummaryStat
              label="Max Tilt"
              value={`±${summary.maxTilt.toFixed(1)}°`}
            />
          )}
          {summary.maxRoll > 0 && (
            <SummaryStat
              label="Max Roll"
              value={`±${summary.maxRoll.toFixed(1)}°`}
            />
          )}
        </div>
      )}

      {/* ---- Per-cursor metric cards ----------------------------- */}
      <div className="telemetry-cards" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
        {METRIC_CARDS.map((c) => {
          const v = displayPoint?.[c.key] as number | undefined;
          // Per-row: show "—" when null (missing reading for
          // this sample), the actual value otherwise. Negative
          // values render with a leading minus; regen reads will
          // show as e.g. "-31.8 A" which is exactly what we want.
          return (
            <div
              key={c.key}
              style={{ background: 'var(--bg-2)', padding: 8, borderRadius: 6 }}
            >
              <div style={{ fontSize: 10, opacity: 0.6, textTransform: 'uppercase' }}>{c.label}</div>
              <div style={{ fontSize: 18, fontWeight: 600 }} aria-live="polite">
                {formatVal(typeof v === 'number' ? v : null, c.digits ?? 2)}{' '}
                <span style={{ fontSize: 10, opacity: 0.6 }}>{c.suffix}</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* ---- Non-numeric status -------------------------------- */}
      {(point?.mode != null || point?.alert != null) && (
        <div style={{ display: 'flex', gap: 8, fontSize: 12 }}>
          {point?.mode != null && (
            <span
              style={{
                background: 'var(--bg-2)',
                padding: '4px 8px',
                borderRadius: 4,
                fontFamily: 'monospace',
              }}
            >
              mode: {point.mode}
            </span>
          )}
          {point?.alert != null && (
            <span
              style={{
                background: 'var(--bg-2)',
                padding: '4px 8px',
                borderRadius: 4,
                fontFamily: 'monospace',
                color: 'var(--danger, #ef4444)',
              }}
            >
              alert: {point.alert}
            </span>
          )}
        </div>
      )}

      {/* ---- Charts --------------------------------------------- */}
      <div className="telemetry-charts" style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8, minHeight: 0 }}>
        <TelemetryChart
          data={chartDataDecimated}
          dataKey="speed"
          label="Velocity (km/h)"
          color={SPEED_COLOR}
          cursorX={cursorX}
          hoverX={hoverX}
          setHoverMs={setHoverMs}
        />
        <TelemetryChart
          data={chartDataDecimated}
          dataKey="power"
          label="Power (W)"
          color={POWER_COLOR}
          cursorX={cursorX}
          hoverX={hoverX}
          setHoverMs={setHoverMs}
        />
        <TelemetryChart
          data={chartDataDecimated}
          dataKey="batteryLevel"
          label="Battery (%)"
          color={BATTERY_COLOR}
          cursorX={cursorX}
          hoverX={hoverX}
          setHoverMs={setHoverMs}
        />
        <TelemetryChart
          data={chartDataDecimated}
          dataKey="voltage"
          label="Voltage (V)"
          color={VOLTAGE_COLOR}
          cursorX={cursorX}
          hoverX={hoverX}
          setHoverMs={setHoverMs}
        />
        <TelemetryChart
          data={chartDataDecimated}
          dataKey="current"
          label="Current (A) — +draw / −regen"
          color={CURRENT_COLOR}
          cursorX={cursorX}
          hoverX={hoverX}
          setHoverMs={setHoverMs}
        />
      </div>
    </div>
  );
}

function SummaryStat({
  label,
  value,
  hint,
  accent,
}: {
  label: string;
  value: string;
  hint?: string;
  accent?: boolean;
}) {
  return (
    <div>
      <div style={{ fontSize: 10, opacity: 0.6, textTransform: 'uppercase' }}>{label}</div>
      <div
        style={{
          fontSize: 18,
          fontWeight: 600,
          color: accent ? 'var(--accent, #4f9eff)' : undefined,
        }}
      >
        {value}
      </div>
      {hint && <div style={{ fontSize: 9, opacity: 0.5 }}>{hint}</div>}
    </div>
  );
}
