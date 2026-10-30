"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { authClient } from "@/lib/auth/client";
import { Button } from "../ui/button";
import { Input, Label } from "../ui/input";

/**
 * Phase 17A item 4: the landing page after a user clicks their real
 * password-reset email link. Better Auth's own backend callback route
 * (`GET /reset-password/:token`, verified against
 * node_modules/better-auth/dist/api/routes/password.mjs) redirects
 * the browser here with `?token=...` on success, or `?error=
 * INVALID_TOKEN` if the token was already used/expired/malformed --
 * this component reads EXACTLY that query contract (never invents its
 * own token handling) and calls Better Auth's own real
 * `authClient.resetPassword({ newPassword, token })`.
 */
export function ResetPasswordForm({ token, invalidToken }: { token: string | null; invalidToken: boolean }) {
  const router = useRouter();
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [success, setSuccess] = useState(false);

  if (invalidToken || !token) {
    return (
      <p role="alert" className="text-sm text-critical-fg">
        This password reset link is invalid or has expired. Request a new one.
      </p>
    );
  }

  if (success) {
    return (
      <p role="status" className="text-sm text-fg-muted">
        Your password has been reset. You can now sign in with your new password.
      </p>
    );
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const { error: resetError } = await authClient.resetPassword({ newPassword, token: token as string });
      if (resetError) {
        setError("This password reset link is invalid or has expired. Request a new one.");
        return;
      }
      setSuccess(true);
      setTimeout(() => router.push("/sign-in"), 2000);
    } catch {
      setError("Could not reach the server. Check your connection and try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="grid gap-4">
      <div>
        <Label htmlFor="reset-password-new">New password</Label>
        <Input
          id="reset-password-new"
          type="password"
          required
          minLength={12}
          autoComplete="new-password"
          value={newPassword}
          onChange={(event) => setNewPassword(event.target.value)}
        />
      </div>
      {error && (
        <p role="alert" className="text-sm text-critical-fg">
          {error}
        </p>
      )}
      <Button type="submit" disabled={pending} loading={pending} className="mt-1">
        Reset password
      </Button>
    </form>
  );
}
