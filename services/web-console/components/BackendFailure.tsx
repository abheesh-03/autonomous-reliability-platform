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
};

export function BackendFailure({ kind }: { kind: BackendErrorKind }) {
  return (
    <div
      role="alert"
      style={{
        border: "1px solid #5a2a2a",
        background: "#1a0f0f",
        color: "#f3c9c9",
        borderRadius: 8,
        padding: "1rem",
      }}
    >
      {MESSAGES[kind]}
    </div>
  );
}
