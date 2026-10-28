/**
 * Phase 14 Gate 9: the browser-side Better Auth client -- used only
 * by Client Components (sign-in/register forms, org switcher,
 * members/invitations UI) for sign-in/sign-up/sign-out and reading
 * the current session/organization client-side. Every value this
 * returns is for DISPLAY/UX only (Gate 9: "backend authorization must
 * independently reject it" regardless of what the client believes) --
 * no Server Component, Route Handler, or BFF call ever trusts
 * anything from this module as authorization; they always call
 * `auth.api.getSession(...)` server-side (lib/auth/auth.ts) instead.
 */
"use client";

import { createAuthClient } from "better-auth/react";
import { organizationClient } from "better-auth/client/plugins";

// Independent-review correction round: `baseURL` is deliberately NOT a
// hardcoded host like "http://127.0.0.1:3101" (what this previously
// was). That value gets baked into the client JS bundle at BUILD time,
// so any user who reaches this app through a DIFFERENT hostname that
// also resolves to the same server -- "localhost" vs. "127.0.0.1" are
// the textbook example, since browsers treat them as different origins
// even though they're the same machine -- ends up with every
// authClient call (sign-up, sign-in, ...) silently going cross-origin.
// Without a matching CORS allowlist entry, the browser blocks the
// response entirely and `fetch()` throws; this was the real cause of a
// user-reported sign-up button that spun forever (see
// components/auth/RegisterForm.tsx's own fix for the other half of
// that bug: the thrown exception was never caught).
//
// Omitting `baseURL` here lets Better Auth's own client resolve it to
// the relative path "/api/auth" (see its getClientConfig/getBaseURL),
// which the browser's fetch() always resolves against the CURRENT
// page's own origin -- correct no matter which hostname/domain was
// actually used to reach this app. `NEXT_PUBLIC_WEB_CONSOLE_ORIGIN`
// remains available as an explicit override for a deployment that
// genuinely needs one (e.g. behind a reverse proxy on a different
// public hostname than the one the Next.js server itself sees).
export const authClient = createAuthClient({
  baseURL: process.env.NEXT_PUBLIC_WEB_CONSOLE_ORIGIN,
  plugins: [organizationClient()],
});

export const { useSession, signIn, signUp, signOut, organization } = authClient;
