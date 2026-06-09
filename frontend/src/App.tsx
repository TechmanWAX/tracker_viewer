import { useEffect } from 'react';
import { Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import TripsListPage from './pages/TripsListPage';
import TripUploadPage from './pages/TripUploadPage';
import TripDetailPage from './pages/TripDetailPage';
import CheckEmailPage from './pages/CheckEmailPage';
import VerifyEmailPage from './pages/VerifyEmailPage';
import ProtectedRoute from './components/ProtectedRoute';
import { useAuthBootstrap } from './hooks/useAuth';
import { AUTH_EXPIRED_EVENT } from './api/client';
import { useAuthStore } from './store/authStore';

function AuthBoundary({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  const setUser = useAuthStore((s) => s.setUser);

  useEffect(() => {
    function onExpired() {
      setUser(null);
      navigate('/login', { replace: true });
    }
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired);
  }, [navigate, setUser]);

  return <>{children}</>;
}

export default function App() {
  useAuthBootstrap();

  return (
    <AuthBoundary>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        {/* Email verification flow. /check-email is the post-
            register "we sent you a link" page; /verify-email is
            the destination of the link itself. Both are public
            (no auth required). */}
        <Route path="/check-email" element={<CheckEmailPage />} />
        <Route path="/verify-email" element={<VerifyEmailPage />} />
        <Route
          path="/trips"
          element={
            <ProtectedRoute>
              <TripsListPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/trips/upload"
          element={
            <ProtectedRoute>
              <TripUploadPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/trips/:tripId"
          element={
            <ProtectedRoute>
              <TripDetailPage />
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<Navigate to="/trips" replace />} />
      </Routes>
    </AuthBoundary>
  );
}
