import { KeyRound } from "lucide-react";
import { ResetPasswordForm } from "../../components/auth/ResetPasswordForm";
import { Card, CardContent } from "../../components/ui/card";

export default async function ResetPasswordPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string; error?: string }>;
}) {
  const params = await searchParams;
  const token = params.token ?? null;
  const invalidToken = params.error === "INVALID_TOKEN";

  return (
    <div className="w-full max-w-sm">
      <div className="mb-6 flex flex-col items-center gap-2 text-center">
        <KeyRound className="h-7 w-7 text-accent-soft-fg" aria-hidden="true" />
        <h1 className="text-lg font-semibold text-fg">Choose a new password</h1>
      </div>
      <Card>
        <CardContent className="pt-5">
          <ResetPasswordForm token={token} invalidToken={invalidToken} />
        </CardContent>
      </Card>
    </div>
  );
}
