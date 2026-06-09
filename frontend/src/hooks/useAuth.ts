import { useEffect } from 'react';
import { useAuthStore } from '../store/authStore';
import { me } from '../api/auth';

export function useAuthBootstrap() {
  const setUser = useAuthStore((s) => s.setUser);
  const setAuthLoaded = useAuthStore((s) => s.setAuthLoaded);

  useEffect(() => {
    let cancelled = false;
    // Skip the bootstrap fetch entirely if we know there's no
    // session. This avoids emitting a 401 → AUTH_EXPIRED_EVENT on
    // every public-page load (e.g. /login, /register, /verify-email),
    // which used to bounce users to /login even on a fresh visit
    // to a public route. The auth interceptor dispatches
    // AUTH_EXPIRED_EVENT for *any* /auth/* 401, including the
    // initial /me probe, so the cheapest fix is to not probe at
    // all when we know we're not logged in.
    const hasAccessToken = document.cookie
      .split(';')
      .map((s) => s.trim())
      .some((c) => c.startsWith('access_token='));
    if (!hasAccessToken) {
      setUser(null);
      setAuthLoaded(true);
      return;
    }
    me()
      .then((user) => {
        if (!cancelled) setUser(user);
      })
      .catch(() => {
        if (!cancelled) setUser(null);
      })
      .finally(() => {
        if (!cancelled) setAuthLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [setUser, setAuthLoaded]);
}
