/**
 * Phase 14 correction round, BLOCKER 3: "sendVerificationEmail
 * currently prints a live email-verification URL into server logs...
 * useful as a local test fixture but... not a real mailbox-ownership
 * verification mechanism... must not be enabled for real multi-user
 * production deployments."
 *
 * No external email provider is configured or referenced anywhere in
 * this repository (no SMTP/Resend/SendGrid dependency or credential
 * in package.json or .env.example) -- so this implements option (B)
 * from the correction round's own spec: the log-URL fallback stays
 * STRICTLY local-development-only, and every other deployment fails
 * CLOSED (throws before logging anything, never a faked "sent")
 * rather than printing a live, usable verification token nobody but
 * this server's own log stream could ever see.
 *
 * "Secure deployment" is read from CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT
 * -- the SAME explicit flag control-plane's OrganizationContextSettings
 * and agent-runtime-service's own mirror of it already use to
 * distinguish a real, tenant-isolated deployment from local
 * development (see those services' core/config.py / config.py) --
 * never a second, independently-drifting flag.
 */
import "server-only";

function isSecureDeployment(): boolean {
  const raw = (process.env.CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT ?? "").trim().toLowerCase();
  return raw === "1" || raw === "true" || raw === "yes" || raw === "on";
}

/**
 * Thrown when a secure deployment has no real email-delivery
 * mechanism configured. Better Auth's own sendVerificationEmail hook
 * is invoked through `runInBackgroundOrAwait` (verified directly
 * against node_modules/better-auth/dist/context/create-context.mjs),
 * which awaits this callback and only LOGS any exception it throws --
 * it never propagates the error back to the sign-up/resend caller and
 * never blocks account creation. Throwing here is therefore safe: it
 * ensures the verification-email dispatch fails loudly (a real server
 * error, naming no secret) instead of silently logging a live,
 * single-use verification token.
 */
export class VerificationEmailNotConfiguredError extends Error {
  constructor() {
    super(
      "cannot deliver a real verification email: no email-delivery provider is configured for this " +
        "secure deployment (CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT is enabled) -- email-" +
        "verification-dependent flows, including organization invitation acceptance, are unavailable " +
        "until a real provider is wired up",
    );
    this.name = "VerificationEmailNotConfiguredError";
  }
}

/**
 * The real implementation behind `auth.ts`'s `emailVerification.sendVerificationEmail`
 * hook. In local development (the default -- CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT
 * unset/false) this keeps the existing, already-reviewed behavior:
 * log the real, Better-Auth-generated token/URL server-side only,
 * never claiming it was actually emailed. In a secure deployment it
 * never logs the token at all and fails closed instead -- see
 * `VerificationEmailNotConfiguredError`'s own docstring for why that
 * is safe and does not break sign-up itself.
 */
export async function deliverVerificationEmail(user: { email: string }, url: string): Promise<void> {
  if (isSecureDeployment()) {
    throw new VerificationEmailNotConfiguredError();
  }
  console.log(
    `[web-console] email verification link for ${user.email} (local-development only -- not emailed, ` +
      `no provider configured): ${url}`,
  );
}
