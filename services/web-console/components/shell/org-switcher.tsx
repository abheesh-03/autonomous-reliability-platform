"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Check, ChevronsUpDown, Loader2, Plus } from "lucide-react";
import { authClient } from "@/lib/auth/client";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";
import { useToast } from "../ui/toast";

interface OrgSummary {
  id: string;
  name: string;
}

/**
 * Real organization switching, via Better Auth's own
 * `authClient.organization.list`/`.setActive` -- same underlying calls
 * OrganizationsPanel already uses. The org list is fetched lazily, on
 * open, rather than on every page load, since it is not needed until
 * the dropdown is actually opened.
 */
export function OrgSwitcher({ activeOrganizationName }: { activeOrganizationName: string }) {
  const router = useRouter();
  const toast = useToast();
  const [orgs, setOrgs] = useState<OrgSummary[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [switching, setSwitching] = useState<string | null>(null);

  async function loadOnOpen(open: boolean) {
    if (!open || orgs !== null) return;
    setLoading(true);
    try {
      const result = await authClient.organization.list();
      setOrgs((result.data ?? []).map((org) => ({ id: org.id, name: org.name })));
    } finally {
      setLoading(false);
    }
  }

  async function switchTo(orgId: string) {
    setSwitching(orgId);
    try {
      const result = await authClient.organization.setActive({ organizationId: orgId });
      if (result.error) {
        toast({ title: "Could not switch organization", description: result.error.message, tone: "critical" });
        return;
      }
      router.refresh();
    } finally {
      setSwitching(null);
    }
  }

  return (
    <DropdownMenu onOpenChange={loadOnOpen}>
      <DropdownMenuTrigger className="flex max-w-48 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm font-medium text-fg hover:bg-surface-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--accent)">
        <span className="truncate">{activeOrganizationName}</span>
        <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 text-fg-subtle" aria-hidden="true" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64">
        <DropdownMenuLabel>Switch organization</DropdownMenuLabel>
        {loading && (
          <div className="flex items-center gap-2 px-2.5 py-2 text-sm text-fg-muted">
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> Loading…
          </div>
        )}
        {orgs?.map((org) => (
          <DropdownMenuItem key={org.id} disabled={switching !== null} onSelect={() => switchTo(org.id)}>
            <span className="flex h-3.5 w-3.5 items-center justify-center">
              {org.name === activeOrganizationName && <Check className="h-3.5 w-3.5 text-accent-soft-fg" />}
            </span>
            <span className="truncate">{org.name}</span>
            {switching === org.id && <Loader2 className="ml-auto h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => router.push("/organizations")}>
          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
          Manage organizations
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
