import Link from "next/link";
import { RegisterForm } from "../../components/auth/RegisterForm";

export default function RegisterPage() {
  return (
    <main style={{ maxWidth: 420, margin: "0 auto", padding: "3rem 1.5rem" }}>
      <h1>Create account</h1>
      <RegisterForm />
      <p style={{ marginTop: "1.5rem", color: "#9fb3c8" }}>
        Already have an account? <Link href="/sign-in">Sign in</Link>.
      </p>
    </main>
  );
}
