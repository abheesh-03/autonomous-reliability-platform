import { CalendarClock, Bot, ShieldCheck } from "lucide-react";
import { Card, CardContent } from "../ui/card";
import type { DemoProvenance } from "../../lib/demo/types";

/**
 * Phase 18: the explicit, unmissable "this is recorded, not live"
 * disclosure required for every recorded-demo view. Deliberately
 * states the capture date, that measurements/workflow results are
 * historical, and that the investigation used a deterministic stub
 * provider rather than a live/paid LLM call -- never left implicit.
 */
export function DemoDisclosure({ provenance }: { provenance: DemoProvenance }) {
  return (
    <Card className="border-warning-soft-bg bg-warning-soft-bg/40">
      <CardContent className="space-y-2.5 pt-5 text-sm text-fg">
        <p className="flex items-start gap-2">
          <CalendarClock className="mt-0.5 h-4 w-4 shrink-0 text-warning-fg" aria-hidden="true" />
          <span>
            <strong className="font-medium">Captured {provenance.captured_at}.</strong> Every measurement, timestamp,
            and workflow result below is historical -- recorded once from a real, completed run and replayed exactly
            as captured. Nothing here updates, polls, or reflects the current time.
          </span>
        </p>
        <p className="flex items-start gap-2">
          <Bot className="mt-0.5 h-4 w-4 shrink-0 text-warning-fg" aria-hidden="true" />
          <span>
            <strong className="font-medium">Investigator provider: stub.</strong> The recorded investigation below
            was produced by this platform&apos;s deterministic stub investigator, not a live or paid LLM call.
          </span>
        </p>
        <p className="flex items-start gap-2">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-warning-fg" aria-hidden="true" />
          <span>
            <strong className="font-medium">Approval and remediation are recorded historical events</strong>, decided
            and executed once during the original run. There are no Approve, Run, or Execute controls here -- this
            view is read-only.
          </span>
        </p>
      </CardContent>
    </Card>
  );
}
