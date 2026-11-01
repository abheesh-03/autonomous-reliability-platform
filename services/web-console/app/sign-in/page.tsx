import Link from "next/link";
import { ShieldAlert, Sparkles } from "lucide-react";
import { SignInForm } from "../../components/auth/SignInForm";
import { Card, CardContent } from "../../components/ui/card";
import { buttonVariants } from "../../components/ui/button";
import { cn } from "../../lib/cn";

export default function SignInPage() {
  return (
    <div className="w-full max-w-sm">
      <div className="mb-6 flex flex-col items-center gap-2 text-center">
        <ShieldAlert className="h-7 w-7 text-accent-soft-fg" aria-hidden="true" />
        <h1 className="text-lg font-semibold text-fg">Sign in</h1>
        <p className="text-sm text-fg-muted">Welcome back to the Reliability Console.</p>
      </div>
      <Card>
        <CardContent className="pt-5">
          <SignInForm />
        </CardContent>
      </Card>
      <p className="mt-3 text-center text-sm text-fg-muted">
        <Link href="/forgot-password" className="font-medium text-accent-soft-fg hover:underline">
          Forgot password?
        </Link>
      </p>
      <p className="mt-2 text-center text-sm text-fg-muted">
        No account?{" "}
        <Link href="/register" className="font-medium text-accent-soft-fg hover:underline">
          Create one
        </Link>
        .
      </p>
      <Link href="/demo" className={cn(buttonVariants({ variant: "outline", size: "sm" }), "mt-5 w-full")}>
        <Sparkles className="h-4 w-4" aria-hidden="true" />
        Explore recorded demo — no signup needed
      </Link>
    </div>
  );
}
