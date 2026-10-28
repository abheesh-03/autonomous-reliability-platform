import { headers as nextHeaders } from "next/headers";
import Link from "next/link";
import { auth } from "../../lib/auth/auth";
import { getSessionUser, resolveActor } from "../../lib/server/actor";
import { VerifyEmailBanner } from "../auth/VerifyEmailBanner";
import { AppShell } from "./app-shell";
import { ThemeToggle } from "../theme/theme-toggle";

/**
 * Phase 15: the one place that decides which of three real,
 * session-derived layouts to render -- never a fourth, separate
 * "demo" layout. All three read the EXACT same real
 * resolveActor()/getSessionUser() this console's protected pages
 * already use (lib/server/actor.ts) -- this component only decides
 * what CHROME to show around whatever the page itself renders; it is
 * never itself a security boundary (Gate 9: the real boundary is each
 * protected page's own requireActorOrRedirect() call, and
 * independently, the backend's own assertion verification).
 *
 *   1. No session at all -> a minimal, centered layout with no
 *      sidebar (sign-in/register/unauthorized pages).
 *   2. A real session but no resolved organization membership -> a
 *      minimal top bar only (the /organizations page itself is the
 *      only reasonable destination here).
 *   3. A real, fully resolved actor -> the full application shell.
 */
export async function RootShell({ children }: { children: React.ReactNode }) {
  const [actor, sessionUser] = await Promise.all([resolveActor(), getSessionUser()]);

  if (!sessionUser) {
    return (
      <div className="flex min-h-screen flex-col">
        <div className="flex justify-end px-4 py-3">
          <ThemeToggle />
        </div>
        <main className="flex flex-1 items-center justify-center px-4 pb-16">{children}</main>
      </div>
    );
  }

  if (!actor) {
    return (
      <div className="flex min-h-screen flex-col">
        <header className="flex items-center justify-between border-b border-border px-4 py-3 lg:px-6">
          <Link href="/" className="text-sm font-semibold text-fg">
            Reliability Console
          </Link>
          <ThemeToggle />
        </header>
        {!sessionUser.emailVerified && <VerifyEmailBanner email={sessionUser.email} />}
        <main className="mx-auto w-full max-w-2xl flex-1 px-4 py-8">{children}</main>
      </div>
    );
  }

  const organizationName = await resolveOrganizationName(actor.organizationId);

  return (
    <AppShell email={sessionUser.email} role={actor.role} organizationName={organizationName}>
      {!sessionUser.emailVerified && <VerifyEmailBanner email={sessionUser.email} />}
      {children}
    </AppShell>
  );
}

async function resolveOrganizationName(organizationId: string): Promise<string> {
  try {
    const requestHeaders = await nextHeaders();
    const organizations = await auth.api.listOrganizations({ headers: requestHeaders });
    const active = organizations?.find((org) => org.id === organizationId);
    return active?.name ?? "Organization";
  } catch {
    // Cosmetic only (Gate 9) -- never blocks rendering the real page
    // behind it over a display-name lookup failure.
    return "Organization";
  }
}
