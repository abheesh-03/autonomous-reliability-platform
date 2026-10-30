import { KeyRound } from "lucide-react";
import { ForgotPasswordForm } from "../../components/auth/ForgotPasswordForm";
import { Card, CardContent } from "../../components/ui/card";

export default function ForgotPasswordPage() {
  return (
    <div className="w-full max-w-sm">
      <div className="mb-6 flex flex-col items-center gap-2 text-center">
        <KeyRound className="h-7 w-7 text-accent-soft-fg" aria-hidden="true" />
        <h1 className="text-lg font-semibold text-fg">Reset your password</h1>
        <p className="text-sm text-fg-muted">Enter your email and we&rsquo;ll send you a reset link.</p>
      </div>
      <Card>
        <CardContent className="pt-5">
          <ForgotPasswordForm />
        </CardContent>
      </Card>
    </div>
  );
}
