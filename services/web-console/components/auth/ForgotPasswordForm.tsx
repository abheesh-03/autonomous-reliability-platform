"use client";

import { useState } from "react";

import { authClient } from "@/lib/auth/client";
import { Button } from "../ui/button";
import { Input, Label } from "../ui/input";

/**
 * Phase 17A item 4: Better Auth's own real, supported
 * request-password-reset endpoint (verified directly against
 * node_modules/better-auth/dist/api/routes/password.mjs --
 * `POST /request-password-reset`, client method `requestPasswordReset`).
 * This form never reveals whether the submitted email actually
 * belongs to an account -- Better Auth's own route always responds
 * the same way either way (it simulates the verification-token work
 * for an unknown email rather than short-circuiting), and this
 * component shows the identical success message regardless of the
 * real outcome, for the same anti-enumeration reason SignInForm.tsx's
 * own fixed, generic error message already documents.
 */
export function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const [pending, setPending] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await authClient.requestPasswordReset({ email, redirectTo: "/reset-password" });
    } catch {
      // Still shown as "submitted" below -- a network-level failure
      // here must not teach an attacker anything either; the user can
      // simply try again.
    } finally {
      setPending(false);
      setSubmitted(true);
    }
  }

  if (submitted) {
    return (
      <p role="status" className="text-sm text-fg-muted">
        If an account exists for that email address, a password reset link has been sent. Check your inbox.
      </p>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="grid gap-4">
      <div>
        <Label htmlFor="forgot-password-email">Email</Label>
        <Input
          id="forgot-password-email"
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </div>
      {error && (
        <p role="alert" className="text-sm text-critical-fg">
          {error}
        </p>
      )}
      <Button type="submit" disabled={pending} loading={pending} className="mt-1">
        Send reset link
      </Button>
    </form>
  );
}
