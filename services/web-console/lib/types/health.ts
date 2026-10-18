// Not a backend contract to mirror -- these are this console's OWN
// narrow categorization of what a real /health/live + /health/ready
// pair actually proved, never a synthesized "healthy" guess.

export type LiveStatus = "UP" | "UNAVAILABLE" | "UNKNOWN";
export type ReadyStatus = "READY" | "NOT_READY" | "UNAVAILABLE" | "UNKNOWN";

export interface ServiceHealthResult {
  name: string;
  live: LiveStatus;
  ready: ReadyStatus;
}
