import { api } from './client';
import type { JobStatus, JobResult } from '../types/api';

interface BackendJobResult {
  trip_id: string | null;
  total_rows: number;
  valid_rows: number;
  error_rows: number;
  sample_errors: Record<string, unknown>[] | null;
  parsing_report: string | null;
  error: string | null;
}

interface BackendJob {
  job_id: string;
  user_id: string;
  status: 'pending' | 'processing' | 'done' | 'failed';
  filename: string;
  created_at: string;
  result: BackendJobResult | null;
  // Live progress — sourced from the dedicated columns. Null until
  // the worker reports its first update.
  progress: number | null;
  processed_bytes: number | null;
  total_bytes: number | null;
}

function toResult(r: BackendJobResult | null): JobResult | null {
  if (!r) return null;
  return {
    tripId: r.trip_id,
    totalRows: r.total_rows,
    validRows: r.valid_rows,
    errorRows: r.error_rows,
    sampleErrors: r.sample_errors,
    parsingReport: r.parsing_report,
    error: r.error,
  };
}

export async function getJob(jobId: string): Promise<JobStatus> {
  const { data } = await api.get<BackendJob>(`/jobs/${jobId}`);
  return {
    id: data.job_id,
    status: data.status,
    filename: data.filename,
    createdAt: data.created_at,
    result: toResult(data.result),
    progress: data.progress ?? null,
    processedBytes: data.processed_bytes ?? null,
    totalBytes: data.total_bytes ?? null,
  };
}
