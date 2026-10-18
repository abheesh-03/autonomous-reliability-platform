// Gate F support helpers: drive the REAL live stack's own test-harness
// surfaces (controlled payment fault injection, real checkout traffic,
// real Prometheus/Alertmanager state, real control-plane GETs) the
// exact same way scripts/verify-remediation.sh and
// scripts/verify-alerting.py already do, just in TypeScript so the
// Playwright spec can drive the real browser UI through the SAME real
// workflow those scripts already proved via curl.
//
// CREDENTIAL BOUNDARY: PAYMENT_FAULT_INJECTION_TOKEN and
// PAYMENT_REMEDIATION_TOKEN are TEST-HARNESS-ONLY secrets, read here
// directly from this test runner's own environment (.env) -- web-
// console itself never holds either, and this module is never
// imported by any web-console server/client code, only by this e2e
// suite.

const CHECKOUT_URL = process.env.CHECKOUT_URL ?? "http://127.0.0.1:8080";
const PAYMENT_URL = process.env.PAYMENT_URL ?? "http://127.0.0.1:8081";
const CONTROL_PLANE_URL = process.env.CONTROL_PLANE_URL ?? "http://127.0.0.1:8000";
const AGENT_RUNTIME_URL = process.env.AGENT_RUNTIME_URL ?? "http://127.0.0.1:8003";
const PROMETHEUS_URL = process.env.PROMETHEUS_URL ?? "http://127.0.0.1:9090";
const ALERTMANAGER_URL = process.env.ALERTMANAGER_URL ?? "http://127.0.0.1:9093";

export const ALERT_NAME = "CheckoutServerErrors";
export const INCIDENT_TITLE = "checkout-service is returning HTTP 5xx errors";

export function requiredTestHarnessTokens(): { faultInjection: string; remediation: string } {
  const faultInjection = process.env.PAYMENT_FAULT_INJECTION_TOKEN;
  const remediation = process.env.PAYMENT_REMEDIATION_TOKEN;
  if (!faultInjection || !remediation) {
    throw new Error(
      "PAYMENT_FAULT_INJECTION_TOKEN and PAYMENT_REMEDIATION_TOKEN must both be set in this test runner's " +
        "own environment (.env) -- these are test-harness-only secrets, never held by web-console itself.",
    );
  }
  return { faultInjection, remediation };
}

interface CheckoutResult {
  status: number;
  body: unknown;
}

const CHECKOUT_PAYLOAD = {
  sku: "sku_keyboard_001",
  quantity: 1,
  amount_cents: 2599,
  currency: "USD",
  recipient: "customer@example.com",
};

export async function doCheckout(): Promise<CheckoutResult> {
  try {
    const response = await fetch(`${CHECKOUT_URL}/checkouts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(CHECKOUT_PAYLOAD),
      signal: AbortSignal.timeout(15_000),
    });
    const body = await response.json().catch(() => null);
    return { status: response.status, body };
  } catch {
    return { status: 0, body: null };
  }
}

export function assertCheckoutFailedWithPaymentService(result: CheckoutResult) {
  if (result.status !== 502) {
    throw new Error(`expected HTTP 502 from payment-service, got ${result.status} (body=${JSON.stringify(result.body)})`);
  }
  const expected = { error: "downstream_failure", service: "payment-service", message: "Downstream service request failed" };
  if (JSON.stringify(result.body) !== JSON.stringify(expected)) {
    throw new Error(`checkout failure body did not match the expected downstream_failure contract: ${JSON.stringify(result.body)}`);
  }
}

export async function paymentFaultGet(): Promise<{ status: number; active: boolean | null }> {
  const { remediation } = requiredTestHarnessTokens();
  const response = await fetch(`${PAYMENT_URL}/internal/v1/faults/authorization`, {
    headers: { Authorization: `Bearer ${remediation}` },
    signal: AbortSignal.timeout(10_000),
  });
  const body = (await response.json().catch(() => null)) as { active?: boolean } | null;
  return { status: response.status, active: body?.active ?? null };
}

export async function paymentFaultEnable(): Promise<{ status: number; active: boolean | null }> {
  const { faultInjection } = requiredTestHarnessTokens();
  const response = await fetch(`${PAYMENT_URL}/internal/v1/faults/authorization/enable`, {
    method: "POST",
    headers: { Authorization: `Bearer ${faultInjection}` },
    signal: AbortSignal.timeout(10_000),
  });
  const body = (await response.json().catch(() => null)) as { active?: boolean } | null;
  return { status: response.status, active: body?.active ?? null };
}

export async function paymentFaultClear(): Promise<{ status: number; active: boolean | null }> {
  const { remediation } = requiredTestHarnessTokens();
  const response = await fetch(`${PAYMENT_URL}/internal/v1/faults/authorization/clear`, {
    method: "POST",
    headers: { Authorization: `Bearer ${remediation}` },
    signal: AbortSignal.timeout(10_000),
  });
  const body = (await response.json().catch(() => null)) as { active?: boolean } | null;
  return { status: response.status, active: body?.active ?? null };
}

interface PrometheusRule {
  name: string;
  state: string;
  alerts?: unknown[];
}

async function getPrometheusRule(alertName: string): Promise<PrometheusRule | null> {
  const response = await fetch(`${PROMETHEUS_URL}/api/v1/rules`, { signal: AbortSignal.timeout(10_000) });
  const body = await response.json();
  if (body.status !== "success") throw new Error(`Prometheus /api/v1/rules did not report status=success: ${JSON.stringify(body)}`);
  for (const group of body.data?.groups ?? []) {
    for (const rule of group.rules ?? []) {
      if (rule.type === "alerting" && rule.name === alertName) return rule as PrometheusRule;
    }
  }
  return null;
}

interface AlertmanagerAlert {
  labels: Record<string, string>;
  status: { state: string };
}

async function getAlertmanagerAlerts(): Promise<AlertmanagerAlert[]> {
  const response = await fetch(`${ALERTMANAGER_URL}/api/v2/alerts`, { signal: AbortSignal.timeout(10_000) });
  return (await response.json()) as AlertmanagerAlert[];
}

export async function isAlertInactive(alertName: string): Promise<boolean> {
  const rule = await getPrometheusRule(alertName);
  return rule !== null && rule.state === "inactive";
}

// Mirrors verify-alerting.py's own `firing` check: the Prometheus rule
// itself must report "firing" with a nonempty alerts list, AND
// Alertmanager's own GET /api/v2/alerts must independently report a
// matching, non-resolved alert -- proving real propagation between the
// two systems, not just one side's own belief.
export async function isAlertFiring(alertName: string): Promise<boolean> {
  const rule = await getPrometheusRule(alertName);
  if (!rule || rule.state !== "firing" || !rule.alerts?.length) return false;
  const alerts = await getAlertmanagerAlerts();
  const matches = alerts.filter((a) => a.labels?.alertname === alertName);
  return matches.some((a) => a.status?.state !== "resolved");
}

export async function isAlertRecovered(alertName: string): Promise<boolean> {
  const rule = await getPrometheusRule(alertName);
  if (!rule || rule.state !== "inactive" || (rule.alerts?.length ?? 0) > 0) return false;
  const alerts = await getAlertmanagerAlerts();
  const matches = alerts.filter((a) => a.labels?.alertname === alertName);
  return matches.every((a) => a.status?.state === "resolved" || a.status?.state === "suppressed");
}

export interface LiveIncident {
  id: string;
  status: string;
  title: string;
  first_seen_at: string;
  resolved_at: string | null;
  source_fingerprint: string;
}

async function fetchAllIncidents(source: string): Promise<LiveIncident[]> {
  const items: LiveIncident[] = [];
  let offset = 0;
  const limit = 100;
  for (;;) {
    const response = await fetch(`${CONTROL_PLANE_URL}/api/v1/incidents?source=${source}&limit=${limit}&offset=${offset}`, {
      signal: AbortSignal.timeout(10_000),
    });
    const body = await response.json();
    items.push(...(body.items ?? []));
    offset += limit;
    if (!body.items?.length || offset >= body.total) break;
  }
  return items;
}

// Mirrors verify-ingestion.py's own `incident-from-alert` freshness
// proof: only an ACTIVE (not resolved/closed), genuinely fresh
// (first_seen_at after this test run's own freshness checkpoint)
// incident counts -- never a stale historical row that happens to
// share this alert's title.
export async function findFreshActiveIncident(sinceIso: string): Promise<LiveIncident | null> {
  const items = await fetchAllIncidents("alertmanager");
  const since = new Date(sinceIso).getTime();
  const matches = items.filter(
    (i) => i.title === INCIDENT_TITLE && new Date(i.first_seen_at).getTime() > since && i.status !== "resolved" && i.status !== "closed",
  );
  if (matches.length > 1) {
    throw new Error(`expected at most one fresh active incident titled "${INCIDENT_TITLE}", found ${matches.length}`);
  }
  return matches[0] ?? null;
}

export async function getIncident(incidentId: string): Promise<LiveIncident> {
  const response = await fetch(`${CONTROL_PLANE_URL}/api/v1/incidents/${incidentId}`, { signal: AbortSignal.timeout(10_000) });
  if (response.status !== 200) throw new Error(`GET incident ${incidentId} returned ${response.status}`);
  return (await response.json()) as LiveIncident;
}

interface IncidentEvent {
  event_type: string;
  new_status: string | null;
  actor_type: string;
  metadata: Record<string, unknown>;
}

export async function getAllIncidentEvents(incidentId: string): Promise<IncidentEvent[]> {
  const items: IncidentEvent[] = [];
  let offset = 0;
  const limit = 100;
  for (;;) {
    const response = await fetch(`${CONTROL_PLANE_URL}/api/v1/incidents/${incidentId}/events?limit=${limit}&offset=${offset}`, {
      signal: AbortSignal.timeout(10_000),
    });
    const body = await response.json();
    items.push(...(body.items ?? []));
    offset += limit;
    if (!body.items?.length || offset >= body.total) break;
  }
  return items;
}

export interface RecoveryVerification {
  proposal_succeeded: boolean;
  fault_inactive: boolean;
  target_healthy: boolean;
}

export interface LiveAgentRun {
  run_id: string;
  status: string;
  current_node: string;
  remediation_proposal_id: string | null;
  recovery_verification: RecoveryVerification | null;
}

// Reads agent-runtime-service DIRECTLY (bypassing web-console) purely
// to recover this run's own real remediation_proposal_id for the
// final audit-trail assertions below -- never used to drive the
// workflow itself, which this spec only ever does through the real
// browser UI.
export async function getAgentRun(runId: string): Promise<LiveAgentRun> {
  const response = await fetch(`${AGENT_RUNTIME_URL}/api/v1/agent-runs/${runId}`, { signal: AbortSignal.timeout(10_000) });
  if (response.status !== 200) throw new Error(`GET agent run ${runId} returned ${response.status}`);
  return (await response.json()) as LiveAgentRun;
}

export async function getRemediationProposal(proposalId: string): Promise<Record<string, unknown>> {
  const response = await fetch(`${CONTROL_PLANE_URL}/api/v1/remediation-proposals/${proposalId}`, {
    signal: AbortSignal.timeout(10_000),
  });
  if (response.status !== 200) throw new Error(`GET proposal ${proposalId} returned ${response.status}`);
  return (await response.json()) as Record<string, unknown>;
}

export async function getAllRemediationEvents(proposalId: string): Promise<{ event_type: string; actor_type: string }[]> {
  const response = await fetch(`${CONTROL_PLANE_URL}/api/v1/remediation-proposals/${proposalId}/events?limit=100&offset=0`, {
    signal: AbortSignal.timeout(10_000),
  });
  const body = await response.json();
  return body.items ?? [];
}

export async function waitFor<T>(
  label: string,
  attempts: number,
  delayMs: number,
  check: () => Promise<T | null | false>,
): Promise<T> {
  for (let i = 1; i <= attempts; i++) {
    const result = await check();
    if (result) return result;
    console.log(`  attempt ${i}/${attempts}: ${label} not yet satisfied`);
    await new Promise((resolve) => setTimeout(resolve, delayMs));
  }
  throw new Error(`${label} was never satisfied after ${attempts} attempts`);
}
