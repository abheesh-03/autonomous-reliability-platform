/**
 * Phase 14 Gate 5: mints the short-lived, signed service assertion
 * that carries the REAL authenticated actor's identity from this BFF
 * to control-plane/agent-runtime-service -- the ONLY mechanism either
 * backend trusts to learn "who is this" (Gate 5: "Never treat an
 * unsigned X-User-ID, X-Role, or X-Organization-ID header as trusted
 * authorization").
 *
 * Every call to `mintServiceAssertion` re-derives the actor from
 * scratch:
 *   1. `auth.api.getSession` -- the REAL, server-side-verified Better
 *      Auth session for this request (never a client-supplied claim).
 *   2. `auth.api.getActiveMember` -- a FRESH, live lookup of this
 *      user's membership/role in their currently active organization,
 *      straight from the database, on every single call. This is
 *      deliberately never cached across requests: a membership
 *      revoked or a role changed a moment ago must be reflected on
 *      the very next request (Gate 3: "membership revocation takes
 *      effect for subsequent requests").
 *
 * If either step fails to produce a real, current membership, this
 * returns `null` -- callers must treat that as "do not call the
 * downstream backend with any assertion at all", never substitute a
 * default organization or role.
 *
 * Signed with `jose` (already a dependency of better-auth itself, and
 * installed top-level here) -- HS256, a short (60s) expiry, and a
 * `aud` pinned to the specific downstream service this assertion is
 * for (Gate 5/6: an assertion minted for one backend must not be
 * replayable against a different one).
 */
import "server-only";

import { headers as nextHeaders } from "next/headers";
import { redirect } from "next/navigation";
import { SignJWT } from "jose";
import { APIError } from "better-auth";

import { auth } from "@/lib/auth/auth";

/**
 * Phase 14 correction round, BLOCKER 5 (found by the real revoked-
 * membership end-to-end check, scripts/verify-phase14-multitenant-security.sh):
 * `auth.api.getActiveMember` does NOT resolve to a falsy value when
 * the caller has no active-organization membership (e.g. a member
 * just removed by an owner, or a session with no active organization
 * at all) -- it THROWS a better-auth `APIError` (MEMBER_NOT_FOUND /
 * NO_ACTIVE_ORGANIZATION). `resolveActor`/`requireActorOrRedirect`
 * below must treat that exact, expected failure identically to "no
 * member" (never authenticate, never grant access) -- it is not a
 * real error to log or escalate, and letting it propagate uncaught
 * previously surfaced as an unhandled 500 instead of the intended
 * fail-closed `null`/redirect. Any OTHER, unexpected error is still
 * allowed to propagate -- this only narrows the one specific,
 * documented "no active member" outcome.
 */
async function getActiveMemberOrNull(
  requestHeaders: Headers,
): Promise<Awaited<ReturnType<typeof auth.api.getActiveMember>> | null> {
  try {
    return await auth.api.getActiveMember({ headers: requestHeaders });
  } catch (error) {
    if (error instanceof APIError && error.status === "BAD_REQUEST") {
      return null;
    }
    throw error;
  }
}

export type ServiceAssertionAudience = "control-plane" | "agent-runtime-service" | "investigator-service";

export interface VerifiedActor {
  userId: string;
  organizationId: string;
  role: string;
}

export interface SessionUser {
  userId: string;
  email: string;
  emailVerified: boolean;
}

// Phase 14 correction round, Issue 1: a defensive, belt-and-suspenders
// check that the organization id this module is about to sign into an
// assertion is actually UUID-shaped -- `advanced.database.generateId:
// "uuid"` (lib/auth/auth.ts) already guarantees this at the source, but
// this module never trusts a single layer alone for something this
// consequential: `reliability.incidents.organization_id` is a native
// Postgres UUID column, and a malformed value reaching
// control-plane/agent-runtime-service as a claim would be a confusing,
// hard-to-diagnose failure rather than a clear, immediate one.
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function assertUuidShaped(value: string, label: string): void {
  if (!UUID_PATTERN.test(value)) {
    throw new Error(`${label} is not a valid UUID (${value.length} chars) -- refusing to sign an assertion with it`);
  }
}

/**
 * Lightweight session read for cosmetic UI (Gate 9) that doesn't need
 * organization membership at all -- e.g. the unverified-email banner,
 * shown even before the user has selected/joined an organization.
 */
export async function getSessionUser(): Promise<SessionUser | null> {
  const requestHeaders = await nextHeaders();
  const session = await auth.api.getSession({ headers: requestHeaders });
  if (!session?.user) return null;
  return {
    userId: session.user.id,
    email: session.user.email,
    emailVerified: Boolean(session.user.emailVerified),
  };
}

function signingSecret(): Uint8Array {
  const raw = process.env.SERVICE_ASSERTION_SIGNING_SECRET;
  if (!raw || raw.trim() === "") {
    throw new Error("SERVICE_ASSERTION_SIGNING_SECRET is not configured");
  }
  return new TextEncoder().encode(raw);
}

/**
 * Resolves the real, current actor behind this request -- or `null`
 * if there is no valid session, no active organization selected, or
 * the live membership lookup finds none (e.g. a revoked member).
 * Exported separately from `mintServiceAssertion` so Server Components
 * can also use it directly to decide what to render (Gate 9), without
 * needing a signed token for their own use.
 */
export async function resolveActor(): Promise<VerifiedActor | null> {
  const requestHeaders = await nextHeaders();

  const session = await auth.api.getSession({ headers: requestHeaders });
  if (!session?.session?.activeOrganizationId || !session.user) {
    return null;
  }

  const member = await getActiveMemberOrNull(requestHeaders);
  if (!member) {
    // Gate 3: a revoked/removed member has no active Member row
    // anymore -- fails closed rather than falling back to any
    // previously-known role.
    return null;
  }

  return {
    userId: session.user.id,
    organizationId: session.session.activeOrganizationId,
    role: member.role,
  };
}

/**
 * Phase 14 Gate 9: the one helper every protected page/Route Handler
 * uses to establish "who is making this request" -- redirects to
 * `/sign-in` with no real session at all, or to `/organizations` with
 * a real session but no (or no longer valid) active organization
 * membership, rather than ever rendering a protected page for an
 * unresolved actor. This is a CONVENIENCE for the UI (Gate 9: "Do not
 * rely solely on Next.js middleware/proxy redirects") -- the actual
 * security boundary remains control-plane/agent-runtime-service
 * independently verifying the signed assertion this produces, not
 * this redirect.
 */
export async function requireActorOrRedirect(): Promise<VerifiedActor> {
  const requestHeaders = await nextHeaders();
  const session = await auth.api.getSession({ headers: requestHeaders });
  if (!session?.user) {
    redirect("/sign-in");
  }
  if (!session.session.activeOrganizationId) {
    redirect("/organizations");
  }
  const member = await getActiveMemberOrNull(requestHeaders);
  if (!member) {
    redirect("/organizations");
  }
  return {
    userId: session.user.id,
    organizationId: session.session.activeOrganizationId,
    role: member.role,
  };
}

export async function signAssertion(actor: VerifiedActor, audience: ServiceAssertionAudience): Promise<string> {
  assertUuidShaped(actor.organizationId, "actor.organizationId");
  return new SignJWT({ org: actor.organizationId, role: actor.role })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(actor.userId)
    .setIssuer(process.env.SERVICE_ASSERTION_ISSUER ?? "web-console")
    .setAudience(audience)
    .setIssuedAt()
    .setExpirationTime("60s")
    .sign(signingSecret());
}

/**
 * Same real actor resolution as requireActorOrRedirect, for Route
 * Handlers (which must return a JSON 401, never an HTML redirect, to
 * a `fetch()` caller) instead of Server Components.
 */
export async function requireActorOrUnauthorized(): Promise<
  { ok: true; actor: VerifiedActor } | { ok: false; response: Response }
> {
  const actor = await resolveActor();
  if (!actor) {
    return {
      ok: false,
      response: Response.json({ error: "unauthorized" }, { status: 401 }),
    };
  }
  return { ok: true, actor };
}

export async function mintServiceAssertion(
  audience: ServiceAssertionAudience,
): Promise<{ token: string; actor: VerifiedActor } | null> {
  const actor = await resolveActor();
  if (!actor) {
    return null;
  }
  return { token: await signAssertion(actor, audience), actor };
}
