"use client";

import { useState } from "react";
import Link from "next/link";
import { Menu } from "lucide-react";
import { SidebarNav } from "./sidebar-nav";
import { OrgSwitcher } from "./org-switcher";
import { UserMenu } from "./user-menu";
import { ThemeToggle } from "../theme/theme-toggle";
import { Dialog, DialogContent } from "../ui/dialog";
import { Button } from "../ui/button";
import { cn } from "../../lib/cn";

export function AppShell({
  email,
  role,
  organizationName,
  children,
}: {
  email: string;
  role: string | null;
  organizationName: string;
  children: React.ReactNode;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="min-h-screen bg-bg">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-60 shrink-0 border-r border-border bg-bg-raised px-3 py-5 lg:block">
        <SidebarNav />
      </aside>

      {/* Mobile sidebar, as a left-anchored sheet built on the Dialog primitive.
          Gate 7 visual polish: the desktop header's OrgSwitcher is
          `hidden lg:block` (see below), so without this it would be
          completely unreachable on a mobile viewport -- organization
          switching must remain usable there too. */}
      <Dialog open={mobileOpen} onOpenChange={setMobileOpen}>
        <DialogContent className="left-0 top-0 h-full w-72 max-w-[85vw] -translate-x-0 -translate-y-0 rounded-none border-r border-border p-4">
          <div className="mb-4 border-b border-border pb-4">
            <OrgSwitcher activeOrganizationName={organizationName} />
          </div>
          <SidebarNav onNavigate={() => setMobileOpen(false)} />
        </DialogContent>
      </Dialog>

      <div className="lg:pl-60">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-border bg-bg/80 px-4 backdrop-blur-sm lg:px-6">
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              className="lg:hidden"
              aria-label="Open navigation"
              onClick={() => setMobileOpen(true)}
            >
              <Menu className="h-5 w-5" />
            </Button>
            <Link href="/" className="font-semibold text-fg lg:hidden">
              Reliability Console
            </Link>
            <div className="hidden lg:block">
              <OrgSwitcher activeOrganizationName={organizationName} />
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <ThemeToggle />
            <UserMenu email={email} role={role} />
          </div>
        </header>
        <div className={cn("mx-auto w-full max-w-[1400px] px-4 py-6 lg:px-8")}>{children}</div>
      </div>
    </div>
  );
}
