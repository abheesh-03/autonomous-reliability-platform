// Gate F support helpers, Phase 14 compatibility fix: establishes a
// REAL, legitimate, authenticated Better Auth session for the Phase 9
// browser workflow spec -- Phase 14 made every protected web-console
// page unconditionally require a real session
// (lib/server/actor.ts::requireActorOrRedirect), regardless of
// whether CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT ("secure mode",
// which governs BACKEND tenant enforcement) is on or off. This module
// never bypasses that check, mocks the backend, or hardcodes a
// browser-visible approval token -- it drives the exact same real
// Better Auth HTTP endpoints a real operator's browser would.
//
// TENANT FIXTURE DETAIL (the reason this file exists, not just a
// plain sign-up): the real incident this spec drives through is
// created by the EXISTING demo ingestion pipeline (a real controlled
// payment-authorization fault -> a real Prometheus alert -> a real
// Alertmanager webhook -> control-plane's own webhook handler), which
// -- Gate 6's own documented, deferred scope -- always assigns the
// resulting incident to the FIXED "legacy local-development
// organization" (database/migrations/V10__add_organization_scoping.sql's
// own backfill constant, mirrored here, never re-derived or guessed).
// A freshly, normally REGISTERED Better Auth organization gets its
// own newly generated UUID and would NOT own that incident at all.
// Making this spec's test actor a REAL, legitimate member of THAT
// SPECIFIC organization -- via a direct, explicit, TEST-ONLY SQL
// insert into Better Auth's own `auth.organization`/`auth.member`
// tables, using the SAME dedicated, least-privileged `web_console`
// role Better Auth's own real Pool connection uses (never the broad,
// shared POSTGRES_USER) -- is the correct, safe, tenant-bound fixture:
// it does not reassign any real/pre-existing incident, does not touch
// global production tenant rules, and does not disable the
// organization-ownership check anywhere. It simply makes a REAL test
// user a REAL, legitimate member of the SAME organization that ALREADY,
// legitimately owns the incident this spec's EXISTING fault-injection
// mechanism produces. This spec runs with control-plane in its
// legacy/default mode (CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT
// unset), matching its own pre-Phase-14 design -- the real,
// authoritative negative proof that a DIFFERENT tenant cannot access
// another organization's incident, WITH secure mode genuinely
// enabled, is scripts/verify-phase14-multitenant-security.sh and
// scripts/verify-retrieval-tenant-isolation.sh, run separately.
//
// Idempotent and safe to rerun: a fresh, unique test user is created
// on every run (so repeated CI runs never collide on a duplicate
// email), but the LEGACY organization row itself is only ever created
// once (ON CONFLICT DO NOTHING) -- never duplicated, never reset,
// never deleted. This never touches any OTHER organization or user a
// real developer or an earlier CI run may have created.

import { execFileSync } from "node:child_process";
import { Pool } from "pg";

// Mirrors control_plane.core.config's own
// LEGACY_LOCAL_DEVELOPMENT_ORGANIZATION_ID exactly -- the ONE fixed,
// documented constant every pre-Phase-14-style (ingestion-created)
// incident is actually assigned to. Never re-derived, never guessed.
export const LEGACY_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001";

const WEB_CONSOLE_BASE_URL = process.env.WEB_CONSOLE_URL ?? "http://127.0.0.1:3101";
// The real browser-facing trusted origin Better Auth's own
// trustedOrigins/CSRF check requires on every mutating request --
// mirrors lib/auth/auth.ts's own WEB_CONSOLE_TRUSTED_ORIGIN default
// exactly, never a value this test invents independently.
const TRUSTED_ORIGIN = process.env.WEB_CONSOLE_TRUSTED_ORIGIN ?? "http://127.0.0.1:3101";

function requiredEnv(name: string): string {
  const value = process.env[name];
  if (!value || value.trim() === "") {
    throw new Error(
      `${name} must be set in this test runner's own environment (.env) -- this Playwright spec needs it to ` +
        "establish a real test-only database connection as the dedicated, least-privileged web_console role, " +
        "exactly like lib/auth/auth.ts's own real Pool connection does.",
    );
  }
  return value;
}

// Connects as the SAME dedicated, least-privileged `web_console` role
// Better Auth's own real runtime Pool connection uses -- never the
// broad, shared POSTGRES_USER -- so this fixture setup is bound by
// the EXACT same real database privileges as the application itself,
// never a wider, test-only bypass. Runs on the HOST (this test runner
// is never containerized), so it connects via Postgres's own
// host-published port, mirroring the same host-vs-Compose-network
// boundary convention already established by e.g.
// test_remediation_transactions.py's own
// CONTROL_PLANE_TEST_POSTGRES_HOST.
function webConsoleDbPool(): Pool {
  return new Pool({
    host: process.env.POSTGRES_TEST_HOST ?? "127.0.0.1",
    port: Number(process.env.POSTGRES_PORT ?? 5432),
    user: "web_console",
    password: requiredEnv("WEB_CONSOLE_DB_PASSWORD"),
    database: requiredEnv("POSTGRES_DB"),
  });
}

export interface RealTestActor {
  userId: string;
  email: string;
  organizationId: string;
  /** The real, server-verified Better Auth session cookie header value for this actor. */
  cookieHeader: string;
}

/**
 * Ensures the fixed legacy organization row exists in Better Auth's
 * own `auth.organization` table (idempotent -- created at most once,
 * across however many times this spec or this helper is invoked
 * across CI runs against the same database; never recreated, never
 * reset, never deleted). This is the SAME organization real demo
 * ingestion already, legitimately assigns every alert-sourced
 * incident to -- this call never invents a new tenant boundary, it
 * only ensures the EXISTING one Gate 6's own documented scope already
 * names is addressable by Better Auth's own organization plugin too.
 */
async function ensureLegacyOrganizationExists(pool: Pool): Promise<void> {
  await pool.query(
    `INSERT INTO auth.organization (id, name, slug, "createdAt")
     VALUES ($1, 'Legacy Local-Development Organization', 'legacy-local-development', now())
     ON CONFLICT (id) DO NOTHING`,
    [LEGACY_ORGANIZATION_ID],
  );
}

/**
 * Marks a real, freshly signed-up user's email verified by extracting
 * the REAL, non-faked verification link Better Auth's own
 * sendVerificationEmail hook already writes to web-console's stdout
 * in local-development mode
 * (lib/auth/email-verification-delivery.ts -- "not emailed, logged
 * for local-dev/test visibility only") and fetching it -- mirrors
 * scripts/verify-phase14-multitenant-security.sh's own established
 * `verify_header` precedent exactly (the same log line, the same
 * mechanism), never a shortcut that bypasses the real verification
 * flow. Without this, the web console's own real "email not verified"
 * banner (also rendered with `role="status"`) would collide with this
 * spec's own status-polling locators -- an unverified test actor is
 * not a realistic stand-in for a real human operator either way.
 */
async function verifyRealEmail(email: string, cookieHeader: string): Promise<void> {
  const containerId = execFileSync("docker", [
    "ps",
    "--filter",
    "label=com.docker.compose.service=web-console",
    "--format",
    "{{.ID}}",
  ])
    .toString()
    .trim()
    .split("\n")[0];
  if (!containerId) {
    throw new Error("could not find the running web-console container to extract this test actor's real email verification link");
  }
  const logs = execFileSync("docker", ["logs", "--tail", "2000", containerId]).toString();
  const marker = `email verification link for ${email}`;
  const line = logs
    .split("\n")
    .reverse()
    .find((l) => l.includes(marker));
  if (!line) {
    throw new Error(`could not find web-console's real email verification link for ${email} in its logs`);
  }
  const match = line.match(/(https?:\/\/\S+)/);
  if (!match) {
    throw new Error(`found the verification log line for ${email} but could not extract a URL from it: ${line}`);
  }
  const verifyResponse = await fetch(match[1], { headers: { Cookie: cookieHeader } });
  if (verifyResponse.status !== 200) {
    throw new Error(`real email verification failed: HTTP ${verifyResponse.status}`);
  }
}

/**
 * Creates a REAL, fresh Better Auth user (via the real
 * `/api/auth/sign-up/email` endpoint -- real password hashing, real
 * session creation, nothing faked), then makes that EXACT user a
 * REAL, legitimate OWNER member of the fixed legacy organization via
 * a direct, explicit, TEST-ONLY `auth.member` insert (OWNER: the one
 * role that satisfies every role gate this workflow exercises --
 * ENGINEER-or-above to start/resume an investigation, OWNER/
 * INCIDENT_APPROVER to decide remediation -- a real human operator
 * driving this exact workflow would plausibly hold this role too).
 * Finally selects that organization as the session's real active one
 * via the real `/api/auth/organization/set-active` endpoint, so
 * `lib/server/actor.ts::resolveActor`'s own
 * `session.session.activeOrganizationId` check -- unmodified --
 * resolves correctly. Returns the real session cookie header value to
 * inject into the Playwright browser context; never a bypassed or
 * synthetic one.
 */
export async function createRealLegacyOrgActor(): Promise<RealTestActor> {
  const pool = webConsoleDbPool();
  try {
    await ensureLegacyOrganizationExists(pool);

    const uniqueSuffix = `${Date.now()}-${Math.floor(Math.random() * 1_000_000)}`;
    const email = `phase9-e2e-${uniqueSuffix}@example.com`;

    const signUpResponse = await fetch(`${WEB_CONSOLE_BASE_URL}/api/auth/sign-up/email`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Origin: TRUSTED_ORIGIN },
      body: JSON.stringify({ email, password: "correct-horse-battery-staple", name: "Phase 9 E2E Test Actor" }),
    });
    if (signUpResponse.status !== 200) {
      throw new Error(`real Better Auth sign-up failed: HTTP ${signUpResponse.status} (${await signUpResponse.text()})`);
    }
    const signUpBody = (await signUpResponse.json()) as { user: { id: string; email: string } };
    const userId = signUpBody.user.id;

    const setCookieHeader = signUpResponse.headers.get("set-cookie");
    if (!setCookieHeader) {
      throw new Error("real Better Auth sign-up did not return a session cookie");
    }
    // A real Set-Cookie header can carry multiple cookies separated by
    // commas within attributes (e.g. Expires) -- Better Auth's own
    // session cookie is the first `;`-delimited segment, which is all
    // a subsequent request's own Cookie header needs.
    const cookieHeader = setCookieHeader.split(";")[0];

    await verifyRealEmail(email, cookieHeader);

    await pool.query(
      `INSERT INTO auth.member (id, "organizationId", "userId", role, "createdAt")
       VALUES (gen_random_uuid(), $1, $2, 'OWNER', now())
       ON CONFLICT DO NOTHING`,
      [LEGACY_ORGANIZATION_ID, userId],
    );

    const setActiveResponse = await fetch(`${WEB_CONSOLE_BASE_URL}/api/auth/organization/set-active`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Origin: TRUSTED_ORIGIN, Cookie: cookieHeader },
      body: JSON.stringify({ organizationId: LEGACY_ORGANIZATION_ID }),
    });
    if (setActiveResponse.status !== 200) {
      throw new Error(
        `real Better Auth organization/set-active failed: HTTP ${setActiveResponse.status} (${await setActiveResponse.text()})`,
      );
    }

    return { userId, email, organizationId: LEGACY_ORGANIZATION_ID, cookieHeader };
  } finally {
    await pool.end();
  }
}

/**
 * Injects a real actor's own real session cookie into a Playwright
 * BrowserContext, so every subsequent `page.goto(...)` in that context
 * is a genuinely authenticated real browser request -- never a header
 * the real browser's own cookie jar wouldn't actually send.
 */
export async function signInBrowserContextAs(
  context: import("@playwright/test").BrowserContext,
  actor: RealTestActor,
): Promise<void> {
  const [name, ...rest] = actor.cookieHeader.split("=");
  const value = rest.join("=");
  const url = new URL(WEB_CONSOLE_BASE_URL);
  await context.addCookies([
    {
      name,
      value,
      domain: url.hostname,
      path: "/",
    },
  ]);
}
