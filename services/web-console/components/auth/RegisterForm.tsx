"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { authClient } from "@/lib/auth/client";
import { Button } from "../ui/button";
import { Input, Label } from "../ui/input";

/**
 * Phase 14 Gate 2: local registration via Better Auth's own real
 * client method (`authClient.signUp.email`) -- real, library-provided
 * password hashing happens server-side; this component never sees or
 * computes a hash. `minPasswordLength: 12` (lib/auth/auth.ts) is
 * enforced server-side regardless of what this form allows through.
 */
export function RegisterForm() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    // Independent-review correction round: `authClient.signUp.email`
    // normally RESOLVES with `{ error }` for an ordinary rejected
    // sign-up (bad input, duplicate email, ...), but a lower-level
    // failure -- a network error, or a cross-origin request blocked by
    // the browser's own CORS enforcement (see lib/auth/client.ts's own
    // fix for why that could happen) -- makes the underlying fetch
    // THROW instead. Without this try/catch, that exception propagated
    // straight out of this handler and `setPending(false)` below was
    // never reached, leaving the button disabled and spinning
    // indefinitely with no feedback at all -- a real, user-reported
    // bug, not a hypothetical one.
    try {
      const { error: signUpError } = await authClient.signUp.email({ name, email, password });
      if (signUpError) {
        setError(signUpError.message ?? "Could not create an account with these details.");
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
        <Label htmlFor="register-name">Name</Label>
        <Input
          id="register-name"
          type="text"
          required
          autoComplete="name"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </div>
      <div>
        <Label htmlFor="register-email">Email</Label>
        <Input
          id="register-email"
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </div>
      <div>
        <Label htmlFor="register-password">Password (minimum 12 characters)</Label>
        <Input
          id="register-password"
          type="password"
          required
          minLength={12}
          autoComplete="new-password"
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
        Create account
      </Button>
    </form>
  );
}
