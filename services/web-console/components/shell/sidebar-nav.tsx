"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ShieldAlert } from "lucide-react";
import { NAV_GROUPS } from "./nav-config";
import { cn } from "../../lib/cn";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "../ui/tooltip";

export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();

  return (
    <nav className="flex flex-col gap-5" aria-label="Primary">
      <div className="flex items-center gap-2 px-2 text-fg">
        <ShieldAlert className="h-5 w-5 text-accent-soft-fg" aria-hidden="true" />
        <span className="text-sm font-semibold tracking-tight">Reliability Console</span>
      </div>

      {NAV_GROUPS.map((group) => (
        <div key={group.label}>
          <p className="mb-1.5 px-2 text-[0.6875rem] font-semibold uppercase tracking-wider text-fg-subtle">
            {group.label}
          </p>
          <ul className="space-y-0.5">
            {group.items.map((item) => {
              const isActive = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              const Icon = item.icon;

              if (!item.available) {
                return (
                  <li key={item.href}>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span
                          aria-disabled="true"
                          className="flex cursor-not-allowed items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-fg-subtle opacity-60"
                        >
                          <Icon className="h-4 w-4" aria-hidden="true" />
                          {item.label}
                        </span>
                      </TooltipTrigger>
                      <TooltipContent>{item.unavailableReason ?? "Not available yet."}</TooltipContent>
                    </Tooltip>
                  </li>
                );
              }

              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={isActive ? "page" : undefined}
                    className={cn(
                      "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm font-medium transition-colors",
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
        </div>
      ))}
    </nav>
  );
}
