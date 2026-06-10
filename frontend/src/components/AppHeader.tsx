import { Link, NavLink, useNavigate } from 'react-router-dom';
import { logout } from '../api/auth';
import { useAuthStore } from '../store/authStore';

type NavItem = { to: string; label: string; end?: boolean };

/**
 * Primary navigation. The order here drives the order in the top bar.
 *
 * `end: true` on `/trips` is important: without it, NavLink would treat
 * `/trips/upload` and `/trips/:id` as "on the Trips page" and highlight
 * the wrong tab. The upload link is left as `end: false` (the default)
 * so future sub-paths like `/trips/upload?foo=bar` keep working.
 */
const NAV_ITEMS: NavItem[] = [
  { to: '/trips', label: 'Trips', end: true },
  { to: '/trips/upload', label: 'Upload' },
];

export default function AppHeader() {
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const setAuthLoaded = useAuthStore((s) => s.setAuthLoaded);
  const navigate = useNavigate();

  async function onLogout() {
    try {
      await logout();
    } catch {
      // ignore — still clear local state
    }
    setUser(null);
    setAuthLoaded(true);
    navigate('/login', { replace: true });
  }

  return (
    <header
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '10px 16px',
        background: 'var(--bg-2)',
        borderBottom: '1px solid #000',
        flexWrap: 'wrap',
      }}
    >
      <Link
        to="/trips"
        style={{
          color: 'var(--fg)',
          textDecoration: 'none',
          fontWeight: 700,
          fontSize: 16,
        }}
      >
        GPS Trip Tracker
      </Link>
      <nav
        aria-label="Primary"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          marginLeft: 8,
          flexWrap: 'wrap',
        }}
      >
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              isActive ? 'app-nav-link app-nav-link--active' : 'app-nav-link'
            }
            style={{
              textDecoration: 'none',
              padding: '6px 10px',
              borderRadius: 4,
              fontSize: 14,
              // NavLink applies the `app-nav-link--active` className when
              // the route matches. Color/border is driven by CSS so we
              // get a real `:hover` for free without inline-style hacks.
            }}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
      <div style={{ flex: 1 }} />
      {user && (
        <span className="hide-mobile" style={{ fontSize: 12, opacity: 0.7 }}>
          {user.username} <span style={{ opacity: 0.5 }}>({user.email})</span>
        </span>
      )}
      <button onClick={onLogout} aria-label="Sign out">
        Sign out
      </button>
    </header>
  );
}
