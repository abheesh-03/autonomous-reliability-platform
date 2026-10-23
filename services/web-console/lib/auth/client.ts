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

export const authClient = createAuthClient({
  baseURL: process.env.NEXT_PUBLIC_WEB_CONSOLE_ORIGIN ?? "http://127.0.0.1:3101",
  plugins: [organizationClient()],
});

export const { useSession, signIn, signUp, signOut, organization } = authClient;
