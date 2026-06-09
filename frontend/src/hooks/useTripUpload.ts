import { useCallback, useRef, useState } from 'react';
import type { AxiosProgressEvent } from 'axios';
import { uploadTrip } from '../api/trips';
import { getJob } from '../api/jobs';
import type { JobStatus } from '../types/api';

function uuidv4(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

// Poll configuration. The original spec called for 60 attempts at
// backoff 1s * 1.5^n capped at 10s — about 10 minutes total. In
// practice users read this as "stuck" long before then, and the
// frontend gets into a state where the job is still "pending" but
// polling has stopped, so the upload button stays disabled forever.
// 30 attempts at the same backoff curve lands at ~4-5 minutes, which
// is enough for any 100k-row CSV the spec describes.
const MAX_POLL_ATTEMPTS = 30;
const POLL_BASE_MS = 1_000;
const POLL_CAP_MS = 10_000;

export type UploadPhase = 'idle' | 'uploading' | 'parsing' | 'done' | 'failed';

export interface UseTripUploadResult {
  upload: (
    file: File,
    onProgress?: (e: AxiosProgressEvent) => void,
  ) => Promise<void>;
  job: JobStatus | null;
  /** True while bytes are flying or the server is parsing. */
  isBusy: boolean;
  /** 0-1 fraction of bytes uploaded, or null. */
  uploadProgress: number | null;
  /** 0-1 fraction of CSV rows parsed, or null. */
  parseProgress: number | null;
  /** Human-readable error string, or null. */
  error: string | null;
  reset: () => void;
}

export function useTripUpload(): UseTripUploadResult {
  const [job, setJob] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [parseProgress, setParseProgress] = useState<number | null>(null);

  const keyRef = useRef<string>(uuidv4());
  const pollRef = useRef<number | null>(null);
  const attemptRef = useRef(0);

  const stop = useCallback(() => {
    if (pollRef.current) {
      window.clearTimeout(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const reset = useCallback(() => {
    stop();
    keyRef.current = uuidv4();
    attemptRef.current = 0;
    setJob(null);
    setError(null);
    setUploadProgress(null);
    setParseProgress(null);
  }, [stop]);

  const poll = useCallback(
    async (jobId: string): Promise<void> => {
      attemptRef.current += 1;
      if (attemptRef.current > MAX_POLL_ATTEMPTS) {
        // CRITICAL: clear the job too, otherwise isBusy stays true
        // and the upload button stays disabled forever. The error
        // is shown by TripUploadPage in its own div.
        setJob(null);
        setParseProgress(null);
        setError(
          `Parsing is taking too long (>${Math.round(MAX_POLL_ATTEMPTS * POLL_CAP_MS / 1000)}s). ` +
          `The job is still running on the server — open the trips list ` +
          `in a minute and it may finish.`,
        );
        stop();
        return;
      }
      try {
        const j = await getJob(jobId);
        setJob(j);

        // Track parse progress from the server's reported fraction.
        // Sourced from the top-level `progress` column on the jobs
        // table, written by the worker via an atomic UPDATE.
        const p = j.progress;
        if (typeof p === 'number' && Number.isFinite(p)) {
          setParseProgress(Math.max(0, Math.min(1, p)));
        }

        if (j.status === 'done' || j.status === 'failed') {
          stop();
          // Pin progress at the boundary.
          setParseProgress(j.status === 'done' ? 1 : p);
          if (j.status === 'failed' && !j.result?.error) {
            setError('Upload failed (no error detail from server).');
          }
          return;
        }
        // Exponential backoff, capped.
        const delay = Math.min(
          POLL_CAP_MS,
          POLL_BASE_MS * 1.5 ** Math.min(attemptRef.current, 5),
        );
        pollRef.current = window.setTimeout(() => poll(jobId), delay);
      } catch (e) {
        // Network blip, 401, 429, etc. Don't get stuck — clear the
        // job and surface the error. The user can hit Upload again.
        setJob(null);
        setParseProgress(null);
        setError(humanizeError(e));
        stop();
      }
    },
    [stop],
  );

  const upload = useCallback(
    async (file: File, onProgress?: (e: AxiosProgressEvent) => void) => {
      setError(null);
      setParseProgress(null);
      setUploadProgress(0);
      attemptRef.current = 0;
      try {
        const { jobId } = await uploadTrip(file, keyRef.current, (e) => {
          if (typeof e.total === 'number' && e.total > 0) {
            setUploadProgress(Math.max(0, Math.min(1, e.loaded / e.total)));
          }
          onProgress?.(e);
        });
        setUploadProgress(1);
        // Optimistic pending state — getJob fills in the rest.
        setJob({
          id: jobId,
          status: 'pending',
          filename: file.name,
          createdAt: new Date().toISOString(),
          result: null,
          progress: null,
          processedBytes: null,
          totalBytes: null,
        });
        await poll(jobId);
      } catch (e) {
        setJob(null);
        setUploadProgress(null);
        setParseProgress(null);
        setError(humanizeError(e));
      }
    },
    [poll],
  );

  const isBusy =
    job?.status === 'pending' || job?.status === 'processing'
      ? true
      : uploadProgress !== null && uploadProgress < 1;

  return { upload, job, isBusy, uploadProgress, parseProgress, error, reset };
}

/**
 * Map Axios errors onto a one-line, user-readable message. The default
 * `String(e)` is a giant AxiosError dump that confuses users and hides
 * the real cause.
 */
function humanizeError(e: unknown): string {
  if (typeof e === 'string') return e;
  if (e && typeof e === 'object') {
    // Axios error shape
    const anyE = e as {
      response?: { status?: number; data?: { detail?: string } };
      message?: string;
      code?: string;
    };
    const status = anyE.response?.status;
    const detail = anyE.response?.data?.detail;
    if (status === 400) return detail || 'The file is invalid (400).';
    if (status === 401) return 'Session expired. Please log in again.';
    if (status === 403) return 'Permission denied (CSRF or auth).';
    if (status === 404) return 'Resource not found.';
    if (status === 409) {
      // The server returns a friendly `detail` that names the
      // existing trip, so prefer it. Fallback is for the rare case
      // where the server sent a 409 with no body.
      return (
        detail ||
        "You've already uploaded this file. Delete the existing trip " +
        "from the trips page if you want to re-upload."
      );
    }
    if (status === 413) return detail || 'File is too large (over 100 MB).';
    if (status === 415) {
      return detail ||
        'Only CSV files are supported. The browser sent an unrecognized ' +
        'content type — try renaming the file to .csv and uploading again.';
    }
    if (status === 422) return detail || 'The CSV is malformed (header missing).';
    if (status === 429) return 'Too many requests — please wait a minute and retry.';
    if (status && status >= 500) return `Server error (${status}). Try again in a moment.`;
    if (anyE.code === 'ERR_NETWORK') return 'Network error. Check your connection.';
    if (anyE.message) return anyE.message;
  }
  return String(e);
}
