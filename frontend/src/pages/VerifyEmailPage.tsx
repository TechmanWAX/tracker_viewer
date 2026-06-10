import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { verifyEmail, type VerifyEmailErrorCode } from '../api/auth';

type Status = 'verifying' | 'success' | 'failed';

export default function VerifyEmailPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') ?? '';
  const consumedRef = useRef<boolean>(false);
  const [status, setStatus] = useState<Status>(token ? 'verifying' : 'failed');
  const [errorCode, setErrorCode] = useState<VerifyEmailErrorCode | null>(null);
  const [errorMessage, setErrorMessage] = useState<string>('');

  useEffect(() => {
    if (!token) {
      setStatus('failed');
      setErrorMessage('No verification token in the link. Please request a new one.');
      return;
    }
    if (consumedRef.current) return;
    consumedRef.current = true;
    verifyEmail(token)
      .then(() => setStatus('success'))
      .catch((e: unknown) => {
        setStatus('failed');
        const code = (e as { code?: string }).code as VerifyEmailErrorCode | undefined;
        setErrorCode(code ?? null);
        setErrorMessage((e as { message?: string }).message ?? 'Verification failed.');
      });
  }, [token]);

  return (
    <div className="auth-page fade-in">
      <div className="card card-glass auth-card" style={{ textAlign: 'center' }}>
        {status === 'verifying' && (
          <>
            <div style={{ fontSize: 36, marginBottom: 8 }}>⏳</div>
            <h1>Verifying your email…</h1>
            <p style={{ color: 'var(--fg-secondary)', fontSize: 14 }}>One moment.</p>
          </>
        )}
        {status === 'success' && (
          <>
            <div style={{ fontSize: 40, marginBottom: 8 }}>✅</div>
            <h1 style={{ color: 'var(--success)' }}>Email verified</h1>
            <p style={{ lineHeight: 1.5 }}>
              Your account is now active. You can sign in and start uploading trips.
            </p>
            <div style={{ marginTop: 16 }}>
              <Link to="/login" className="btn-primary" style={{ display: 'inline-flex', textDecoration: 'none' }}>
                Sign in
              </Link>
            </div>
          </>
        )}
        {status === 'failed' && (
          <>
            <div style={{ fontSize: 40, marginBottom: 8 }}>
              {errorCode === 'expired' ? '⏰' : errorCode === 'used' ? '🔗' : '⚠️'}
            </div>
            <h1 style={{ color: 'var(--danger)' }}>
              {errorCode === 'used' ? 'Already used' : errorCode === 'expired' ? 'Link expired' : 'Verification failed'}
            </h1>
            <p style={{ lineHeight: 1.5 }}>{errorMessage}</p>
            <div style={{ marginTop: 16, display: 'flex', gap: 8, justifyContent: 'center' }}>
              <Link to="/login"><button>Sign in</button></Link>
              <Link to="/register"><button>Register</button></Link>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
