export interface Trip {
  id: string;
  userId: string;
  name: string;
  startTime: string;
  endTime: string;
  // Bounding box is null when the trip has no GPS data.
  minLat: number | null;
  maxLat: number | null;
  minLon: number | null;
  maxLon: number | null;
  // True iff at least one telemetry point has lat/lng. The UI uses
  // this to decide between rendering a map or a "No GPS data"
  // placeholder.
  hasGps: boolean;
  isShared: boolean;
  shareToken: string | null;
  totalDistanceMeters: number | null;
  createdAt: string;
}

export interface TripUpdatePayload {
  name: string;
}
