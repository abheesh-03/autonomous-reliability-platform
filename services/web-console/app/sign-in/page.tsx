import Link from "next/link";
import { SignInForm } from "../../components/auth/SignInForm";

export default function SignInPage() {
  return (
    <main style={{ maxWidth: 420, margin: "0 auto", padding: "3rem 1.5rem" }}>
      <h1>Sign in</h1>
      <SignInForm />
      <p style={{ marginTop: "1.5rem", color: "#9fb3c8" }}>
        No account? <Link href="/register">Create one</Link>.
      </p>
    </main>
  );
}
