export interface TelemetryPoint {
  ts: string;
  // Lat/lon are null for trips whose CSV didn't include GPS
  // coordinates (older controller firmware variants). The playback
  // engine and dashboard tolerate nulls by treating them as "no
  // position"; the map doesn't render such trips at all.
  lat: number | null;
  lon: number | null;
  // Wheel speed (km/h), always present.
  speed: number;
  // GPS-derived (nullable: not all firmware emits them, and even
  // when it does, individual rows can be NULL when the receiver
  // had no fix at that moment).
  gpsSpeed: number | null;
  gpsAlt: number | null;
  gpsHeading: number | null;
  gpsDistance: number | null;
  // Power-train
  voltage: number | null;
  current: number | null;       // signed: regen → negative
  phaseCurrent: number | null;  // motor-side current
  power: number | null;         // signed: regen → negative
  torque: number | null;
  pwm: number | null;           // duty cycle %
  batteryLevel: number | null;
  // Odometer
  distance: number | null;       // per-trip running odometer
  totalDistance: number | null;  // device-lifetime odometer
  // Vehicle state
  systemTemp: number | null;
  temp2: number | null;
  tilt: number | null;
  roll: number | null;
  // Status strings
  mode: string | null;
  alert: string | null;
}

export interface TelemetryQueryParams {
  bbox?: [number, number, number, number];
  fromTs?: string;
  toTs?: string;
  limit?: number;
}
