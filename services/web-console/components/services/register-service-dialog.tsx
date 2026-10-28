"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "../ui/dialog";
import { Button } from "../ui/button";
import { Input, Label, Select } from "../ui/input";
import { useToast } from "../ui/toast";
import { Tooltip, TooltipContent, TooltipTrigger } from "../ui/tooltip";
import { SERVICE_KINDS, SERVICE_KIND_LABELS } from "../../lib/types/service";

/**
 * Calls this console's own BFF route (never control-plane directly --
 * Gate 10: "Do not fetch control-plane protected endpoints directly
 * from client-side code"), which mints the real actor assertion
 * server-side before forwarding.
 *
 * Independent-review correction round, BLOCKER 2: `canRegister` is a
 * UI-only convenience -- control-plane's own `require_role` check
 * (core/authz.py::ROLES_THAT_MAY_REGISTER_SERVICES) is the REAL
 * enforcement and is never bypassed merely because this prop is
 * miscalculated or stale; a disabled trigger here only prevents a
 * confusing round-trip-then-403 for a role that control-plane would
 * reject anyway, with an accessible explanation of why.
 */
export function RegisterServiceDialog({ canRegister = true }: { canRegister?: boolean }) {
  const router = useRouter();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [name, setName] = useState("");
  const [kind, setKind] = useState(SERVICE_KINDS[0]);
  const [language, setLanguage] = useState("");
  const [description, setDescription] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setPending(true);
    try {
      const response = await fetch("/api/services", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          kind,
          language: language.trim() || null,
          description: description.trim() || null,
        }),
      });
      const body: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        const message =
          body && typeof body === "object" && "message" in body && typeof (body as { message: unknown }).message === "string"
            ? (body as { message: string }).message
            : "Could not register this service.";
        toast({ title: "Could not register service", description: message, tone: "critical" });
        return;
      }
      toast({ title: "Service registered", description: `${name} was added to your organization.`, tone: "success" });
      setOpen(false);
      setName("");
      setLanguage("");
      setDescription("");
      router.refresh();
    } catch {
      toast({ title: "Could not reach the server", tone: "critical" });
    } finally {
      setPending(false);
    }
  }

  if (!canRegister) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span tabIndex={0}>
            <Button disabled aria-disabled="true">
              <Plus className="h-4 w-4" aria-hidden="true" />
              Register service
            </Button>
          </span>
        </TooltipTrigger>
        <TooltipContent>Your role does not have permission to register services in this organization.</TooltipContent>
      </Tooltip>
    );
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus className="h-4 w-4" aria-hidden="true" />
          Register service
        </Button>
      </DialogTrigger>
      <DialogContent>
        <form onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>Register a service</DialogTitle>
            <DialogDescription>
              Add a system you operate to this organization&apos;s catalog. This records the service itself --
              connecting it to real telemetry is a separate step on the Integrations page.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <div>
              <Label htmlFor="service-name">Name</Label>
              <Input
                id="service-name"
                required
                maxLength={200}
                placeholder="orders-api"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="service-kind">Kind</Label>
              <Select id="service-kind" value={kind} onChange={(event) => setKind(event.target.value as typeof kind)}>
                {SERVICE_KINDS.map((value) => (
                  <option key={value} value={value}>
                    {SERVICE_KIND_LABELS[value]}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label htmlFor="service-language">Language / runtime (optional)</Label>
              <Input
                id="service-language"
                maxLength={100}
                placeholder="Go, Java, Python, Node.js, .NET, …"
                value={language}
                onChange={(event) => setLanguage(event.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="service-description">Description (optional)</Label>
              <textarea
                id="service-description"
                maxLength={2000}
                rows={3}
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-fg placeholder:text-fg-subtle focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--accent)"
                placeholder="What does this service do?"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="secondary" onClick={() => setOpen(false)} disabled={pending}>
              Cancel
            </Button>
            <Button type="submit" loading={pending} disabled={name.trim().length === 0}>
              Register
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
