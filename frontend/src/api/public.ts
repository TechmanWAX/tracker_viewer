import axios from 'axios';
import type { Trip } from '../types/trip';
import type { TelemetryPoint } from '../types/telemetry';

const publicApi = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  headers: { 'Content-Type': 'application/json' },
});

interface BackendTrip {
  trip_id: string; user_id: string; trip_name: string;
  start_time: string; end_time: string;
  min_lat: number | null; max_lat: number | null;
  min_lon: number | null; max_lon: number | null;
  has_gps: boolean; is_shared: boolean; share_token: string | null;
  total_distance_meters: number | null; created_at: string;
}

interface BackendTP {
  trip_id: string; timestamp: string;
  latitude: number | null; longitude: number | null;
  speed: number; gps_speed: number | null; gps_alt: number | null;
  gps_heading: number | null; gps_distance: number | null;
  voltage: number | null; current: number | null; phase_current: number | null;
  power: number | null; torque: number | null; pwm: number | null;
  battery_level: number | null; distance: number | null; totaldistance: number | null;
  system_temp: number | null; temp2: number | null;
  tilt: number | null; roll: number | null;
  mode: string | null; alert: string | null;
}

function toTrip(t: BackendTrip): Trip {
  return {
    id: t.trip_id, userId: t.user_id, name: t.trip_name,
    startTime: t.start_time, endTime: t.end_time,
    minLat: t.min_lat, maxLat: t.max_lat, minLon: t.min_lon, maxLon: t.max_lon,
    hasGps: t.has_gps, isShared: t.is_shared, shareToken: t.share_token,
    totalDistanceMeters: t.total_distance_meters, createdAt: t.created_at,
  };
}

function toPoint(p: BackendTP): TelemetryPoint {
  return {
    ts: p.timestamp, lat: p.latitude, lon: p.longitude, speed: p.speed,
    gpsSpeed: p.gps_speed, gpsAlt: p.gps_alt, gpsHeading: p.gps_heading, gpsDistance: p.gps_distance,
    voltage: p.voltage, current: p.current, phaseCurrent: p.phase_current,
    power: p.power, torque: p.torque, pwm: p.pwm, batteryLevel: p.battery_level,
    distance: p.distance, totalDistance: p.totaldistance,
    systemTemp: p.system_temp, temp2: p.temp2, tilt: p.tilt, roll: p.roll,
    mode: p.mode, alert: p.alert,
  };
}

export async function getPublicTrip(token: string): Promise<Trip> {
  const { data } = await publicApi.get<BackendTrip>(`/public/trips/${token}`);
  return toTrip(data);
}

export async function getPublicTripPoints(
  token: string, limit: number = 50000,
): Promise<{ points: TelemetryPoint[]; total: number }> {
  const { data } = await publicApi.get<{ trip_id: string; points: BackendTP[]; total: number }>(
    `/public/trips/${token}/points?limit=${limit}`,
  );
  return { points: data.points.map(toPoint), total: data.total };
}
