import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router";

import { describeError, useLogin, useMe, useRegister } from "../api/queries";
import { AuthHero } from "../components/AuthHero";

export function RegisterPage() {
  const me = useMe();
  const register = useRegister();
  const login = useLogin();
  const navigate = useNavigate();
  const [form, setForm] = useState({ name: "", email: "", password: "", invite_code: "" });

  if (me.data) return <Navigate to="/" replace />;

  const set = (field: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [field]: e.target.value }));

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await register.mutateAsync(form);
      // Registering doesn't log in (the API keeps the two separate); do it for them.
      // The feed then forwards them to the profile form (no profile yet).
      await login.mutateAsync({ email: form.email, password: form.password });
      navigate("/", { replace: true });
    } catch {
      // Shown below from the mutation's error state.
    }
  }

  const error = register.error ?? login.error;
  const busy = register.isPending || login.isPending;

  return (
    <main className="auth-page">
      <AuthHero />
      <form onSubmit={onSubmit} className="card form">
        <h2>Create an account</h2>
        <label>
          Name
          <input autoComplete="name" required maxLength={100} value={form.name} onChange={set("name")} />
        </label>
        <label>
          Email
          <input type="email" autoComplete="email" required value={form.email} onChange={set("email")} />
        </label>
        <label>
          Password <span className="muted">(at least 8 characters)</span>
          <input
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            maxLength={128}
            value={form.password}
            onChange={set("password")}
          />
        </label>
        <label>
          Batch invite code
          <input autoComplete="off" required value={form.invite_code} onChange={set("invite_code")} />
        </label>
        {error && (
          <p className="error" role="alert">
            {describeError(error)}
          </p>
        )}
        <button type="submit" disabled={busy}>
          {busy ? "Creating…" : "Create account"}
        </button>
        <p className="muted">
          Already have an account? <Link to="/login">Log in</Link>
        </p>
      </form>
    </main>
  );
}
