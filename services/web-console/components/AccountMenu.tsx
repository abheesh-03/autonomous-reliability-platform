import Link from "next/link";

import { getSessionUser, resolveActor } from "../lib/server/actor";
import { SignOutButton } from "./auth/SignOutButton";
import { VerifyEmailBanner } from "./auth/VerifyEmailBanner";

/**
 * Phase 14 Gate 9: the account/session menu rendered on every page
 * (app/layout.tsx) -- shows the signed-in user's active
 * organization/role, or a sign-in/register link when there is no
 * session. Purely a DISPLAY convenience: it reads via resolveActor()
 * (the same real session+membership lookup every protected route
 * uses), never a separate, weaker check.
 */
export async function AccountMenu() {
  const [actor, sessionUser] = await Promise.all([resolveActor(), getSessionUser()]);

  return (
    <>
      <div
        style={{
          display: "flex",
          justifyContent: "flex-end",
          gap: "1rem",
          padding: "0.5rem 1.5rem",
          borderBottom: "1px solid var(--border)",
          fontSize: "0.9rem",
          color: "#9fb3c8",
        }}
      >
        {sessionUser ? (
          <>
            {actor && <span>Role: {actor.role}</span>}
            <Link href="/organizations">Organizations</Link>
            <SignOutButton />
          </>
        ) : (
          <>
            <Link href="/sign-in">Sign in</Link>
            <Link href="/register">Register</Link>
          </>
        )}
      </div>
      {/* Phase 14 correction round, Issue 5: shown regardless of
          whether an active organization is selected yet -- an
          unverified account must see this before it can even attempt
          to accept an invitation. */}
      {sessionUser && !sessionUser.emailVerified && <VerifyEmailBanner email={sessionUser.email} />}
    </>
  );
}
