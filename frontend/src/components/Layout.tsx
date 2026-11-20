import { NavLink, Outlet, useLocation, useNavigate } from "react-router";

import { useLogout, useMe } from "../api/queries";

export function Layout() {
  const me = useMe();
  const logout = useLogout();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const isAdmin = me.data?.role === "admin";

  return (
    <div className="app">
      <header className="topbar">
        <NavLink to="/" className="brand">
          DriveRadar
        </NavLink>
        <nav>
          <NavLink to="/" end>
            Drives
          </NavLink>
          <NavLink to="/tracker">Tracker</NavLink>
          <NavLink to="/profile">Profile</NavLink>
          {isAdmin && <NavLink to="/admin">Admin</NavLink>}
          <button
            type="button"
            className="link-button"
            disabled={logout.isPending}
            onClick={() => logout.mutate(undefined, { onSettled: () => navigate("/login") })}
          >
            Log out
          </button>
        </nav>
      </header>
      {me.data && <p className="greeting">Hi, {me.data.name}</p>}
      {/* Keyed by path: each route remounts and plays the CSS page-in animation. */}
      <main key={pathname} className="page">
        <Outlet />
      </main>
    </div>
  );
}
