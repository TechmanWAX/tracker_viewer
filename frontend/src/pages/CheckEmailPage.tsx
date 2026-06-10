import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { resendVerification } from '../api/auth';

const RESEND_COOLDOWN_S = 30;

export default function CheckEmailPage() {
  const location = useLocation();
  const state = location.state as { email?: string; devVerificationUrl?: string } | null;
  const email = state?.email ?? null;
  const devUrl = state?.devVerificationUrl ?? null;

  const [resendStatus, setResendStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle');
  const [resendMessage, setResendMessage] = useState<string>('');
  const [cooldown, setCooldown] = useState<number>(0);

  useEffect(() => {
    if (!email) return;
    const t = window.setInterval(() => {
      setCooldown((c) => Math.max(0, c - 1));
    }, 1000);
    return () => window.clearInterval(t);
  }, [email]);

  async function onResend() {
    if (!email) return;
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
    <div className="auth-page fade-in">
      <div className="card card-glass auth-card" style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 40, marginBottom: 12 }}>📧</div>
        <h1>Check your email</h1>
        {email ? (
          <p style={{ margin: '12px 0' }}>
            We sent a verification link to{' '}
            <strong style={{ color: 'var(--fg-primary)' }}>{email}</strong>
          </p>
        ) : (
          <p style={{ fontSize: 14, color: 'var(--fg-secondary)' }}>
            No email address provided. Please register again.
          </p>
        )}
        {devUrl && (
          <div style={{ margin: '10px 0', padding: 8, background: 'var(--bg-tertiary)', borderRadius: 'var(--radius-sm)', fontSize: 11, wordBreak: 'break-all' }}>
            <span style={{ opacity: 0.6 }}>Dev link: </span>
            <a href={devUrl}>{devUrl.slice(0, 60)}…</a>
          </div>
        )}
        <div style={{ marginTop: 18 }}>
          {cooldown > 0 ? (
            <button disabled style={{ margin: 0 }}>Resend in {cooldown}s</button>
          ) : (
            <button onClick={onResend} disabled={!email || resendStatus === 'sending'} style={{ margin: 0 }}>
              {resendStatus === 'sending' ? 'Sending…' : 'Resend'}
            </button>
          )}
        </div>
        {resendStatus === 'sent' && <div style={{ marginTop: 8, color: 'var(--success)', fontSize: 13 }}>{resendMessage}</div>}
        {resendStatus === 'error' && <div style={{ marginTop: 8, color: 'var(--danger)', fontSize: 13 }}>{resendMessage}</div>}
        <div className="auth-footer">
          <Link to="/login">Back to sign in</Link>
        </div>
      </div>
    </div>
  );
}
