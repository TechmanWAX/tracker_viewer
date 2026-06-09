import { Navigate, useLocation } from 'react-router-dom';
import type { ReactNode } from 'react';
import { useAuthStore } from '../store/authStore';

export default function ProtectedRoute({ children }: { children: ReactNode }) {
  const user = useAuthStore((s) => s.user);
  const authLoaded = useAuthStore((s) => s.authLoaded);
  const location = useLocation();

  if (!authLoaded) {
    return (
      <div style={{ padding: 24, opacity: 0.6, fontSize: 13 }}>
        Loading…
      </div>
    );
  }
  if (user === null) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}
