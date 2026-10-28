"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { authClient } from "@/lib/auth/client";
import { Button } from "../ui/button";
import { Input, Label } from "../ui/input";

/**
 * Phase 14 Gate 2/9: calls Better Auth's own real client method
 * (`authClient.signIn.email`) -- no hand-rolled credential submission
 * or password handling anywhere in this component. A failed sign-in
 * shows one fixed, generic message (never "no such user" vs. "wrong
 * password", which would let an attacker enumerate registered
 * emails) -- Gate 2: "safe login error behavior."
 */
export function SignInForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    // Independent-review correction round: see RegisterForm.tsx's own
    // identical fix for the full explanation -- a thrown (not merely
    // resolved-with-error) failure from authClient must never leave
    // this button disabled/spinning with no feedback.
    try {
      const { error: signInError } = await authClient.signIn.email({ email, password });
      if (signInError) {
        setError("Invalid email or password.");
        return;
      }
      router.push("/organizations");
      router.refresh();
    } catch {
      setError("Could not reach the server. Check your connection and try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="grid gap-4">
      <div>
        <Label htmlFor="sign-in-email">Email</Label>
        <Input
          id="sign-in-email"
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </div>
      <div>
        <Label htmlFor="sign-in-password">Password</Label>
        <Input
          id="sign-in-password"
          type="password"
          required
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </div>
      {error && (
        <p role="alert" className="text-sm text-critical-fg">
          {error}
        </p>
      )}
      <Button type="submit" disabled={pending} loading={pending} className="mt-1">
        Sign in
      </Button>
    </form>
  );
}
