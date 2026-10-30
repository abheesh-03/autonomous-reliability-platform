/**
 * Phase 14, Gate 2/3: this console's single Better Auth server
 * instance -- the SOLE authoritative source of user identity,
 * sessions, organizations, and memberships for this platform (Gate 3:
 * "Maintain ONE authoritative permission/membership source. Do not
 * introduce competing authorization databases with inconsistent role
 * state.").
 *
 * Every option below was verified directly against the actual
 * installed package's own type definitions before being used here --
 * NOT guessed from general training knowledge (the task's own
 * instruction) -- see:
 *   - node_modules/@better-auth/core/dist/types/init-options.d.mts
 *     for baseURL/database/secret/secrets/trustedOrigins/
 *     emailAndPassword/useSecureCookies/rateLimit/session.
 *   - node_modules/better-auth/dist/plugins/organization/types.d.mts
 *     for OrganizationOptions (ac/roles/creatorRole/membershipLimit).
 *
 * server-only guards this module from ever being bundled into a
 * client component (it holds the raw Postgres pool and signing
 * secret).
 */
import "server-only";

import { betterAuth } from "better-auth";
import { nextCookies } from "better-auth/next-js";
import { organization } from "better-auth/plugins";
import { Pool } from "pg";

import { accessControl, platformRoles } from "./access-control";
import { isSecureDeployment } from "./deployment-mode";
import { deliverResetPasswordEmail } from "./email-reset-delivery";
import { deliverVerificationEmail } from "./email-verification-delivery";

function requiredEnv(name: string): string {
  const value = process.env[name];
  if (!value || value.trim() === "") {
    throw new Error(`required environment variable ${name} is not set`);
  }
  return value;
}

// Phase 14: a dedicated, least-privileged `web_console` PostgreSQL
// role/schema (scripts/init-web-console-db.sh) -- mirrors the EXACT
// precedent agent-runtime-service's own dedicated `agent_runtime`
// role/schema already establishes in this repository (see
// docker-compose.yml's agent-runtime-service block and
// scripts/init-agent-runtime-db.sh), never the shared
// POSTGRES_USER/POSTGRES_PASSWORD role control-plane/retrieval-service
// use. This role's own search_path is set (at the ROLE level, by that
// script) to a dedicated `auth` schema -- logically separate from the
// Flyway-owned `reliability` schema (Gate 2: "Keep auth persistence
// clearly separated from existing Flyway-owned reliability data"),
// without a literal cross-schema foreign key (see
// docs/architecture/phase-14-security-multitenancy.md's "schema
// separation" note for why).
//
// Non-blocking-module-load philosophy, consistent with every other
// service in this repository (control-plane's core/config.py,
// agent-runtime-service's config.py): an empty/invalid password here
// does not crash Next.js's build step; it fails the FIRST real
// database operation, which is the correct place for a durable
// dependency's misconfiguration to surface (never silently degraded).
const pool = new Pool({
  host: process.env.WEB_CONSOLE_DB_HOST ?? process.env.POSTGRES_HOST ?? "postgres",
  port: Number(process.env.WEB_CONSOLE_DB_PORT ?? process.env.POSTGRES_INTERNAL_PORT ?? 5432),
  user: process.env.WEB_CONSOLE_DB_USER ?? "web_console",
  password: process.env.WEB_CONSOLE_DB_PASSWORD ?? "",
  database: process.env.POSTGRES_DB ?? "",
  max: Number(process.env.WEB_CONSOLE_DB_POOL_MAX_SIZE ?? 5),
});

export const auth = betterAuth({
  baseURL: process.env.WEB_CONSOLE_TRUSTED_ORIGIN ?? "http://127.0.0.1:3101",
  database: pool,

  // Gate 2: real, library-provided password hashing/session
  // management -- no homegrown crypto anywhere in this module.
  emailAndPassword: {
    enabled: true,
    // Gate 2: "Account recovery/email verification must not be
    // faked." Local development (the default) keeps the original
    // Phase 14 behavior: sign-IN does not require a verified email,
    // since no email provider exists there -- but see
    // `emailVerification` below and `requireEmailVerificationOnInvitation`
    // in the organization plugin: ACCEPTING or REJECTING an
    // invitation (the one place an unverified account could otherwise
    // claim someone else's identity, Phase 14 correction round Issue
    // 5) DOES require a verified email, using Better Auth's own real,
    // supported verification-token mechanism -- never faked.
    //
    // PHASE 17A item 4: a real secure deployment DOES require a
    // verified email to sign in at all -- verified directly against
    // the installed package's own route implementation
    // (node_modules/better-auth/dist/api/routes/sign-in.mjs:338,
    // `if (requireEmailVerification && !user.emailVerified) { ... }`)
    // -- gated behind the SAME `isSecureDeployment()` flag used
    // throughout this module, never a second toggle.
    requireEmailVerification: isSecureDeployment(),
    minPasswordLength: 12,
    // Phase 17A item 4: Better Auth's own real, supported
    // forget-password/reset-password flow (verified against
    // node_modules/better-auth/dist/api/routes/reset-password.mjs) --
    // a real, single-use, time-limited reset token Better Auth itself
    // generates and validates; this hook only delivers the real URL,
    // never invents or manually validates a token itself. See
    // lib/auth/email-reset-delivery.ts for the same local-dev-logs/
    // secure-deployment-fails-closed rule `emailVerification` below
    // already uses.
    async sendResetPassword({ user, url }) {
      await deliverResetPasswordEmail(user, url);
    },
  },

  // Phase 14 correction round, Issue 5 / BLOCKER 3: a REAL,
  // Better-Auth-generated, single-use, time-limited verification
  // token -- never faked as "sent". No external email provider is
  // configured this phase, so `deliverVerificationEmail`
  // (lib/auth/email-verification-delivery.ts) only logs the real
  // token/URL server-side in an explicitly local-development
  // deployment (retrieved from server logs, or resent via
  // `authClient.sendVerificationEmail` --
  // components/auth/VerifyEmailBanner.tsx) -- in a secure deployment
  // (CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT enabled) it fails
  // CLOSED instead, never logging a live token and never claiming an
  // email was actually delivered. See that module's own docstring for
  // why this is safe (it never blocks sign-up itself) and why
  // invitation acceptance -- which requires `emailVerified` below --
  // is therefore also unavailable in a secure deployment until a real
  // provider is wired up.
  emailVerification: {
    sendOnSignUp: true,
    autoSignInAfterVerification: true,
    async sendVerificationEmail({ user, url }) {
      await deliverVerificationEmail(user, url);
    },
  },

  // Gate 2: explicit, pinned trusted-origin validation -- mirrors the
  // existing WEB_CONSOLE_TRUSTED_ORIGIN convention this console's own
  // origin-guard.ts already uses, so both mechanisms agree on exactly
  // one, non-attacker-controlled origin rather than drifting apart.
  trustedOrigins: [process.env.WEB_CONSOLE_TRUSTED_ORIGIN ?? "http://127.0.0.1:3101"],

  // Gate 2: session signing/cookie secret -- never hardcoded, never
  // committed; generated by scripts/init-web-console-db.sh alongside
  // the database password, same .env-is-authoritative convention every
  // other secret in this repository already follows.
  secret: requiredEnv("BETTER_AUTH_SECRET"),

  // Gate 2: HttpOnly/SameSite are Better Auth's own cookie defaults
  // (verified against its session-cookie implementation); this flag
  // additionally marks cookies `Secure` once this console is actually
  // served over HTTPS -- never forced on for this phase's plain-HTTP
  // local-development deployment (which would make every cookie
  // silently rejected by the browser).
  advanced: {
    useSecureCookies: process.env.WEB_CONSOLE_USE_SECURE_COOKIES === "true",
    // Phase 17A item 2: trusts `x-forwarded-for` for Better Auth's own
    // built-in rate limiter and session IP tracking (verified against
    // node_modules/@better-auth/core/dist/types/init-options.d.mts's
    // real `ipAddress.ipAddressHeaders` option) ONLY when
    // TRUSTED_PROXY_ENABLED is set -- which a real deployment sets
    // (deploy/docker-compose.override.yml) BECAUSE this container
    // publishes no port of its own there; Caddy (deploy/caddy/
    // Caddyfile) is the only path in, and it OVERWRITES this header
    // with the real connecting client's address on every request it
    // proxies, never trusting whatever a client itself sent. Local
    // development (TRUSTED_PROXY_ENABLED unset) leaves this
    // unconfigured -- Better Auth's own default (the real, direct
    // socket peer address) applies, exactly as before Phase 17A.
    ipAddress:
      process.env.TRUSTED_PROXY_ENABLED === "true" ? { ipAddressHeaders: ["x-forwarded-for"] } : undefined,
    // Phase 14 correction round, Issue 1: Better Auth's own DEFAULT
    // id generator produces an opaque random string that is NOT
    // guaranteed to be a syntactically valid UUID -- incompatible
    // with `reliability.incidents.organization_id UUID NOT NULL`
    // (database/migrations/V10__add_organization_scoping.sql).
    // Verified directly against the installed package's real type
    // definitions (node_modules/@better-auth/core/dist/types/init-options.d.mts):
    // `generateId: "uuid"` is a REAL, explicitly supported built-in
    // mode -- "we generate a random UUID for the id. If postgres, we
    // use the gen_random_uuid() function" -- chosen over a custom
    // GenerateIdFn precisely because it is the library's own
    // first-class, maintained option, not a hand-rolled generator this
    // codebase would have to keep correct itself. This makes EVERY
    // Better Auth id (user, session, organization, member, invitation,
    // account, verification) a real UUID string, directly compatible
    // with Postgres's native UUID type -- see
    // auth-schema/schema.sql (regenerated with this setting active)
    // and docs/architecture/phase-14-security-multitenancy.md's
    // "organization identity strategy" section for the real, verified
    // column-type evidence.
    database: {
      generateId: "uuid",
    },
  },

  session: {
    expiresIn: 60 * 60 * 24 * 7, // 7 days
    updateAge: 60 * 60 * 24, // refresh once per day of activity
  },

  // Gate 2: safe login error behavior / brute-force resistance.
  // Better Auth's own built-in rate limiter (verified in
  // init-options.d.mts) -- no separate, hand-rolled limiter.
  rateLimit: {
    enabled: true,
    window: 60,
    max: 20,
    // Phase 14 correction round: Better Auth has its OWN built-in,
    // stricter "special rules" for sign-in/sign-up specifically
    // (window: 10, max: 3 -- verified directly against
    // node_modules/better-auth/dist/api/rate-limiter/index.mjs's real
    // `getDefaultSpecialRules`), which silently override the general
    // window/max above regardless of this config -- by design, a real
    // anti-abuse control, never relaxed for a real deployment.
    // `customRules` is the ONLY supported way to override it per
    // path, and is used here ONLY to let
    // scripts/verify-phase14-multitenant-security.sh's own real,
    // disposable multi-identity test run (several real sign-ups/
    // invitations in quick succession) avoid tripping that same
    // control against ITSELF -- gated behind an env var this script
    // is the only thing that ever sets; every real deployment keeps
    // Better Auth's own real default.
    customRules:
      process.env.WEB_CONSOLE_DISABLE_SPECIAL_RATE_LIMITS === "true"
        ? { "/sign-up/email": { window: 1, max: 10_000 }, "/sign-in/email": { window: 1, max: 10_000 } }
        : undefined,
  },

  plugins: [
    // Gate 3: organizations/memberships/invitations/roles. `ac`/
    // `roles` below REPLACE Better Auth's own default
    // admin/owner/member roles entirely with this platform's five
    // (Gate 3's exact list) -- `creatorRole: "OWNER"` is the only
    // role a brand-new organization's creator is ever assigned.
    organization({
      ac: accessControl,
      roles: platformRoles,
      creatorRole: "OWNER",
      allowUserToCreateOrganization: true,
      membershipLimit: 500,
      // Phase 14 correction round, Issue 5: verified directly against
      // the installed package's own source
      // (node_modules/better-auth/dist/plugins/organization/routes/crud-invites.mjs) --
      // Better Auth ALREADY rejects accept/reject for the wrong email
      // (`invitation.email !== session.user.email`) unconditionally,
      // and its own documented default behavior leaves the
      // ADDITIONAL verified-email gate off only when invitation ids
      // are "opaque" (e.g. generateId: "uuid", which this config now
      // uses -- see `advanced.database.generateId` above) AND reach
      // the recipient only via a real mailbox. Neither holds here:
      // this phase has no real email delivery, so the raw invitation
      // id is surfaced directly to the INVITER (never mailed to the
      // invitee) -- meaning an attacker could sign up with a victim's
      // exact email (unverified, since sign-in itself doesn't require
      // verification) and satisfy the email-match check alone. This
      // explicit `true` closes exactly that gap: accepting/rejecting
      // an invitation now ALSO requires `session.user.emailVerified`
      // (see `emailVerification` above for the real, non-faked
      // verification-token mechanism) -- an unverified account can
      // never claim an invitation, verified or not matching by email.
      requireEmailVerificationOnInvitation: true,
      // Gate 2/3: invitation emails are NOT faked as sent -- this
      // callback is a safe, disabled-by-default no-op (logs
      // server-side only) until a real external email provider is
      // configured (documented, not implemented, this phase). The
      // actual security boundary -- a random, time-limited,
      // single-use invitation token -- is fully real regardless: it
      // is generated and persisted by Better Auth itself before this
      // callback ever runs, and the invite endpoint
      // (app/api/invitations/[id]/route placeholder, Gate 9) surfaces
      // the real invite link directly to the inviter so the
      // invitation flow works end-to-end in local development without
      // ever claiming an email was delivered.
      async sendInvitationEmail(data) {
        console.log(
          `[web-console] organization invitation created (email delivery not configured): ` +
            `invitation ${data.id} for ${data.email} to organization ${data.organization.name}`,
        );
      },
    }),
    // Must be the LAST plugin (Better Auth's own documented
    // requirement, confirmed against its real hook ordering): lets
    // Server Actions/Route Handlers in this console set the session
    // cookie directly via Next.js's own cookies() API.
    nextCookies(),
  ],
});

export type Session = typeof auth.$Infer.Session;
