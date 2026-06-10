import { useState, useEffect, useCallback } from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { logout } from '../api/auth';
import { useAuthStore } from '../store/authStore';

type NavItem = { to: string; label: string; end?: boolean };

const NAV_ITEMS: NavItem[] = [
  { to: '/trips', label: 'Trips', end: true },
  { to: '/trips/upload', label: 'Upload' },
];

function getTheme(): 'light' | 'dark' {
  return document.documentElement.getAttribute('data-theme') as 'light' | 'dark' || 'light';
}

function setTheme(t: 'light' | 'dark') {
  document.documentElement.setAttribute('data-theme', t);
  localStorage.setItem('tracker-theme', t);
}

function toggleTheme() {
  setTheme(getTheme() === 'dark' ? 'light' : 'dark');
}

export default function AppHeader() {
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const setAuthLoaded = useAuthStore((s) => s.setAuthLoaded);
  const navigate = useNavigate();
  const [theme, setThemeState] = useState<'light' | 'dark'>(getTheme);

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => {
      if (!localStorage.getItem('tracker-theme')) {
        const t = mq.matches ? 'dark' : 'light';
        setTheme(t);
        setThemeState(t);
      }
    };
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  const onToggleTheme = useCallback(() => {
    toggleTheme();
    setThemeState(getTheme());
  }, []);

  async function onLogout() {
    try { await logout(); } catch { /* ignore */ }
    setUser(null);
    setAuthLoaded(true);
    navigate('/login', { replace: true });
  }

  return (
    <header
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '8px 18px',
        background: 'var(--glass-bg)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        borderBottom: '1px solid var(--glass-border)',
        position: 'sticky',
        top: 0,
        zIndex: 500,
      }}
    >
      <Link
        to="/trips"
        style={{
          color: 'var(--fg-primary)',
          fontSize: 16,
          fontWeight: 700,
          letterSpacing: '-0.01em',
          textDecoration: 'none',
        }}
      >
        GPS Trip Tracker
      </Link>

      <nav aria-label="Primary" style={{ display: 'flex', alignItems: 'center', gap: 2, marginLeft: 8 }}>
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `app-nav-link${isActive ? ' app-nav-link--active' : ''}`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div style={{ flex: 1 }} />

      {/* Theme toggle */}
      <button
        onClick={onToggleTheme}
        className="theme-toggle"
        aria-label="Toggle theme"
        title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
      >
        {theme === 'dark' ? '☀️' : '🌙'}
      </button>

      {user && (
        <span className="badge accent hide-mobile" style={{ fontSize: 12 }}>
          {user.username}
        </span>
      )}

      <button onClick={onLogout} aria-label="Sign out" className="btn-ghost btn-sm">
        Sign out
      </button>
    </header>
  );
}
