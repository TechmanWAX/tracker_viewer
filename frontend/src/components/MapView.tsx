import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { MapContainer, TileLayer, Polyline, Marker, useMap } from 'react-leaflet';
import L from 'leaflet';
import { fetchPoints } from '../api/telemetry';
import { useTelemetryStore } from '../store/telemetryStore';
import { usePlayback } from '../hooks/usePlayback';
import type { TelemetryPoint } from '../types/telemetry';

// Max points the map fetches in one shot. Bumped from 5000 to
// cover trips with 40k+ points. The polyline is RDP-simplified
// to RDP_HARD_CAP below, so the actual DOM node count stays
// bounded regardless of this value.
const FETCH_LIMIT_OVERVIEW = 50000;
const RDP_TOLERANCE = 0.0001;
// RDP-simplified polyline cap. Raising from the original 2000
// lets large trips show more detail without blowing up the
// canvas node count — Leaflet prefersCanvas can handle 5k
// segments comfortably.
const RDP_HARD_CAP = 5000;

interface Props {
  tripId: string;
  // True iff at least one row in this trip has lat/lng. The trip
  // detail page passes this from the Trip response; when false the
  // map is replaced with a "No GPS data for this trip" placeholder
  // and we skip the /points fetch entirely (no need to download
  // 100k rows of telemetry just to render an empty message).
  hasGps?: boolean;
}

function getPerpendicularDistance(
  p: { lat: number; lon: number },
  start: { lat: number; lon: number },
  end: { lat: number; lon: number }
): number {
  const x = p.lon, y = p.lat;
  const x1 = start.lon, y1 = start.lat;
  const x2 = end.lon, y2 = end.lat;
  const numerator = Math.abs((y2 - y1) * x - (x2 - x1) * y + x2 * y1 - y2 * x1);
  const denominator = Math.sqrt((y2 - y1) ** 2 + (x2 - x1) ** 2);
  if (denominator === 0) return 0;
  return numerator / denominator;
}

function simplifyPath(
  points: { lat: number; lon: number }[],
  tolerance: number
): { lat: number; lon: number }[] {
  if (points.length <= 2) return points;
  let maxDistance = 0;
  let index = 0;
  for (let i = 1; i < points.length - 1; i++) {
    const dist = getPerpendicularDistance(points[i], points[0], points[points.length - 1]);
    if (dist > maxDistance) {
      index = i;
      maxDistance = dist;
    }
  }
  if (maxDistance > tolerance) {
    const left = simplifyPath(points.slice(0, index + 1), tolerance);
    const right = simplifyPath(points.slice(index), tolerance);
    return [...left.slice(0, -1), ...right];
  }
  return [points[0], points[points.length - 1]];
}

/**
 * Auto-fit the map to the loaded points.
 *
 * Background. The MapContainer's `center` and `zoom` props are
 * **initial values only** — react-leaflet does not re-apply them on
 * later re-renders. So if the trip data arrives after the map is
 * mounted (which is the common case — we fetch points asynchronously
 * in a useEffect), the user is stuck looking at the default Moscow /
 * zoom-2 world view with the polyline drawn somewhere off-screen as
 * a few pixels. Looks exactly like "the track didn't load".
 *
 * Fix: a child of MapContainer that uses `useMap` to get the live
 * Leaflet instance and calls `fitBounds` the first time we have
 * points for the current `tripId`. We re-fit on every `tripId` change
 * (so navigating between trips jumps to each new track) but NOT on
 * subsequent point updates — once the user has seen the trip, don't
 * fight their panning/zooming.
 *
 * Edge cases:
 *  - 0 points: no-op (don't move the map).
 *  - 1 point: `fitBounds` chokes on a zero-area bound. Fall back to
 *    `setView` at zoom 15.
 *  - 2+ points with the exact same lat/lon (degenerate): also fall
 *    back to `setView`.
 */
function BoundsFitter({
  points,
  tripId,
}: {
  points: TelemetryPoint[];
  tripId: string;
}) {
  const map = useMap();
  const fittedFor = useRef<string | null>(null);

  useEffect(() => {
    // Defensive filter: even though we no-op the whole component
    // when the trip has no GPS, the API can still return rows
    // with null lat/lon for a mixed trip (it doesn't currently
    // happen, but the schema now allows it). Drop them here so
    // `Math.min` doesn't choke on `null - 0` = NaN.
    const positioned = points.filter(
      (p) => p.lat != null && p.lon != null,
    ) as Array<{ lat: number; lon: number; ts: string; speed: number; voltage: number | null; current: number | null; power: number | null; batteryLevel: number | null }>;
    if (positioned.length === 0) return;
    if (fittedFor.current === tripId) return;
    fittedFor.current = tripId;

    if (positioned.length === 1) {
      map.setView([positioned[0].lat, positioned[0].lon], 15, { animate: false });
      return;
    }

    const lats = positioned.map((p) => p.lat);
    const lons = positioned.map((p) => p.lon);
    const minLat = Math.min(...lats);
    const maxLat = Math.max(...lats);
    const minLon = Math.min(...lons);
    const maxLon = Math.max(...lons);
    if (minLat === maxLat && minLon === maxLon) {
      map.setView([minLat, minLon], 15, { animate: false });
      return;
    }
    const bounds = L.latLngBounds(
      [minLat, minLon],
      [maxLat, maxLon],
    );
    map.fitBounds(bounds, { padding: [40, 40], animate: false });
  }, [points, tripId, map]);

  return null;
}

/**
 * Auto-center: fits the map when playback starts and re-fits
 * 30 seconds after the last user interaction (pan/zoom).
 */
const AUTO_FIT_DELAY_MS = 30_000;

function AutoCenter({
  positionedPoints,
  currentIndex,
  isPlaying,
}: {
  positionedPoints: Array<TelemetryPoint & { lat: number; lon: number }>;
  currentIndex: number;
  isPlaying: boolean;
}) {
  const map = useMap();
  const wasPlaying = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const programmaticRef = useRef(false);

  const fitAroundIndex = useCallback((idx: number) => {
    if (positionedPoints.length === 0) return;
    const i = Math.min(idx, positionedPoints.length - 1);
    const p = positionedPoints[i];
    programmaticRef.current = true;
    map.panTo([p.lat, p.lon], { animate: true, duration: 0.5 });
    setTimeout(() => { programmaticRef.current = false; }, 600);
  }, [map, positionedPoints]);

  const fitFullTrack = useCallback(() => {
    if (positionedPoints.length === 0) return;
    if (positionedPoints.length === 1) {
      const p = positionedPoints[0];
      programmaticRef.current = true;
      map.setView([p.lat, p.lon], 15, { animate: true });
      setTimeout(() => { programmaticRef.current = false; }, 500);
      return;
    }
    const lats = positionedPoints.map((p) => p.lat);
    const lons = positionedPoints.map((p) => p.lon);
    const bounds = L.latLngBounds(
      [Math.min(...lats), Math.min(...lons)],
      [Math.max(...lats), Math.max(...lons)],
    );
    programmaticRef.current = true;
    map.fitBounds(bounds, { padding: [40, 40], animate: true, maxZoom: 17 });
    setTimeout(() => { programmaticRef.current = false; }, 500);
  }, [map, positionedPoints]);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const scheduleAutoFit = useCallback(() => {
    clearTimer();
    timerRef.current = setTimeout(() => {
      if (useTelemetryStore.getState().isPlaying) {
        fitAroundIndex(useTelemetryStore.getState().currentIndex);
      } else {
        fitFullTrack();
      }
    }, AUTO_FIT_DELAY_MS);
  }, [clearTimer, fitAroundIndex, fitFullTrack]);

  useEffect(() => {
    if (isPlaying && !wasPlaying.current) {
      fitFullTrack();
      clearTimer();
    }
    wasPlaying.current = isPlaying;
  }, [isPlaying, fitFullTrack, clearTimer]);

  useEffect(() => {
    const onInteract = () => {
      if (programmaticRef.current) return;
      scheduleAutoFit();
    };
    map.on('movestart', onInteract);
    map.on('zoomstart', onInteract);
    return () => {
      clearTimer();
      map.off('movestart', onInteract);
      map.off('zoomstart', onInteract);
    };
  }, [map, scheduleAutoFit, clearTimer]);

  useEffect(() => () => clearTimer(), [clearTimer]);

  return null;
}

const vehicleIcon = L.divIcon({
  className: 'custom-vehicle-icon',
  html: '<div style="background-color:#ef4444;width:14px;height:14px;border:2px solid white;border-radius:50%;box-shadow:0 0 6px rgba(0,0,0,0.6);"></div>',
  iconSize: [14, 14],
  iconAnchor: [7, 7],
});

const hoverIcon = L.divIcon({
  className: 'custom-hover-icon',
  html: '<div style="background-color:#fbbf24;width:12px;height:12px;border:2px solid white;border-radius:50%;box-shadow:0 0 6px rgba(0,0,0,0.5);opacity:0.8;"></div>',
  iconSize: [12, 12],
  iconAnchor: [6, 6],
});

export default function MapView({ tripId, hasGps = true }: Props) {
  const setPoints = useTelemetryStore((s) => s.setPoints);
  const points = useTelemetryStore((s) => s.points);
  const totalPoints = useTelemetryStore((s) => s.totalPoints);
  const currentIndex = useTelemetryStore((s) => s.currentIndex);
  const isPlaying = useTelemetryStore((s) => s.isPlaying);
  const hoverMs = useTelemetryStore((s) => s.hoverMs);
  const setHoverMs = useTelemetryStore((s) => s.setHoverMs);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const markerRef = useRef<L.Marker | null>(null);
  const hoverMarkerRef = useRef<L.Marker | null>(null);
  const { registerMarkerSink, seekToIndex } = usePlayback();

  useEffect(() => {
    return () => {
      if (abortRef.current) {
        abortRef.current.abort();
        abortRef.current = null;
      }
      registerMarkerSink(null);
    };
  }, [tripId, registerMarkerSink]);

  useEffect(() => {
    registerMarkerSink((p) => {
      const m = markerRef.current;
      if (m && p && p.lat != null && p.lon != null) {
        m.setLatLng([p.lat, p.lon]);
      }
    });
  }, [registerMarkerSink]);

  useEffect(() => {
    if (points.length === 0) return;
    const m = markerRef.current;
    if (m) {
      const p = points[Math.min(currentIndex, points.length - 1)];
      if (p.lat != null && p.lon != null) {
        m.setLatLng([p.lat, p.lon]);
      }
    }
  }, [currentIndex, points]);

  // Load the full trip once per `tripId`. We deliberately do NOT
  // re-fetch on map pan/zoom — see the comment above `BoundsFitter`:
  // the backend's bbox filter returns *only* points inside the current
  // viewport, and replacing the full set with that subset used to chop
  // the track off as the user zoomed in. The full set is bounded by
  // FETCH_LIMIT_OVERVIEW (5000) and the polyline is RDP-simplified to
  // RDP_HARD_CAP (2000) for canvas performance, so the dataset is
  // small enough to hold in memory and re-render on every pan/zoom.
  useEffect(() => {
    if (!hasGps) {
      // No GPS → no map. The telemetry dashboard still uses
      // `useTelemetryStore`, so the worker on the trip detail
      // page is responsible for fetching points when hasGps=true.
      // We just clear the store so a previous trip's points
      // don't leak into this one.
      setPoints([]);
      return;
    }
    if (abortRef.current) abortRef.current.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setLoading(true);
    fetchPoints(tripId, { limit: FETCH_LIMIT_OVERVIEW })
      .then(({ points: fetched, total }) => {
        if (ctrl.signal.aborted) return;
        setPoints(fetched, total);
        setError(null);
      })
      .catch((e: unknown) => {
        if (ctrl.signal.aborted) return;
        setError(String(e));
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setLoading(false);
      });
  }, [tripId, setPoints, hasGps]);

  // All hooks above — the early returns below MUST stay below every
  // hook call, otherwise React sees a different number of hooks on
  // successive renders and throws "Rendered fewer hooks than
  // expected". (This bit us when the no-GPS branch was added
  // after the useMemo calls — opening a no-GPS trip crashed with
  // that exact error.) The hooks below are no-ops when `hasGps` is
  // false, which is fine: useMemo just runs the factory once and
  // memoises the (empty) result.

  const initialCenter: [number, number] = useMemo(() => {
    const positioned = points.filter(
      (p) => p.lat != null && p.lon != null,
    ) as Array<{ lat: number; lon: number }>;
    if (positioned.length === 0) return [55.7558, 37.6173];
    let sumLat = 0;
    let sumLon = 0;
    for (const p of positioned) {
      sumLat += p.lat;
      sumLon += p.lon;
    }
    return [sumLat / positioned.length, sumLon / positioned.length];
  }, [points]);

  const polylinePoints = useMemo<[number, number][]>(() => {
    const positioned = points.filter(
      (p) => p.lat != null && p.lon != null,
    ) as Array<{ lat: number; lon: number }>;
    if (positioned.length > RDP_HARD_CAP) {
      return simplifyPath(positioned, RDP_TOLERANCE).map((p) => [p.lat, p.lon]);
    }
    return positioned.map((p) => [p.lat, p.lon]);
  }, [points]);

  const positionedPoints = useMemo(
    () =>
      points.filter(
        (p) => p.lat != null && p.lon != null,
      ) as Array<TelemetryPoint & { lat: number; lon: number }>,
    [points],
  );

  // Hover marker: moved independently from playback. When the user
  // hovers a chart or the polyline, the store's `hoverMs` drives
  // this marker to the corresponding position.
  useEffect(() => {
    const m = hoverMarkerRef.current;
    if (!m) return;
    if (hoverMs == null) {
      m.setOpacity(0);
      return;
    }
    for (let i = 0; i < positionedPoints.length - 1; i++) {
      const a = positionedPoints[i];
      const b = positionedPoints[i + 1];
      const tA = new Date(a.ts).getTime();
      const tB = new Date(b.ts).getTime();
      if (tA <= hoverMs && hoverMs <= tB) {
        const frac = tB === tA ? 0 : (hoverMs - tA) / (tB - tA);
        const lat = a.lat + (b.lat - a.lat) * frac;
        const lon = a.lon + (b.lon - a.lon) * frac;
        m.setLatLng([lat, lon]);
        m.setOpacity(0.9);
        return;
      }
    }
    if (positionedPoints.length > 0) {
      m.setLatLng([positionedPoints[0].lat, positionedPoints[0].lon]);
      m.setOpacity(0.9);
    }
  }, [hoverMs, positionedPoints]);

  const currentPos: [number, number] | null = positionedPoints.length
    ? (() => {
        const idx = Math.min(currentIndex, positionedPoints.length - 1);
        const p = positionedPoints[idx];
        return [p.lat, p.lon];
      })()
    : null;

  if (error) {
    return (
      <div style={{ padding: 16, color: 'var(--danger)' }}>
        Map error: {error}
      </div>
    );
  }

  if (!hasGps) {
    return (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexDirection: 'column',
          gap: 8,
          color: 'var(--fg-muted, #888)',
          background: 'var(--bg-2)',
          textAlign: 'center',
          padding: 16,
        }}
      >
        <div style={{ fontSize: 32, opacity: 0.4 }}>📍</div>
        <div style={{ fontSize: 14, fontWeight: 500 }}>
          No GPS data for this trip
        </div>
        <div style={{ fontSize: 12, opacity: 0.7, maxWidth: 320 }}>
          The source CSV didn't include GPS coordinates. Telemetry
          (speed, voltage, current, power, battery) is still available
          in the dashboard on the right.
        </div>
      </div>
    );
  }

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <MapContainer
        center={initialCenter}
        zoom={points.length ? 13 : 2}
        style={{ height: '100%', width: '100%' }}
        preferCanvas={true}
      >
        <TileLayer
          attribution='&copy; OpenStreetMap contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <BoundsFitter points={points} tripId={tripId} />
        <AutoCenter positionedPoints={positionedPoints} currentIndex={currentIndex} isPlaying={isPlaying} />
        {polylinePoints.length > 1 && (
          <Polyline
            positions={polylinePoints}
            pathOptions={{ color: '#4f9eff', weight: 4, opacity: 0.9 }}
            eventHandlers={{
              mousemove: (e) => {
                const { lat, lng } = e.latlng;
                let bestIdx = 0;
                let bestDist = Infinity;
                for (let i = 0; i < positionedPoints.length; i++) {
                  const p = positionedPoints[i];
                  const d = (p.lat - lat) ** 2 + (p.lon - lng) ** 2;
                  if (d < bestDist) { bestDist = d; bestIdx = i; }
                }
                const tsMs = new Date(positionedPoints[bestIdx].ts).getTime();
                setHoverMs(tsMs);
              },
              mouseout: () => setHoverMs(null),
              click: (e) => {
                const { lat, lng } = e.latlng;
                let bestIdx = 0;
                let bestDist = Infinity;
                for (let i = 0; i < positionedPoints.length; i++) {
                  const p = positionedPoints[i];
                  const d = (p.lat - lat) ** 2 + (p.lon - lng) ** 2;
                  if (d < bestDist) { bestDist = d; bestIdx = i; }
                }
                seekToIndex(bestIdx);
              },
            }}
          />
        )}
        {currentPos && (
          <Marker
            ref={markerRef}
            position={currentPos}
            icon={vehicleIcon}
          />
        )}
        {hoverMs != null && (
          <Marker
            ref={hoverMarkerRef}
            position={positionedPoints.length > 0 ? [positionedPoints[0].lat, positionedPoints[0].lon] : [0, 0]}
            icon={hoverIcon}
            zIndexOffset={900}
          />
        )}
      </MapContainer>
      <div
        style={{
          position: 'absolute',
          top: 10,
          left: 10,
          zIndex: 1000,
          background: 'rgba(15, 17, 21, 0.85)',
          color: 'var(--fg)',
          padding: '6px 10px',
          borderRadius: 6,
          fontSize: 12,
          fontFamily: 'monospace',
        }}
      >
        {loading ? 'Loading…' : `${points.length}${points.length < totalPoints ? ` / ${totalPoints}` : ''} pts`}
      </div>
    </div>
  );
}
