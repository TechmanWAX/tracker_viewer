import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { EmailNotVerifiedError, login, resendVerification } from '../api/auth';
import { useAuthStore } from '../store/authStore';

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
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
    <div className="auth-page fade-in">
      <div className="card card-glass auth-card">
        <h1>Welcome back</h1>
        <p>Sign in to your account</p>
        <form onSubmit={submit}>
          <div>
            <label>Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              placeholder="you@example.com"
            />
          </div>
          <div>
            <label>Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              placeholder="••••••••"
            />
          </div>
          {error && (
            <div role="alert" style={{ color: 'var(--danger)', fontSize: 13, lineHeight: 1.4, padding: '8px 12px', background: 'var(--danger-soft)', borderRadius: 'var(--radius)' }}>
              {error}
              {unverifiedEmail && (
                <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
                  <button type="button" onClick={onResend} disabled={resendStatus === 'sending'} className="btn-sm" style={{ margin: 0 }}>
                    {resendStatus === 'sending' ? 'Sending…' : 'Resend verification email'}
                  </button>
                </div>
              )}
              {resendStatus === 'sent' && (
                <div style={{ marginTop: 6, color: 'var(--success)' }}>{resendMessage}</div>
              )}
              {resendStatus === 'error' && (
                <div style={{ marginTop: 6 }}>{resendMessage}</div>
              )}
            </div>
          )}
          <button type="submit" disabled={busy} className="btn-primary">
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
        <div className="auth-footer">
          Don't have an account? <Link to="/register">Sign up</Link>
        </div>
      </div>
    </div>
  );
}
