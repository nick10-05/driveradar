import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";

import type { Schemas } from "../api/client";
import { describeError, useBranches, useMe, useSaveProfile } from "../api/queries";

type Profile = Schemas["ProfileOut"];

export function ProfilePage() {
  const me = useMe();
  const profile = me.data?.profile ?? null;
  // The mutation lives here, above the keyed form, so its "Saved" state survives the
  // remount that happens when the refetched profile arrives.
  const save = useSaveProfile();
  // Remount the form when the saved profile changes, so it starts from the new values.
  return <ProfileForm key={JSON.stringify(profile)} profile={profile} save={save} />;
}

/** Form fields are strings (what inputs hold); converted to numbers only on submit. */
function toFields(profile: Profile | null) {
  return {
    branch_code: profile?.branch_code ?? "",
    cgpa: profile ? String(profile.cgpa) : "",
    active_backlogs: profile ? String(profile.active_backlogs) : "0",
    grad_year: profile ? String(profile.grad_year) : "",
  };
}

type SaveMutation = ReturnType<typeof useSaveProfile>;

function ProfileForm({ profile, save }: { profile: Profile | null; save: SaveMutation }) {
  const branches = useBranches();
  const navigate = useNavigate();
  const [fields, setFields] = useState(() => toFields(profile));
  const firstTime = profile === null;

  const set = (field: keyof typeof fields) => (e: { target: { value: string } }) => {
    save.reset(); // hide a stale "Saved" / error once they edit again
    setFields((current) => ({ ...current, [field]: e.target.value }));
  };

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    save.mutate(
      {
        branch_code: fields.branch_code,
        // A JSON number; the server keeps it as an exact Decimal (no 7.1 → 7.0999…).
        cgpa: Number(fields.cgpa),
        active_backlogs: Number(fields.active_backlogs),
        grad_year: Number(fields.grad_year),
      },
      { onSuccess: () => firstTime && navigate("/", { replace: true }) },
    );
  }

  const thisYear = new Date().getFullYear();

  return (
    <section>
      <h1>Your profile</h1>
      {firstTime && (
        <p className="notice">
          Fill this in once to see which drives you're eligible for. Only the eligibility
          rules use it.
        </p>
      )}
      <form onSubmit={onSubmit} className="card form">
        <label>
          Branch
          <select required value={fields.branch_code} onChange={set("branch_code")}>
            <option value="" disabled>
              {branches.isPending ? "Loading…" : "Choose your branch"}
            </option>
            {branches.data?.map((b) => (
              <option key={b.code} value={b.code}>
                {b.name} ({b.code})
              </option>
            ))}
          </select>
        </label>
        {branches.isError && (
          <p className="error" role="alert">
            Couldn't load branches: {describeError(branches.error)}
          </p>
        )}
        <label>
          CGPA <span className="muted">(0–10)</span>
          <input
            type="number"
            inputMode="decimal"
            required
            min={0}
            max={10}
            step={0.01}
            value={fields.cgpa}
            onChange={set("cgpa")}
          />
        </label>
        <label>
          Active backlogs
          <input
            type="number"
            inputMode="numeric"
            required
            min={0}
            max={100}
            step={1}
            value={fields.active_backlogs}
            onChange={set("active_backlogs")}
          />
        </label>
        <label>
          Graduation year
          <input
            type="number"
            inputMode="numeric"
            required
            min={thisYear - 2}
            max={thisYear + 6}
            step={1}
            value={fields.grad_year}
            onChange={set("grad_year")}
          />
        </label>
        {save.isError && (
          <p className="error" role="alert">
            {describeError(save.error)}
          </p>
        )}
        {save.isSuccess && !firstTime && (
          <p className="success" role="status">
            Saved. Your feed is updated.
          </p>
        )}
        <button type="submit" disabled={save.isPending}>
          {save.isPending ? "Saving…" : firstTime ? "Save and see drives" : "Save"}
        </button>
      </form>
    </section>
  );
}
