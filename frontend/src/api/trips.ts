import type { AxiosProgressEvent } from 'axios';
import { api } from './client';
import type { Trip, TripUpdatePayload } from '../types/trip';

interface BackendTrip {
  trip_id: string;
  user_id: string;
  trip_name: string;
  start_time: string;
  end_time: string;
  min_lat: number | null;
  max_lat: number | null;
  min_lon: number | null;
  max_lon: number | null;
  has_gps: boolean;
  is_shared: boolean;
  share_token: string | null;
  total_distance_meters: number | null;
  created_at: string;
}

function toTrip(t: BackendTrip): Trip {
  return {
    id: t.trip_id,
    userId: t.user_id,
    name: t.trip_name,
    startTime: t.start_time,
    endTime: t.end_time,
    minLat: t.min_lat,
    maxLat: t.max_lat,
    minLon: t.min_lon,
    maxLon: t.max_lon,
    hasGps: t.has_gps,
    isShared: t.is_shared,
    shareToken: t.share_token,
    totalDistanceMeters: t.total_distance_meters,
    createdAt: t.created_at,
  };
}

export async function listTrips(): Promise<Trip[]> {
  const { data } = await api.get<{ trips: BackendTrip[]; total: number; page: number; per_page: number }>('/trips');
  return data.trips.map(toTrip);
}

export async function getTrip(tripId: string): Promise<Trip> {
  const { data } = await api.get<BackendTrip>(`/trips/${tripId}`);
  return toTrip(data);
}

export async function updateTrip(tripId: string, payload: TripUpdatePayload): Promise<Trip> {
  const { data } = await api.put<BackendTrip>(`/trips/${tripId}`, { trip_name: payload.name });
  return toTrip(data);
}

export async function deleteTrip(tripId: string): Promise<void> {
  await api.delete(`/trips/${tripId}`);
}

export async function uploadTrip(
  file: File,
  idempotencyKey: string,
  onProgress?: (e: AxiosProgressEvent) => void
): Promise<{ jobId: string }> {
  const form = new FormData();
  form.append('file', file);
  const res = await api.post<{ job_id: string; jobId?: string; status: string; status_url: string; statusUrl?: string; message: string }>(
    '/trips',
    form,
    {
      headers: {
        'Content-Type': 'multipart/form-data',
        'Idempotency-Key': idempotencyKey,
      },
      onUploadProgress: onProgress,
    }
  );
  return { jobId: res.data.jobId ?? res.data.job_id };
}

interface ShareResponse {
  share_token: string | null;
  share_url: string | null;
  is_shared: boolean;
}

export async function shareTrip(tripId: string): Promise<ShareResponse> {
  const { data } = await api.post<ShareResponse>(`/trips/${tripId}/share`);
  return data;
}

export async function unshareTrip(tripId: string): Promise<ShareResponse> {
  const { data } = await api.delete<ShareResponse>(`/trips/${tripId}/share`);
  return data;
}
