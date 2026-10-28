import Link from "next/link";
import { ShieldAlert } from "lucide-react";
import { RegisterForm } from "../../components/auth/RegisterForm";
import { Card, CardContent } from "../../components/ui/card";

export default function RegisterPage() {
  return (
    <div className="w-full max-w-sm">
      <div className="mb-6 flex flex-col items-center gap-2 text-center">
        <ShieldAlert className="h-7 w-7 text-accent-soft-fg" aria-hidden="true" />
        <h1 className="text-lg font-semibold text-fg">Create account</h1>
        <p className="text-sm text-fg-muted">Set up access to the Reliability Console.</p>
      </div>
      <Card>
        <CardContent className="pt-5">
          <RegisterForm />
        </CardContent>
      </Card>
      <p className="mt-4 text-center text-sm text-fg-muted">
        Already have an account?{" "}
        <Link href="/sign-in" className="font-medium text-accent-soft-fg hover:underline">
          Sign in
        </Link>
        .
      </p>
    </div>
  );
}
