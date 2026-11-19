import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router";

import { describeError, useLogin, useMe } from "../api/queries";
import { safeRedirect } from "../auth/RequireAuth";

export function LoginPage() {
  const me = useMe();
  const login = useLogin();
  const navigate = useNavigate();
  const location = useLocation();
  const target = safeRedirect((location.state as { from?: unknown } | null)?.from);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  if (me.data) return <Navigate to={target} replace />;

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    login.mutate({ email, password }, { onSuccess: () => navigate(target, { replace: true }) });
  }

  return (
    <main className="auth-page">
      <h1>DriveRadar</h1>
      <p className="muted">Placement drives for your batch, filtered for you.</p>
      <form onSubmit={onSubmit} className="card form">
        <h2>Log in</h2>
        <label>
          Email
          <input
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>
        <label>
          Password
          <input
            type="password"
            autoComplete="current-password"
            required
            maxLength={128}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {login.isError && (
          <p className="error" role="alert">
            {describeError(login.error)}
          </p>
        )}
        <button type="submit" disabled={login.isPending}>
          {login.isPending ? "Logging in…" : "Log in"}
        </button>
        <p className="muted">
          New here? <Link to="/register">Create an account</Link> with your batch invite code.
        </p>
      </form>
    </main>
  );
}
