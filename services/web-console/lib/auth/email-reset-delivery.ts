/**
 * Phase 17A item 4: the real implementation behind `auth.ts`'s
 * `emailAndPassword.sendResetPassword` hook -- the exact symmetrical
 * counterpart of `email-verification-delivery.ts`'s
 * `deliverVerificationEmail`, reusing the SAME `isSecureDeployment`/
 * `isSmtpConfigured`/`sendMail` contract so both real flows (email
 * verification, password reset) share one fail-closed rule: a secure
 * deployment with no SMTP configured never logs a live token and
 * never fakes a send; local development with no SMTP configured logs
 * the real, Better-Auth-generated link server-side only, exactly like
 * the existing verification-email behavior.
 *
 * Better Auth's own `/forget-password` route (verified directly
 * against node_modules/better-auth/dist/api/routes/reset-password.mjs)
 * already generates a real, single-use, time-limited token before
 * this hook ever runs, and -- same as sendVerificationEmail -- awaits
 * this callback through `runInBackgroundOrAwait`, which only logs an
 * exception rather than propagating it to the caller: throwing here
 * is a safe, loud failure that never blocks `/forget-password` itself
 * from reporting success (so the response stays safe against account
 * enumeration either way -- see docs on that route's own
 * always-200-regardless-of-whether-the-email-exists behavior).
 */
import "server-only";

import { isSecureDeployment } from "./deployment-mode";
import { isSmtpConfigured, sendMail } from "./mail-transport";

export class ResetPasswordEmailNotConfiguredError extends Error {
  constructor() {
    super(
      "cannot deliver a real password-reset email: no email-delivery provider is configured for this " +
        "secure deployment (CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT is enabled) -- password reset is " +
        "unavailable until a real SMTP provider is wired up",
    );
    this.name = "ResetPasswordEmailNotConfiguredError";
  }
}

export async function deliverResetPasswordEmail(user: { email: string }, url: string): Promise<void> {
  if (isSmtpConfigured()) {
    await sendMail({
      to: user.email,
      subject: "Reset your password",
      text: `Reset your password by visiting the following link:\n\n${url}\n\nIf you did not request this, you can ignore this message -- your password will not be changed.`,
      html:
        `<p>Reset your password by clicking the link below:</p>` +
        `<p><a href="${url}">Reset password</a></p>` +
        `<p>If you did not request this, you can ignore this message -- your password will not be changed.</p>`,
    });
    return;
  }
  if (isSecureDeployment()) {
    throw new ResetPasswordEmailNotConfiguredError();
  }
  console.log(
    `[web-console] password reset link for ${user.email} (local-development only -- not emailed, ` +
      `no provider configured): ${url}`,
  );
}
