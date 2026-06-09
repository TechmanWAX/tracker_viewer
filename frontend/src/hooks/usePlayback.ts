import { useEffect, useRef, useCallback } from 'react';
import { useTelemetryStore } from '../store/telemetryStore';
import type { TelemetryPoint } from '../types/telemetry';

const REACT_UPDATE_INTERVAL_MS = 50;

export interface InterpolatedPoint {
  ts: number;
  // Lat/lon are null for trips without GPS data. The marker sink
  // in MapView already guards against this; the playback engine
  // itself doesn't render anything spatial, only telemetry.
  lat: number | null;
  lon: number | null;
  speed: number;
  voltage: number;
  current: number;
  power: number;
  batteryLevel: number;
}

function pointTsMs(p: TelemetryPoint, fallback: TelemetryPoint): number {
  const v = p?.ts ?? fallback?.ts;
  if (!v) return 0;
  const t = new Date(v).getTime();
  return Number.isFinite(t) ? t : 0;
}

const findIndexAtVirtual = (virtualMs: number, pts: TelemetryPoint[]): number => {
  if (pts.length === 0) return 0;
  const first = pointTsMs(pts[0], pts[0]);
  if (virtualMs <= first) return 0;
  const last = pointTsMs(pts[pts.length - 1], pts[pts.length - 1]);
  if (virtualMs >= last) return pts.length - 1;

  let lo = 0;
  let hi = pts.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (pointTsMs(pts[mid], pts[0]) < virtualMs) lo = mid + 1;
    else hi = mid;
  }
  return lo;
};

const interpolateAt = (virtualMs: number, pts: TelemetryPoint[]): InterpolatedPoint | null => {
  if (pts.length === 0) return null;
  if (pts.length === 1) {
    const p = pts[0];
    return {
      ts: pointTsMs(p, p),
      lat: p.lat,
      lon: p.lon,
      speed: p.speed ?? 0,
      voltage: p.voltage ?? 0,
      current: p.current ?? 0,
      power: p.power ?? 0,
      batteryLevel: p.batteryLevel ?? 0,
    };
  }
  const first = pointTsMs(pts[0], pts[0]);
  const last = pointTsMs(pts[pts.length - 1], pts[pts.length - 1]);
  if (virtualMs <= first) {
    const p = pts[0];
    return {
      ts: first,
      lat: p.lat,
      lon: p.lon,
      speed: p.speed ?? 0,
      voltage: p.voltage ?? 0,
      current: p.current ?? 0,
      power: p.power ?? 0,
      batteryLevel: p.batteryLevel ?? 0,
    };
  }
  if (virtualMs >= last) {
    const p = pts[pts.length - 1];
    return {
      ts: last,
      lat: p.lat,
      lon: p.lon,
      speed: p.speed ?? 0,
      voltage: p.voltage ?? 0,
      current: p.current ?? 0,
      power: p.power ?? 0,
      batteryLevel: p.batteryLevel ?? 0,
    };
  }

  const upper = findIndexAtVirtual(virtualMs, pts);
  const p1 = pts[upper - 1];
  const p2 = pts[upper];
  const t1 = pointTsMs(p1, p1);
  const t2 = pointTsMs(p2, p2);
  const fraction = t2 === t1 ? 0 : (virtualMs - t1) / (t2 - t1);
  // Telemetry fields default to 0 when either side is null. That
  // matches the previous behaviour and keeps the playback bar
  // moving smoothly across gaps.
  const lerp = (a: number | null | undefined, b: number | null | undefined) => {
    const av = a ?? 0;
    const bv = b ?? 0;
    return av + (bv - av) * fraction;
  };
  // Lat/lon interpolation is stricter: if either endpoint is null
  // we return null (we have no sensible way to interpolate a
  // position through a missing coordinate). The marker sink in
  // MapView already guards against null, so the playback engine
  // just stops moving the marker.
  const lerpPos = (
    a: number | null | undefined,
    b: number | null | undefined,
  ): number | null => {
    if (a == null && b == null) return null;
    if (a == null) return b ?? null;
    if (b == null) return a ?? null;
    return a + (b - a) * fraction;
  };

  return {
    ts: virtualMs,
    lat: lerpPos(p1.lat, p2.lat),
    lon: lerpPos(p1.lon, p2.lon),
    speed: lerp(p1.speed, p2.speed),
    voltage: lerp(p1.voltage, p2.voltage),
    current: lerp(p1.current, p2.current),
    power: lerp(p1.power, p2.power),
    batteryLevel: lerp(p1.batteryLevel, p2.batteryLevel),
  };
};

const markerSinkHolder: { current: ((p: InterpolatedPoint | null) => void) | null } = { current: null };

/**
 * Side-effect-only hook. Mount it ONCE per trip detail page to start the rAF
 * loop and keep the playback engine alive. It does not return actions — use
 * `usePlayback` for that.
 */
export function usePlaybackEngine() {
  const rafRef = useRef<number | null>(null);
  const lastStoreUpdateRef = useRef<number>(0);
  const speedRef = useRef<number>(1);
  const pointsRef = useRef<TelemetryPoint[]>([]);
  const anchorRef = useRef<{ virtualMs: number; wallMs: number; index: number } | null>(null);

  useEffect(() => {
    const unsub = useTelemetryStore.subscribe((state) => {
      speedRef.current = state.speed;
      pointsRef.current = state.points;
    });
    return unsub;
  }, []);

  useEffect(() => {
    const tick = () => {
      const isPlaying = useTelemetryStore.getState().isPlaying;
      const pts = pointsRef.current;
      if (!isPlaying) {
        anchorRef.current = null;
        rafRef.current = null;
        return;
      }
      if (pts.length === 0) {
        useTelemetryStore.getState().setIsPlaying(false);
        return;
      }

      const currentIndex = useTelemetryStore.getState().currentIndex;
      if (!anchorRef.current) {
        const startIndex = Math.min(currentIndex, pts.length - 1);
        anchorRef.current = {
          virtualMs: pointTsMs(pts[startIndex], pts[0]),
          wallMs: performance.now(),
          index: startIndex,
        };
        lastStoreUpdateRef.current = performance.now();
      }

      const anchor = anchorRef.current;
      const wallNow = performance.now();
      const virtualNow = anchor.virtualMs + (wallNow - anchor.wallMs) * speedRef.current;

      const last = pts[pts.length - 1];
      const lastMs = pointTsMs(last, last);
      if (virtualNow >= lastMs) {
        const interp = interpolateAt(lastMs, pts);
        const sink = markerSinkHolder.current;
        if (sink && interp) sink(interp);
        useTelemetryStore.getState().setCurrentIndex(pts.length - 1);
        useTelemetryStore.getState().setIsPlaying(false);
        anchorRef.current = null;
        rafRef.current = null;
        return;
      }

      const interp = interpolateAt(virtualNow, pts);
      const sink = markerSinkHolder.current;
      if (sink && interp) sink(interp);

      const lo = findIndexAtVirtual(virtualNow, pts);
      if (lo !== anchor.index) {
        anchor.index = lo;
        if (wallNow - lastStoreUpdateRef.current >= REACT_UPDATE_INTERVAL_MS) {
          lastStoreUpdateRef.current = wallNow;
          useTelemetryStore.getState().setCurrentIndex(lo);
        }
      }
      rafRef.current = requestAnimationFrame(tick);
    };

    const unsub = useTelemetryStore.subscribe((state) => {
      if (state.isPlaying) {
        if (rafRef.current === null) {
          rafRef.current = requestAnimationFrame(tick);
        }
      } else {
        if (rafRef.current !== null) {
          cancelAnimationFrame(rafRef.current);
          rafRef.current = null;
        }
        anchorRef.current = null;
      }
    });

    if (useTelemetryStore.getState().isPlaying && rafRef.current === null) {
      rafRef.current = requestAnimationFrame(tick);
    }

    return () => {
      unsub();
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      anchorRef.current = null;
    };
  }, []);
}

/**
 * Action provider. Safe to call from any component (PlaybackControls, MapView,
 * custom scrubbers). It does NOT run the rAF loop — that's `usePlaybackEngine`.
 */
export function usePlayback() {
  const setIsPlaying = useTelemetryStore((s) => s.setIsPlaying);
  const setSpeed = useTelemetryStore((s) => s.setSpeed);
  const setCurrentIndex = useTelemetryStore((s) => s.setCurrentIndex);

  const play = useCallback(() => {
    if (useTelemetryStore.getState().points.length === 0) return;
    setIsPlaying(true);
  }, [setIsPlaying]);

  const pause = useCallback(() => setIsPlaying(false), [setIsPlaying]);

  const changeSpeed = useCallback((s: number) => {
    const pts = useTelemetryStore.getState().points;
    const idx = useTelemetryStore.getState().currentIndex;
    if (pts.length > 0) {
      markerSinkHolder.current?.({
        ts: pointTsMs(pts[idx], pts[0]),
        lat: pts[idx].lat,
        lon: pts[idx].lon,
        speed: pts[idx].speed ?? 0,
        voltage: pts[idx].voltage ?? 0,
        current: pts[idx].current ?? 0,
        power: pts[idx].power ?? 0,
        batteryLevel: pts[idx].batteryLevel ?? 0,
      });
    }
    setSpeed(s);
  }, [setSpeed]);

  const seekToIndex = useCallback((index: number) => {
    const pts = useTelemetryStore.getState().points;
    if (pts.length === 0) return;
    const clamped = Math.max(0, Math.min(pts.length - 1, index));
    setCurrentIndex(clamped);
  }, [setCurrentIndex]);

  const registerMarkerSink = useCallback((sink: ((p: InterpolatedPoint | null) => void) | null) => {
    markerSinkHolder.current = sink;
  }, []);

  return { play, pause, setSpeed: changeSpeed, seekToIndex, registerMarkerSink };
}
