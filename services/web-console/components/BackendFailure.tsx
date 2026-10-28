import { AlertTriangle } from "lucide-react";
import type { BackendErrorKind } from "../lib/server/http";

// Professional operator-facing failure states -- never the raw
// backend exception body, never "no incidents" when the real cause
// was an unavailable/malformed response.
const MESSAGES: Record<BackendErrorKind, string> = {
  not_found: "Not found.",
  validation: "The request was rejected as invalid.",
  unavailable: "Control plane unavailable. Try again shortly.",
  malformed: "Received an unexpected response from the backend.",
  conflict: "The requested change is no longer valid for the current state.",
  unauthorized: "This server could not authenticate to the backend.",
  configuration: "This server is not configured correctly for this action.",
  forbidden: "You do not have permission to perform this action.",
};

export function BackendFailure({ kind }: { kind: BackendErrorKind }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-2.5 rounded-lg border border-critical-fg/30 bg-critical-soft-bg px-4 py-3 text-sm text-critical-fg"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <span>{MESSAGES[kind]}</span>
    </div>
  );
}
