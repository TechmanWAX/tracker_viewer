import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { EmailNotVerifiedError, login, resendVerification } from '../api/auth';
import { useAuthStore } from '../store/authStore';

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  // When login fails with 403, we keep the typed email so the
  // "resend verification" button can reuse it.
  const [unverifiedEmail, setUnverifiedEmail] = useState<string | null>(null);
  const [resendStatus, setResendStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle');
  const [resendMessage, setResendMessage] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const setUser = useAuthStore((s) => s.setUser);
  const navigate = useNavigate();

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setUnverifiedEmail(null);
    setResendStatus('idle');
    setBusy(true);
    try {
      const user = await login(email, password);
      setUser(user);
      navigate('/trips', { replace: true });
    } catch (e: unknown) {
      if (e instanceof EmailNotVerifiedError) {
        setUnverifiedEmail(email);
        setError(e.message);
      } else {
        setError('Invalid email or password');
      }
    } finally {
      setBusy(false);
    }
  }

  async function onResend() {
    if (!unverifiedEmail) return;
    setResendStatus('sending');
    setResendMessage('');
    try {
      const r = await resendVerification(unverifiedEmail);
      setResendStatus('sent');
      setResendMessage(r.message);
    } catch (e) {
      setResendStatus('error');
      setResendMessage(String(e));
    }
  }

  return (
    <div style={{ maxWidth: 320, margin: '10vh auto', padding: 24, background: 'var(--bg-2)', borderRadius: 8 }}>
      <h1>Sign in</h1>
      <form onSubmit={submit} style={{ display: 'grid', gap: 12 }}>
        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
            style={{ width: '100%', padding: 8 }}
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="current-password"
            style={{ width: '100%', padding: 8 }}
          />
        </label>
        {error && (
          <div
            data-testid="login-error"
            role="alert"
            style={{ color: 'var(--danger)', fontSize: 13, lineHeight: 1.4 }}
          >
            {error}
            {unverifiedEmail && (
              <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
                <button
                  type="button"
                  onClick={onResend}
                  disabled={resendStatus === 'sending'}
                  aria-label="Resend verification email"
                >
                  {resendStatus === 'sending' ? 'Sending…' : 'Resend verification email'}
                </button>
              </div>
            )}
            {resendStatus === 'sent' && (
              <div style={{ marginTop: 6, color: 'var(--ok)' }} data-testid="resend-success">
                {resendMessage}
              </div>
            )}
            {resendStatus === 'error' && (
              <div style={{ marginTop: 6, color: 'var(--danger)' }}>{resendMessage}</div>
            )}
          </div>
        )}
        <button type="submit" disabled={busy} style={{ padding: 10 }}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
      <div style={{ marginTop: 16, fontSize: 13, opacity: 0.8 }}>
        Need an account? <Link to="/register">Sign up</Link>
      </div>
    </div>
  );
}
