"use client";

import { useState } from "react";
import { Button } from "../ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../ui/dialog";

export interface GuidedStep {
  title: string;
  detail: string;
  done: boolean;
}

export function SetupGuideDialog({ name, steps }: { name: string; steps: GuidedStep[] }) {
  const [open, setOpen] = useState(false);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button variant="secondary" size="sm" onClick={() => setOpen(true)}>
        View setup guide
      </Button>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{name} setup</DialogTitle>
          <DialogDescription>
            The real enrollment flow for this integration -- each step below reflects what is actually implemented
            today, not an aspirational roadmap.
          </DialogDescription>
        </DialogHeader>
        <ol className="space-y-3">
          {steps.map((step, index) => (
            <li key={step.title} className="flex gap-3">
              <div
                className={
                  "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold " +
                  (step.done ? "bg-success-soft-bg text-success-fg" : "bg-surface-hover text-fg-subtle")
                }
              >
                {index + 1}
              </div>
              <div>
                <p className={"text-sm font-medium " + (step.done ? "text-fg" : "text-fg-muted")}>{step.title}</p>
                <p className="text-xs text-fg-subtle">{step.detail}</p>
              </div>
            </li>
          ))}
        </ol>
        <DialogFooter>
          <Button variant="secondary" onClick={() => setOpen(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
