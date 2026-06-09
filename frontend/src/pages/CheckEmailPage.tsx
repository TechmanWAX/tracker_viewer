import { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { resendVerification } from '../api/auth';

interface LocationState {
  email?: string;
  devVerificationUrl?: string;
}

const RESEND_COOLDOWN_S = 60;

export default function CheckEmailPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const state = (location.state ?? {}) as LocationState;
  const email = state.email ?? '';
  // Only present in dev (`MAIL_ENABLED=false` on the server).
  const devUrl = state.devVerificationUrl;

  const [resendStatus, setResendStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle');
  const [resendMessage, setResendMessage] = useState<string>('');
  const [cooldown, setCooldown] = useState<number>(0);

  // If the user lands here with no email in state, send them back
  // to the register page so they can re-fill the form.
  useEffect(() => {
    if (!email) {
      navigate('/register', { replace: true });
    }
  }, [email, navigate]);

  // Cooldown countdown for the "Resend" button. We use a local
  // interval so the disabled state and the label stay in sync.
  useEffect(() => {
    if (cooldown <= 0) return;
    const t = window.setInterval(() => {
      setCooldown((c) => (c > 0 ? c - 1 : 0));
    }, 1000);
    return () => window.clearInterval(t);
  }, [cooldown]);

  async function onResend() {
    if (cooldown > 0 || !email) return;
    setResendStatus('sending');
    setResendMessage('');
    try {
      const r = await resendVerification(email);
      setResendStatus('sent');
      setResendMessage(r.message);
      setCooldown(RESEND_COOLDOWN_S);
    } catch (e) {
      setResendStatus('error');
      setResendMessage(String(e));
    }
  }

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
      <h1 style={{ marginTop: 0 }}>Check your email</h1>
      <p style={{ lineHeight: 1.5 }}>
        We've sent a verification link to{' '}
        <strong data-testid="check-email-address">{email}</strong>. Click the
        link in that email to activate your account. The link expires in 30
        minutes and can only be used once.
      </p>
      <p style={{ lineHeight: 1.5, opacity: 0.8, fontSize: 13 }}>
        Can't find the email? Check your spam folder, or use the button below
        to send a fresh link.
      </p>

      {devUrl && (
        // Surface the link in dev only. The backend only includes
        // this field when MAIL_ENABLED=false on the server.
        <div
          data-testid="dev-verification-url"
          style={{
            margin: '12px 0',
            padding: 10,
            background: 'var(--bg)',
            border: '1px dashed #555',
            borderRadius: 4,
            fontSize: 12,
            wordBreak: 'break-all',
          }}
        >
          <div style={{ opacity: 0.7, marginBottom: 4 }}>Dev only — verification link:</div>
          <a href={devUrl} style={{ color: 'var(--accent)' }}>
            {devUrl}
          </a>
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, marginTop: 16, flexWrap: 'wrap' }}>
        <button
          onClick={onResend}
          disabled={cooldown > 0 || resendStatus === 'sending'}
          aria-label="Resend verification email"
        >
          {resendStatus === 'sending'
            ? 'Sending…'
            : cooldown > 0
              ? `Resend in ${cooldown}s`
              : 'Resend verification email'}
        </button>
        <Link to="/login">
          <button type="button" aria-label="Back to sign in">
            Back to sign in
          </button>
        </Link>
        <Link to="/register">
          <button type="button" aria-label="Use a different email">
            Use a different email
          </button>
        </Link>
      </div>

      {resendStatus === 'sent' && (
        <div
          role="status"
          data-testid="resend-success"
          style={{ marginTop: 12, fontSize: 13, color: 'var(--ok)' }}
        >
          {resendMessage}
        </div>
      )}
      {resendStatus === 'error' && (
        <div role="alert" style={{ marginTop: 12, fontSize: 13, color: 'var(--danger)' }}>
          {resendMessage || 'Could not resend. Please try again in a moment.'}
        </div>
      )}
    </div>
  );
}
