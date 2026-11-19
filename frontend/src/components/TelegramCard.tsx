/**
 * "Telegram alerts" on the profile page: connect via a one-time deep link, or disconnect.
 *
 * Two steps on purpose: "Connect" asks the server for a link, then "Open Telegram" is a
 * real <a>. Opening a window after an await is blocked as a popup by most browsers, and on
 * a phone the link opens the Telegram app directly.
 *
 * The chat gets linked on the server when the student presses Start in Telegram, which
 * this page can't see. So while a link is pending we poll /me every few seconds; it stops
 * when the link is used or expires.
 */
import { useEffect, useState } from "react";

import type { Schemas } from "../api/client";
import { describeError, useDisconnectTelegram, useMe, useTelegramLink } from "../api/queries";
import { formatDeadlineIST } from "../lib/format";

const POLL_MS = 4_000;

export function TelegramCard({ linked }: { linked: boolean }) {
  const create = useTelegramLink();
  const disconnect = useDisconnectTelegram();
  const link: Schemas["TelegramLinkOut"] | undefined = linked ? undefined : create.data;
  const pending = useIsBefore(link?.expires_at);
  useMe({ refetchInterval: pending ? POLL_MS : false });

  return (
    <section className="card">
      <h2>Telegram alerts</h2>
      {linked ? (
        <>
          <p className="success">Connected. You'll get a message when a drive you're eligible for is published.</p>
          {disconnect.isError && (
            <p className="error" role="alert">
              {describeError(disconnect.error)}
            </p>
          )}
          <button
            type="button"
            className="secondary"
            disabled={disconnect.isPending}
            onClick={() => {
              create.reset();
              disconnect.mutate();
            }}
          >
            {disconnect.isPending ? "Disconnecting…" : "Disconnect Telegram"}
          </button>
        </>
      ) : link && pending ? (
        <>
          <p>
            Open Telegram and press <strong>Start</strong>. This link works once, until{" "}
            {formatDeadlineIST(link.expires_at)}.
          </p>
          <p className="actions">
            <a className="button" href={link.url} target="_blank" rel="noopener noreferrer">
              Open Telegram
            </a>
          </p>
          <p className="muted" role="status">
            Waiting for you to press Start…
          </p>
        </>
      ) : (
        <>
          <p>Get a Telegram message when a drive you're eligible for is published.</p>
          {link && !pending && <p className="muted">That link expired. Get a new one.</p>}
          {create.isError && (
            <p className="error" role="alert">
              {describeError(create.error)}
            </p>
          )}
          <button type="button" disabled={create.isPending} onClick={() => create.mutate()}>
            {create.isPending ? "Getting a link…" : "Connect Telegram"}
          </button>
        </>
      )}
    </section>
  );
}

/** True until the time `iso` passes (a timer flips it), false when there is no `iso`. */
function useIsBefore(iso: string | undefined): boolean {
  const [passed, setPassed] = useState<string | null>(null);
  useEffect(() => {
    if (!iso) return;
    const ms = Math.max(0, new Date(iso).getTime() - Date.now());
    const timer = setTimeout(() => setPassed(iso), ms);
    return () => clearTimeout(timer);
  }, [iso]);
  return iso !== undefined && passed !== iso;
}
