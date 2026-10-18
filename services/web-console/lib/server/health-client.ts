import "server-only";

import type { LiveStatus, ReadyStatus, ServiceHealthResult } from "../types/health";
import { getJson } from "./http";

const HEALTH_TIMEOUT_MS = 3000;

async function checkLive(baseUrl: string): Promise<LiveStatus> {
  const result = await getJson(`${baseUrl}/health/live`, HEALTH_TIMEOUT_MS);
  if ("networkError" in result) return "UNAVAILABLE";
  if (result.parseError) return "UNKNOWN";
  if (result.status !== 200) return "UNAVAILABLE";
  const body = result.body as { status?: unknown } | null;
  return body?.status === "UP" ? "UP" : "UNKNOWN";
}

async function checkReady(baseUrl: string): Promise<ReadyStatus> {
  const result = await getJson(`${baseUrl}/health/ready`, HEALTH_TIMEOUT_MS);
  if ("networkError" in result) return "UNAVAILABLE";
  if (result.parseError) return "UNKNOWN";
  if (result.status === 200) {
    const body = result.body as { status?: unknown } | null;
    return body?.status === "ready" ? "READY" : "UNKNOWN";
  }
  if (result.status === 503) return "NOT_READY";
  return "UNKNOWN";
}

/**
 * Checks one service's real /health/live + /health/ready independently
 * -- never synthesizes a healthy result, and never lets one failing
 * call affect another service's own check (each call to this function
 * is independent; the caller runs them in parallel via Promise.all,
 * which is safe here because neither checkLive nor checkReady ever
 * rejects).
 */
export async function checkServiceHealth(name: string, baseUrl: string): Promise<ServiceHealthResult> {
  const [live, ready] = await Promise.all([checkLive(baseUrl), checkReady(baseUrl)]);
  return { name, live, ready };
}
