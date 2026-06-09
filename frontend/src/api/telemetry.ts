import { api } from './client';
import type { TelemetryPoint, TelemetryQueryParams } from '../types/telemetry';

interface BackendTelemetryPoint {
  trip_id: string;
  timestamp: string;
  latitude: number | null;
  longitude: number | null;
  speed: number;
  gps_speed: number | null;
  gps_alt: number | null;
  gps_heading: number | null;
  gps_distance: number | null;
  voltage: number | null;
  current: number | null;
  phase_current: number | null;
  power: number | null;
  torque: number | null;
  pwm: number | null;
  battery_level: number | null;
  distance: number | null;
  totaldistance: number | null;
  system_temp: number | null;
  temp2: number | null;
  tilt: number | null;
  roll: number | null;
  mode: string | null;
  alert: string | null;
}

function toPoint(p: BackendTelemetryPoint): TelemetryPoint {
  return {
    ts: p.timestamp,
    lat: p.latitude,
    lon: p.longitude,
    speed: p.speed,
    gpsSpeed: p.gps_speed,
    gpsAlt: p.gps_alt,
    gpsHeading: p.gps_heading,
    gpsDistance: p.gps_distance,
    voltage: p.voltage,
    current: p.current,
    phaseCurrent: p.phase_current,
    power: p.power,
    torque: p.torque,
    pwm: p.pwm,
    batteryLevel: p.battery_level,
    distance: p.distance,
    totalDistance: p.totaldistance,
    systemTemp: p.system_temp,
    temp2: p.temp2,
    tilt: p.tilt,
    roll: p.roll,
    mode: p.mode,
    alert: p.alert,
  };
}

export async function fetchPoints(
  tripId: string,
  params: TelemetryQueryParams
): Promise<{ points: TelemetryPoint[]; total: number }> {
  const search = new URLSearchParams();
  if (params.bbox) search.set('bbox', params.bbox.join(','));
  if (params.fromTs) search.set('from_ts', params.fromTs);
  if (params.toTs) search.set('to_ts', params.toTs);
  if (params.limit) search.set('limit', String(params.limit));
  const { data } = await api.get<{ trip_id: string; points: BackendTelemetryPoint[]; total: number }>(
    `/trips/${tripId}/points?${search.toString()}`
  );
  return { points: data.points.map(toPoint), total: data.total };
}
