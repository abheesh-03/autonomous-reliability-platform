"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { authClient } from "@/lib/auth/client";

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
    const { error: signUpError } = await authClient.signUp.email({ name, email, password });
    setPending(false);
    if (signUpError) {
      setError(signUpError.message ?? "Could not create an account with these details.");
      return;
    }
    router.push("/organizations");
    router.refresh();
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: "grid", gap: "0.75rem", maxWidth: 360 }}>
      <label>
        Name
        <input
          type="text"
          required
          autoComplete="name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          style={{ display: "block", width: "100%" }}
        />
      </label>
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
        Password (minimum 12 characters)
        <input
          type="password"
          required
          minLength={12}
          autoComplete="new-password"
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
        {pending ? "Creating account…" : "Create account"}
      </button>
    </form>
  );
}
