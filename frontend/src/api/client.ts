import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from 'axios';
import { getCsrfToken } from '../lib/csrf';

const baseURL = import.meta.env.VITE_API_BASE_URL || '';

export const api: AxiosInstance = axios.create({
  baseURL,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
});

/**
 * Custom event fired when refresh-token fails. A top-level <AuthBoundary>
 * component listens for it and navigates to /login via react-router, so we
 * avoid window.location.reload (which loses all client state).
 */
export const AUTH_EXPIRED_EVENT = 'gps:auth-expired';

let refreshing: Promise<void> | null = null;

async function refreshAccessToken(): Promise<void> {
  if (refreshing) return refreshing;
  refreshing = axios
    .post(`${baseURL}/auth/refresh`, {}, { withCredentials: true })
    .then(() => undefined)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const method = (config.method || 'get').toLowerCase();
  if (['post', 'put', 'patch', 'delete'].includes(method)) {
    const token = getCsrfToken();
    if (token) {
      config.headers.set('X-CSRF-Token', token);
    }
  }
  return config;
});

api.interceptors.response.use(
  (r) => r,
  async (err) => {
    const original = err.config as InternalAxiosRequestConfig & { _retry?: boolean };
    const status = err.response?.status;
    const url = original.url || '';
    const isAuthCall = url.includes('/auth/');

    if (status === 401 && !original._retry && !isAuthCall) {
      original._retry = true;
      try {
        await refreshAccessToken();
        return api(original);
      } catch {
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
        }
        return Promise.reject(err);
      }
    }

    if (status === 401 && isAuthCall) {
      if (typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
      }
    }

    return Promise.reject(err);
  }
);
