export interface User {
  id: string;
  email: string;
  username: string;
  isActive?: boolean;
  isVerified?: boolean;
  verifiedAt?: string | null;
  createdAt?: string | null;
}

export interface UserLoginPayload {
  email: string;
  password: string;
}

export interface UserRegisterPayload {
  email: string;
  username: string;
  password: string;
}

export interface JobResult {
  tripId: string | null;
  totalRows: number;
  validRows: number;
  errorRows: number;
  sampleErrors: Record<string, unknown>[] | null;
  parsingReport: string | null;
  error: string | null;
}

export interface JobStatus {
  id: string;
  status: 'pending' | 'processing' | 'done' | 'failed';
  filename: string;
  createdAt: string;
  result: JobResult | null;
  // Live progress reported by the server. Sourced from the dedicated
  // `progress` column on the `jobs` table, written by the Celery
  // worker via an atomic UPDATE. Null while the job is still
  // pending or before the worker has reported its first update.
  progress: number | null;
  processedBytes: number | null;
  totalBytes: number | null;
}

export interface ApiError {
  status: number;
  message: string;
  details?: Record<string, unknown>;
}
