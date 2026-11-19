import { NavLink, Outlet, useNavigate } from "react-router";

import { useLogout, useMe } from "../api/queries";

export function Layout() {
  const me = useMe();
  const logout = useLogout();
  const navigate = useNavigate();

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
          <NavLink to="/profile">Profile</NavLink>
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
      <main>
        <Outlet />
      </main>
    </div>
  );
}
