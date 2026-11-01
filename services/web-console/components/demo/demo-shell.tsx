"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, Siren, Sparkles, Gauge, ExternalLink, History } from "lucide-react";
import { cn } from "../../lib/cn";
import { buttonVariants } from "../ui/button";
import { ThemeToggle } from "../theme/theme-toggle";
import { demoSnapshot } from "../../lib/demo/snapshot";

const GITHUB_URL = "https://github.com/abheesh-03/autonomous-reliability-platform";

const DEMO_NAV = [
  { label: "Overview", href: "/demo", icon: LayoutDashboard },
  { label: "Incident", href: `/demo/incident/${demoSnapshot.incident_scenario.incident.id}`, icon: Siren },
  { label: "Investigation", href: `/demo/investigation/${demoSnapshot.incident_scenario.agent_run.run_id}`, icon: Sparkles },
  { label: "Telemetry", href: `/demo/telemetry/${demoSnapshot.telemetry_scenario.service.id}`, icon: Gauge },
];

/**
 * Phase 18: the dedicated, session-independent chrome for every
 * `/demo` page -- deliberately never AppShell (which renders a real
 * signed-in visitor's own organization name/sidebar) and never the
 * bare centered auth shell (which has no room for real navigation
 * between the demo's four views). Renders identically regardless of
 * whether the visitor is signed in, signed out, or anything in
 * between -- see root-shell.tsx's own comment on why this branch
 * exists and is checked first.
 *
 * Every link in `DEMO_NAV` stays within /demo/*; the only links that
 * leave it are GitHub and the two explicitly labeled "Sign in" /
 * "Create a workspace" actions below -- Section 3's own requirement.
 */
export function DemoShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="flex min-h-screen flex-col bg-bg">
      <div className="border-b border-warning-soft-bg bg-warning-soft-bg px-4 py-2 text-center text-xs font-medium text-warning-fg">
        <History className="mr-1.5 inline h-3.5 w-3.5 align-text-bottom" aria-hidden="true" />
        Recorded demo — captured {demoSnapshot.provenance.captured_at}. Nothing on this page is live. See the full
        disclosure on the{" "}
        <Link href="/demo" className="underline underline-offset-2 hover:no-underline">
          overview
        </Link>
        .
      </div>

      <header className="border-b border-border bg-bg-raised">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-4 py-3 lg:px-6">
          <div className="flex min-w-0 flex-wrap items-center gap-2 text-fg">
            <Sparkles className="h-5 w-5 text-accent-soft-fg" aria-hidden="true" />
            <span className="text-sm font-semibold tracking-tight">Reliability Console</span>
            <span className="rounded-full bg-surface-hover px-2 py-0.5 text-[0.6875rem] font-medium text-fg-muted">
              Recorded demo
            </span>
          </div>
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noopener noreferrer"
              className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}
            >
              <ExternalLink className="h-4 w-4" aria-hidden="true" />
              GitHub
            </a>
            <Link href="/sign-in" className={cn(buttonVariants({ variant: "outline", size: "sm" }))}>
              Sign in
            </Link>
            <Link
              href="/register"
              // The unlayered global anchor color wins over ordinary utility
              // colors. Keep this CTA white on a sufficiently dark blue in
              // both themes without changing every link in the application.
              className={cn(buttonVariants({ variant: "primary", size: "sm" }), "bg-accent-600 text-accent-fg!")}
            >
              Create a workspace
            </Link>
            <ThemeToggle />
          </div>
        </div>
        <nav aria-label="Recorded demo" className="mx-auto max-w-5xl px-4 pb-3 lg:px-6">
          <ul className="flex flex-wrap gap-1.5">
            {DEMO_NAV.map((item) => {
              const isActive = item.href === "/demo" ? pathname === "/demo" : pathname.startsWith(item.href);
              const Icon = item.icon;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={isActive ? "page" : undefined}
                    className={cn(
                      "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
                      isActive
                        ? "bg-accent-soft-bg text-accent-soft-fg"
                        : "text-fg-muted hover:bg-surface-hover hover:text-fg",
                    )}
                  >
                    <Icon className="h-4 w-4" aria-hidden="true" />
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6 lg:px-6">{children}</main>

      <footer className="border-t border-border px-4 py-4 text-center text-xs text-fg-subtle lg:px-6">
        This is a recorded, read-only demo of the Autonomous Production Reliability Platform.{" "}
        <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2 hover:no-underline">
          View the source on GitHub
        </a>{" "}
        or{" "}
        <Link href="/register" className="underline underline-offset-2 hover:no-underline">
          create your own real workspace
        </Link>
        .
      </footer>
    </div>
  );
}
