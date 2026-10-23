"use client";

import { useState } from "react";

import { authClient } from "@/lib/auth/client";

/**
 * Phase 14 correction round, Issue 5: shown whenever the current
 * session's email is not verified. No fake "email sent" claim -- this
 * calls Better Auth's own real `/send-verification-email` endpoint,
 * which mints a genuine, single-use token and (per lib/auth/auth.ts's
 * `sendVerificationEmail` callback) logs the real verification URL
 * server-side, since no external email provider is configured this
 * phase. An unverified account cannot accept or reject any
 * organization invitation (`requireEmailVerificationOnInvitation: true`).
 */
export function VerifyEmailBanner({ email }: { email: string }) {
  const [sent, setSent] = useState(false);

  return (
    <div
      role="status"
      style={{
        border: "1px solid #5a4a1f",
        background: "#1a140a",
        color: "#f3e2a8",
        borderRadius: 8,
        padding: "0.75rem 1rem",
        margin: "1rem 1.5rem",
      }}
    >
      Your email ({email}) is not verified. You cannot accept or reject organization invitations until it is.{" "}
      {sent ? (
        "A new verification link was requested -- check this server's logs (no email provider is configured for local development)."
      ) : (
        <button
          type="button"
          onClick={async () => {
            await authClient.sendVerificationEmail({ email });
            setSent(true);
          }}
        >
          Resend verification link
        </button>
      )}
    </div>
  );
}
