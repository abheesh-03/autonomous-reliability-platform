"use client";

import { useRouter } from "next/navigation";
import { LogOut, Shield, Users } from "lucide-react";
import { authClient } from "@/lib/auth/client";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";

function initialsOf(email: string): string {
  const [name] = email.split("@");
  return name.slice(0, 2).toUpperCase();
}

export function UserMenu({ email, role }: { email: string; role: string | null }) {
  const router = useRouter();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="flex h-8 w-8 items-center justify-center rounded-full bg-accent-soft-bg text-xs font-semibold text-accent-soft-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--accent)"
        aria-label="Account menu"
      >
        {initialsOf(email)}
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-56">
        <DropdownMenuLabel className="space-y-0.5">
          <p className="truncate text-sm font-medium text-fg">{email}</p>
          {role && (
            <p className="flex items-center gap-1 text-xs text-fg-subtle">
              <Shield className="h-3 w-3" aria-hidden="true" /> {role}
            </p>
          )}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => router.push("/organizations")}>
          <Users className="h-3.5 w-3.5" aria-hidden="true" />
          Organizations
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={async () => {
            await authClient.signOut();
            router.push("/sign-in");
            router.refresh();
          }}
        >
          <LogOut className="h-3.5 w-3.5" aria-hidden="true" />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
