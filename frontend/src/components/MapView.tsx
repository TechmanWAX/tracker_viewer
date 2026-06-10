import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { Map, View } from 'ol';
import TileLayer from 'ol/layer/Tile';
import VectorLayer from 'ol/layer/Vector';
import VectorSource from 'ol/source/Vector';
import XYZ from 'ol/source/XYZ';
import { Circle as CircleStyle, Fill, Stroke, Style } from 'ol/style';
import { LineString, Point } from 'ol/geom';
import Feature from 'ol/Feature';
import { fromLonLat } from 'ol/proj';
import { fetchPoints } from '../api/telemetry';
import { useTelemetryStore } from '../store/telemetryStore';
import { usePlayback } from '../hooks/usePlayback';
import type { TelemetryPoint } from '../types/telemetry';

const FETCH_LIMIT_OVERVIEW = 50000;
const RDP_TOLERANCE = 0.0001;
const RDP_HARD_CAP = 5000;
const AUTO_FIT_DELAY_MS = 30_000;

/* ─── RDP simplification (unchanged) ───────────────────────── */

function getPerpendicularDistance(
  p: { lat: number; lon: number },
  start: { lat: number; lon: number },
  end: { lat: number; lon: number }
): number {
  const x = p.lon, y = p.lat, x1 = start.lon, y1 = start.lat, x2 = end.lon, y2 = end.lat;
  const numerator = Math.abs((y2 - y1) * x - (x2 - x1) * y + x2 * y1 - y2 * x1);
  const denominator = Math.sqrt((y2 - y1) ** 2 + (x2 - x1) ** 2);
  return denominator === 0 ? 0 : numerator / denominator;
}

function simplifyPath(
  points: { lat: number; lon: number }[],
  tolerance: number
): { lat: number; lon: number }[] {
  if (points.length <= 2) return points;
  let maxDistance = 0, index = 0;
  for (let i = 1; i < points.length - 1; i++) {
    const dist = getPerpendicularDistance(points[i], points[0], points[points.length - 1]);
    if (dist > maxDistance) { index = i; maxDistance = dist; }
  }
  if (maxDistance > tolerance) {
    const left = simplifyPath(points.slice(0, index + 1), tolerance);
    const right = simplifyPath(points.slice(index), tolerance);
    return [...left.slice(0, -1), ...right];
  }
  return [points[0], points[points.length - 1]];
}

/* ─── styles ────────────────────────────────────────────────── */

const trackStyle = new Style({
  stroke: new Stroke({ color: '#4f9eff', width: 4 }),
});

const vehicleStyle = new Style({
  image: new CircleStyle({
    radius: 8,
    fill: new Fill({ color: '#ef4444' }),
    stroke: new Stroke({ color: '#fff', width: 2 }),
  }),
  zIndex: 100,
});

const hoverStyle = new Style({
  image: new CircleStyle({
    radius: 7,
    fill: new Fill({ color: '#fbbf24' }),
    stroke: new Stroke({ color: '#fff', width: 2 }),
  }),
  zIndex: 99,
});

/* ─── component ─────────────────────────────────────────────── */

interface Props { tripId: string; hasGps?: boolean; /** Set to false on share/public pages where points are loaded externally */ skipFetch?: boolean; }

export default function MapView({ tripId, hasGps = true, skipFetch = false }: Props) {
  const setPoints = useTelemetryStore((s) => s.setPoints);
  const points = useTelemetryStore((s) => s.points);
  const totalPoints = useTelemetryStore((s) => s.totalPoints);
  const currentIndex = useTelemetryStore((s) => s.currentIndex);
  const isPlaying = useTelemetryStore((s) => s.isPlaying);
  const hoverMs = useTelemetryStore((s) => s.hoverMs);
  const setHoverMs = useTelemetryStore((s) => s.setHoverMs);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [satellite, setSatellite] = useState(() => localStorage.getItem('map-satellite') === '1');

  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<Map | null>(null);
  const trackSourceRef = useRef(new VectorSource());
  const markerSourceRef = useRef(new VectorSource());
  const hoverSourceRef = useRef(new VectorSource());
  const abortRef = useRef<AbortController | null>(null);
  const { seekToIndex } = usePlayback();
  const lightLayerRef = useRef(new TileLayer({
    source: new XYZ({
      url: 'https://{a-c}.tile.opentopomap.org/{z}/{x}/{y}.png',
      maxZoom: 17,
      attributions: '© <a href="https://opentopomap.org">OpenTopoMap</a>',
    }),
    visible: true,
  }));
  const darkLayerRef = useRef(new TileLayer({
    source: new XYZ({
      url: 'https://{a-c}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
      maxZoom: 19,
      attributions: '© <a href="https://carto.com/">CARTO</a>',
    }),
    visible: false,
  }));
  const satLayerRef = useRef(new TileLayer({
    source: new XYZ({
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      maxZoom: 19,
      attributions: '© Esri',
    }),
    visible: false,
  }));

  // ---- init / destroy map ------------------------------------
  useEffect(() => {
    if (!containerRef.current) return;
    const map = new Map({
      target: containerRef.current,
      layers: [
        lightLayerRef.current,
        darkLayerRef.current,
        satLayerRef.current,
        new VectorLayer({ source: trackSourceRef.current, style: trackStyle }),
        new VectorLayer({ source: markerSourceRef.current }),
        new VectorLayer({ source: hoverSourceRef.current }),
      ],
      view: new View({ center: fromLonLat([37.6173, 55.7558]), zoom: 12 }),
      controls: [],
    });
    mapRef.current = map;
    return () => map.setTarget(undefined);
  }, []);

  // ---- sync tile layer to theme + satellite -----------------
  useEffect(() => {
    const sync = () => {
      const theme = document.documentElement.getAttribute('data-theme') || 'light';
      const sat = localStorage.getItem('map-satellite') === '1';
      lightLayerRef.current.setVisible(!sat && theme === 'light');
      darkLayerRef.current.setVisible(!sat && theme === 'dark');
      satLayerRef.current.setVisible(sat);
    };
    sync();
    const obs = new MutationObserver(sync);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => obs.disconnect();
  }, []);

  // ---- satellite toggle -------------------------------------
  const toggleSatellite = useCallback(() => {
    const next = !satellite;
    setSatellite(next);
    localStorage.setItem('map-satellite', next ? '1' : '0');
    lightLayerRef.current.setVisible(!next && (document.documentElement.getAttribute('data-theme') || 'light') === 'light');
    darkLayerRef.current.setVisible(!next && (document.documentElement.getAttribute('data-theme') || 'light') === 'dark');
    satLayerRef.current.setVisible(next);
  }, [satellite]);

  // ---- positioned points (filtered, full set) -----------------
  const positionedPoints = useMemo(
    () => points.filter((p) => p.lat != null && p.lon != null) as Array<TelemetryPoint & { lat: number; lon: number }>,
    [points],
  );

  // ---- polyline (RDP simplified) ------------------------------
  const polylineCoords = useMemo(() => {
    const positioned = positionedPoints;
    if (positioned.length === 0) return [] as [number, number][];
    const simplified = positioned.length > RDP_HARD_CAP
      ? simplifyPath(positioned, RDP_TOLERANCE)
      : positioned;
    return simplified.map((p) => fromLonLat([p.lon, p.lat])) as [number, number][];
  }, [positionedPoints]);

  // ---- update track layer ------------------------------------
  useEffect(() => {
    const src = trackSourceRef.current;
    src.clear();
    if (polylineCoords.length > 1) {
      src.addFeature(new Feature(new LineString(polylineCoords)));
    }
  }, [polylineCoords]);

  // ---- vehicle marker ----------------------------------------
  useEffect(() => {
    const src = markerSourceRef.current;
    src.clear();
    if (positionedPoints.length === 0) return;
    const idx = Math.min(currentIndex, positionedPoints.length - 1);
    const p = positionedPoints[idx];
    const f = new Feature(new Point(fromLonLat([p.lon, p.lat])));
    f.setStyle(vehicleStyle);
    src.addFeature(f);
  }, [currentIndex, positionedPoints]);

  // ---- hover marker ------------------------------------------
  useEffect(() => {
    const src = hoverSourceRef.current;
    src.clear();
    if (hoverMs == null || positionedPoints.length === 0) return;
    let best = positionedPoints[0];
    let bestDist = Infinity;
    for (const p of positionedPoints) {
      const d = Math.abs(new Date(p.ts).getTime() - hoverMs);
      if (d < bestDist) { bestDist = d; best = p; }
    }
    const f = new Feature(new Point(fromLonLat([best.lon, best.lat])));
    f.setStyle(hoverStyle);
    src.addFeature(f);
  }, [hoverMs, positionedPoints]);

  // ---- track hover / click ----------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const onPointer = (e: any) => {
      const coord = e.coordinate;
      const view = map.getView();
      // Check if pointer is near the polyline (within 20px tolerance)
      let hit = false;
      const tol = 20 / view.getResolution()!; // pixels → map units
      for (let i = 0; i < positionedPoints.length; i++) {
        const p = positionedPoints[i];
        const pc = fromLonLat([p.lon, p.lat]);
        const dx = pc[0] - coord[0], dy = pc[1] - coord[1];
        if (dx * dx + dy * dy < tol * tol) { hit = true; break; }
      }
      if (hit) {
        let bestIdx = 0, bestDist = Infinity;
        for (let i = 0; i < positionedPoints.length; i++) {
          const p = positionedPoints[i];
          const pc = fromLonLat([p.lon, p.lat]);
          const d = (pc[0] - coord[0]) ** 2 + (pc[1] - coord[1]) ** 2;
          if (d < bestDist) { bestDist = d; bestIdx = i; }
        }
        setHoverMs(new Date(positionedPoints[bestIdx].ts).getTime());
      } else {
        setHoverMs(null);
      }
    };
    const onClick = (e: any) => {
      const coord = e.coordinate;
      let bestIdx = 0, bestDist = Infinity;
      for (let i = 0; i < positionedPoints.length; i++) {
        const p = positionedPoints[i];
        const pc = fromLonLat([p.lon, p.lat]);
        const d = (pc[0] - coord[0]) ** 2 + (pc[1] - coord[1]) ** 2;
        if (d < bestDist) { bestDist = d; bestIdx = i; }
      }
      seekToIndex(bestIdx);
    };
    map.on('pointermove', onPointer);
    map.on('singleclick', onClick);
    return () => {
      map.un('pointermove', onPointer);
      map.un('singleclick', onClick);
    };
  }, [positionedPoints, setHoverMs, seekToIndex]);

  // ---- auto-fit on trip load ---------------------------------
  const fittedFor = useRef<string | null>(null);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || positionedPoints.length === 0) return;
    if (fittedFor.current === tripId) return;
    fittedFor.current = tripId;
    if (positionedPoints.length === 1) {
      map.getView().setCenter(fromLonLat([positionedPoints[0].lon, positionedPoints[0].lat]));
      map.getView().setZoom(15);
      return;
    }
    const extent = positionedPoints.reduce(
      (acc, p) => {
        const c = fromLonLat([p.lon, p.lat]);
        acc[0] = Math.min(acc[0], c[0]);
        acc[1] = Math.min(acc[1], c[1]);
        acc[2] = Math.max(acc[2], c[0]);
        acc[3] = Math.max(acc[3], c[1]);
        return acc;
      },
      [Infinity, Infinity, -Infinity, -Infinity] as number[]
    );
    map.getView().fit(extent as [number, number, number, number], { padding: [40, 40, 40, 40], maxZoom: 17 });
  }, [positionedPoints, tripId]);

  // ---- auto-center on play / 30s idle -------------------------
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wasPlaying = useRef(false);
  const programmatic = useRef(false);

  const fitFull = useCallback(() => {
    const map = mapRef.current;
    if (!map || positionedPoints.length === 0) return;
    programmatic.current = true;
    if (positionedPoints.length === 1) {
      map.getView().animate({ center: fromLonLat([positionedPoints[0].lon, positionedPoints[0].lat]), zoom: 15, duration: 400 });
    } else {
      const extent = positionedPoints.reduce(
        (acc, p) => { const c = fromLonLat([p.lon, p.lat]); acc[0] = Math.min(acc[0], c[0]); acc[1] = Math.min(acc[1], c[1]); acc[2] = Math.max(acc[2], c[0]); acc[3] = Math.max(acc[3], c[1]); return acc; },
        [Infinity, Infinity, -Infinity, -Infinity] as number[]
      );
      map.getView().fit(extent as [number, number, number, number], { padding: [40, 40, 40, 40], maxZoom: 17, duration: 400 });
    }
    setTimeout(() => { programmatic.current = false; }, 500);
  }, [positionedPoints]);

  const panToCurrent = useCallback(() => {
    const map = mapRef.current;
    if (!map || positionedPoints.length === 0) return;
    const idx = Math.min(useTelemetryStore.getState().currentIndex, positionedPoints.length - 1);
    const p = positionedPoints[idx];
    programmatic.current = true;
    map.getView().animate({ center: fromLonLat([p.lon, p.lat]), duration: 400 });
    setTimeout(() => { programmatic.current = false; }, 500);
  }, [positionedPoints]);

  useEffect(() => {
    if (isPlaying && !wasPlaying.current) {
      fitFull();
      if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
    }
    wasPlaying.current = isPlaying;
  }, [isPlaying, fitFull]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const schedule = () => {
      if (programmatic.current) return;
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        if (useTelemetryStore.getState().isPlaying) panToCurrent();
        else fitFull();
      }, AUTO_FIT_DELAY_MS);
    };
    map.on('pointerdrag', schedule);
    map.on('movestart', schedule);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      map.un('pointerdrag', schedule);
      map.un('movestart', schedule);
    };
  }, [fitFull, panToCurrent]);


  // ---- fetch data --------------------------------------------
  useEffect(() => {
    if (!hasGps || skipFetch) { setPoints([]); return; }
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
      .catch((e: unknown) => { if (!ctrl.signal.aborted) setError(String(e)); })
      .finally(() => { if (!ctrl.signal.aborted) setLoading(false); });
    return () => { if (abortRef.current) { abortRef.current.abort(); abortRef.current = null; } };
  }, [tripId, setPoints, hasGps]);

  // ---- render ------------------------------------------------
  if (error) {
    return <div style={{ padding: 16, color: 'var(--danger)' }}>Map error: {error}</div>;
  }

  if (!hasGps) {
    return (
      <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 8, color: 'var(--fg-muted)', background: 'var(--bg-secondary)', textAlign: 'center', padding: 16 }}>
        <div style={{ fontSize: 32, opacity: 0.4 }}>📍</div>
        <div style={{ fontSize: 14, fontWeight: 500 }}>No GPS data for this trip</div>
        <div style={{ fontSize: 12, opacity: 0.7, maxWidth: 320 }}>The source CSV didn't include GPS coordinates. Telemetry is still available in the dashboard.</div>
      </div>
    );
  }

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
      <div className="map-overlay" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <span>{loading ? 'Loading…' : `${points.length}${points.length < totalPoints ? ` / ${totalPoints}` : ''} pts`}</span>
        <button
          onClick={toggleSatellite}
          className={satellite ? 'btn-primary btn-sm' : 'btn-sm'}
          style={{ fontSize: 12, margin: 0, padding: '3px 8px' }}
          title="Toggle satellite view"
        >
          🛰️
        </button>
      </div>
    </div>
  );
}
