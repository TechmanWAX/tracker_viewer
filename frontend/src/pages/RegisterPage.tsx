import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { register } from '../api/auth';
import { useAuthStore } from '../store/authStore';

interface FieldErrors {
  email?: string;
  username?: string;
  password?: string;
  confirm?: string;
  general?: string;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const USERNAME_RE = /^[a-zA-Z0-9_.-]{3,50}$/;

function validate(email: string, username: string, password: string, confirm: string): FieldErrors {
  const e: FieldErrors = {};
  if (!email) e.email = 'Email is required';
  else if (!EMAIL_RE.test(email)) e.email = 'Invalid email format';
  if (!username) e.username = 'Username is required';
  else if (!USERNAME_RE.test(username)) e.username = '3–50 chars: letters, digits, _ . -';
  if (!password) e.password = 'Password is required';
  else if (password.length < 8) e.password = 'Minimum 8 characters';
  else if (password.length > 128) e.password = 'Maximum 128 characters';
  if (confirm !== password) e.confirm = 'Passwords do not match';
  return e;
}

function extractDetail(err: unknown): string {
  if (typeof err === 'object' && err !== null) {
    const anyErr = err as { response?: { data?: { detail?: unknown } }; message?: string };
    const d = anyErr.response?.data?.detail;
    if (typeof d === 'string') return d;
    if (Array.isArray(d) && d.length > 0 && typeof d[0] === 'object' && d[0] !== null) {
      const first = d[0] as { msg?: string };
      if (typeof first.msg === 'string') return first.msg;
    }
    if (typeof anyErr.message === 'string') return anyErr.message;
  }
  return 'Registration failed';
}

export default function RegisterPage() {
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState<FieldErrors>({});
  const [busy, setBusy] = useState(false);
  const clearUser = useAuthStore((s) => s.setUser);
  const navigate = useNavigate();

  async function submit(e: FormEvent) {
    e.preventDefault();
    const v = validate(email, username, password, confirm);
    setErrors(v);
    if (Object.keys(v).length > 0) return;
    setBusy(true);
    try {
      const resp = await register({ email, username, password });
      clearUser(null);
      navigate('/check-email', { replace: true, state: { email, devVerificationUrl: resp.dev_verification_url } });
    } catch (e: unknown) {
      setErrors({ general: extractDetail(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-page fade-in">
      <div className="card card-glass auth-card">
        <h1>Create account</h1>
        <p>Start tracking your trips</p>
        <form onSubmit={submit} noValidate>
          <div>
            <label>Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              placeholder="you@example.com"
              style={{ borderColor: errors.email ? 'var(--danger)' : undefined }}
            />
            {errors.email && <span style={{ color: 'var(--danger)', fontSize: 11 }}>{errors.email}</span>}
          </div>
          <div>
            <label>Username</label>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoComplete="username"
              placeholder="username"
              style={{ borderColor: errors.username ? 'var(--danger)' : undefined }}
            />
            {errors.username && <span style={{ color: 'var(--danger)', fontSize: 11 }}>{errors.username}</span>}
          </div>
          <div>
            <label>Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="new-password"
              placeholder="••••••••"
              style={{ borderColor: errors.password ? 'var(--danger)' : undefined }}
            />
            {errors.password && <span style={{ color: 'var(--danger)', fontSize: 11 }}>{errors.password}</span>}
          </div>
          <div>
            <label>Confirm password</label>
            <input
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
              autoComplete="new-password"
              placeholder="••••••••"
              style={{ borderColor: errors.confirm ? 'var(--danger)' : undefined }}
            />
            {errors.confirm && <span style={{ color: 'var(--danger)', fontSize: 11 }}>{errors.confirm}</span>}
          </div>
          {errors.general && (
            <div style={{ color: 'var(--danger)', fontSize: 13, padding: '8px 12px', background: 'var(--danger-soft)', borderRadius: 'var(--radius)' }}>
              {errors.general}
            </div>
          )}
          <button type="submit" disabled={busy} className="btn-primary">
            {busy ? 'Creating account…' : 'Create account'}
          </button>
        </form>
        <div className="auth-footer">
          Already have an account? <Link to="/login">Sign in</Link>
        </div>
      </div>
    </div>
  );
}
