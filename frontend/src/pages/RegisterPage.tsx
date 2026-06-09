import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
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
  else if (!USERNAME_RE.test(username))
    e.username = '3–50 chars: letters, digits, _ . -';

  if (!password) e.password = 'Password is required';
  else if (password.length < 8) e.password = 'Minimum 8 characters';
  else if (password.length > 128) e.password = 'Maximum 128 characters';

  if (confirm !== password) e.confirm = 'Passwords do not match';

  return e;
}

export default function RegisterPage() {
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState<FieldErrors>({});
  const [busy, setBusy] = useState(false);
  // We use the auth store only to make sure any stale session is
  // cleared — a freshly-registered user must NOT be logged in.
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
      // Belt-and-braces: drop any stale user from a prior session
      // so a hard refresh of this page doesn't briefly show the
      // nav bar for the wrong account.
      clearUser(null);
      // Don't auto-login. Hand the user off to the "check your
      // email" page; verification is required before they can sign
      // in. We pass the email via router state so the next page
      // can display it without re-asking.
      navigate('/check-email', {
        replace: true,
        state: {
          email: resp.user.email,
          // In dev the backend hands us the link so the user can
          // copy-paste it. We don't surface this in production.
          devVerificationUrl: resp.dev_verification_url,
        },
      });
    } catch (err: unknown) {
      const detail = extractDetail(err);
      if (/email/i.test(detail) && /already|exists|registered/i.test(detail)) {
        setErrors({ email: 'Email already registered' });
      } else if (/username/i.test(detail) && /already|taken|exists/i.test(detail)) {
        setErrors({ username: 'Username already taken' });
      } else {
        setErrors({ general: detail || 'Registration failed' });
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      style={{
        maxWidth: 360,
        margin: '6vh auto',
        padding: 24,
        background: 'var(--bg-2)',
        borderRadius: 8,
      }}
    >
      <h1 style={{ marginTop: 0 }}>Create account</h1>
      <form onSubmit={submit} style={{ display: 'grid', gap: 12 }} noValidate>
        <Field
          label="Email"
          type="email"
          value={email}
          onChange={setEmail}
          error={errors.email}
          autoComplete="email"
        />
        <Field
          label="Username"
          value={username}
          onChange={setUsername}
          error={errors.username}
          autoComplete="username"
        />
        <Field
          label="Password"
          type="password"
          value={password}
          onChange={setPassword}
          error={errors.password}
          autoComplete="new-password"
        />
        <Field
          label="Confirm password"
          type="password"
          value={confirm}
          onChange={setConfirm}
          error={errors.confirm}
          autoComplete="new-password"
        />
        {errors.general && (
          <div style={{ color: 'var(--danger)', fontSize: 13 }}>{errors.general}</div>
        )}
        <button type="submit" disabled={busy} style={{ padding: 10 }}>
          {busy ? 'Creating account…' : 'Create account'}
        </button>
      </form>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  type = 'text',
  error,
  autoComplete,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  error?: string;
  autoComplete?: string;
}) {
  return (
    <label style={{ display: 'grid', gap: 4 }}>
      <span style={{ fontSize: 12, opacity: 0.8 }}>{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required
        autoComplete={autoComplete}
        style={{
          width: '100%',
          padding: 8,
          background: 'var(--bg)',
          color: 'var(--fg)',
          border: `1px solid ${error ? 'var(--danger)' : '#333'}`,
          borderRadius: 4,
        }}
      />
      {error && <span style={{ color: 'var(--danger)', fontSize: 11 }}>{error}</span>}
    </label>
  );
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
