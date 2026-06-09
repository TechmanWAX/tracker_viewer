import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { verifyEmail, type VerifyEmailErrorCode } from '../api/auth';

type Status = 'verifying' | 'success' | 'failed';

export default function VerifyEmailPage() {
  const [searchParams] = useSearchParams();
  // The link from the email looks like
  // `/verify-email?token=<raw>`. We pull the token out of the
  // query string and call the backend exactly once.
  const token = searchParams.get('token') ?? '';
  // Ref-guard against React 18 StrictMode double-invoking effects
  // in dev. The token is single-use — we don't want to consume
  // it twice because the dev server re-runs effects.
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
      .then(() => {
        setStatus('success');
      })
      .catch((e: unknown) => {
        setStatus('failed');
        const code = (e as { code?: string }).code as VerifyEmailErrorCode | undefined;
        setErrorCode(code ?? null);
        setErrorMessage(
          (e as { message?: string }).message ?? 'Verification failed.',
        );
      });
  }, [token]);

  return (
    <div
      style={{
        maxWidth: 480,
        margin: '6vh auto',
        padding: 24,
        background: 'var(--bg-2)',
        borderRadius: 8,
      }}
    >
      {status === 'verifying' && (
        <>
          <h1 style={{ marginTop: 0 }}>Verifying your email…</h1>
          <p style={{ opacity: 0.7 }}>One moment.</p>
        </>
      )}

      {status === 'success' && (
        <>
          <h1 style={{ marginTop: 0, color: 'var(--ok)' }}>Email verified</h1>
          <p style={{ lineHeight: 1.5 }}>
            Your account is now active. You can sign in and start uploading
            trips.
          </p>
          <div style={{ marginTop: 16 }}>
            <Link to="/login">
              <button>Sign in</button>
            </Link>
          </div>
        </>
      )}

      {status === 'failed' && (
        <>
          <h1 style={{ marginTop: 0, color: 'var(--danger)' }}>
            {errorCode === 'used'
              ? 'This link has already been used'
              : errorCode === 'expired'
                ? 'This link has expired'
                : 'Verification failed'}
          </h1>
          <p style={{ lineHeight: 1.5 }}>{errorMessage}</p>
          <p style={{ lineHeight: 1.5, opacity: 0.8, fontSize: 13 }}>
            {errorCode === 'expired' || errorCode === 'used' || !errorCode ? (
              <>
                You can request a new link from the sign-in page.
              </>
            ) : null}
          </p>
          <div style={{ marginTop: 16, display: 'flex', gap: 8 }}>
            <Link to="/login">
              <button>Go to sign in</button>
            </Link>
            <Link to="/register">
              <button>Create a new account</button>
            </Link>
          </div>
        </>
      )}
    </div>
  );
}
