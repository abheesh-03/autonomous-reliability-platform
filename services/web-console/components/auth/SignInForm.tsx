"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { authClient } from "@/lib/auth/client";

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
    const { error: signInError } = await authClient.signIn.email({ email, password });
    setPending(false);
    if (signInError) {
      setError("Invalid email or password.");
      return;
    }
    router.push("/organizations");
    router.refresh();
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: "grid", gap: "0.75rem", maxWidth: 360 }}>
      <label>
        Email
        <input
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          style={{ display: "block", width: "100%" }}
        />
      </label>
      <label>
        Password
        <input
          type="password"
          required
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          style={{ display: "block", width: "100%" }}
        />
      </label>
      {error && (
        <p role="alert" style={{ color: "#f3c9c9" }}>
          {error}
        </p>
      )}
      <button type="submit" disabled={pending}>
        {pending ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
