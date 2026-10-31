# Demo walkthrough

A concrete, from-scratch path through the platform, on top of the quick start in the main [README](../README.md). Every command below is a real `make` target or a real HTTP call against the local stack — nothing here is simulated or mocked.

## 1. Start the stack

```bash
cp .env.example .env
make check
make db-up
make db-migrate
make db-status   # wait for "healthy"
```

`make db-up` starts PostgreSQL first, provisions the dedicated, least-privileged application roles (agent-runtime, web-console) directly into `.env`, applies the web-console auth schema, then brings up the rest of the stack (commerce services, observability, control-plane, investigator, agent-runtime, tool-gateway, web-console). `make db-migrate` applies this platform's own `reliability` schema via Flyway. The console at **http://127.0.0.1:3101** is the dashboard.

## 2. Sign up and create an organization

Open http://127.0.0.1:3101/register, sign up, and verify your email. In local development, the verification link is not sent anywhere — it is printed to the web-console container's own logs (`make web-console-logs`), never faked or auto-confirmed. Then create an organization and make it your session's active organization (the console does this for you after creation).

This new organization is yours — it is where the service you register in step 3 below lives, and where any incident its telemetry raises will appear. It does **not**, however, give you access to the legacy commerce-demo incidents in step 4 — see the note there.

## 3. Register a service and send real telemetry

From the console, register a new service and generate an integration credential. Configure the official OpenTelemetry SDK with the exact endpoint/headers the console renders for that service, and export one real HTTP-server-request metric. See [Telemetry onboarding](architecture/phase-16-secure-telemetry-onboarding.md) for the exact snippet shape and supported signal (metrics only — see the README's Limitations). The service's detail page will show the real sample once it lands.

## 4. Trigger a real incident from the legacy commerce demo

The repository also ships a separate, older demo path: four commerce microservices (checkout/payment/inventory/notification) wired to real Prometheus alert rules through Alertmanager. Every incident this path creates is always assigned to one fixed, pre-existing **"Legacy Local-Development Organization"** — never the organization you created in step 2, regardless of who's signed in. The console has no self-service way to join it (it already exists; there is nothing to "create"). For local development only, this repository's own Playwright fixture (`services/web-console/e2e/support/auth.ts`) joins it with a direct, documented, test-only `auth.member` insert as the dedicated `web_console` database role — the same mechanism you would need to repeat by hand to see these incidents as a real signed-in user. There is no supported way to do this outside local development, and it is not part of the self-service product.

With that membership in place (or just to watch the alert pipeline run, without needing to see the result in your own session):

```bash
make simulate-payment-outage FULL_ACCEPTANCE=true
```

⚠️ Run this only against a disposable local/demo environment — it deliberately stops a real container. Not executed as part of writing this doc; read it before running it.

This deliberately stops `payment-service` and waits for a real Prometheus alert to fire and a real Alertmanager webhook to create the incident — genuinely several minutes, including the alert rule's own `rate()` window. **The script itself restores `payment-service` as part of its own cleanup** (see `scripts/simulate-failure.sh`'s `restore_target`) — this is a real alert-ingestion-and-audit-trail demo, not a demo of the human-approved remediation workflow below; by the time anyone could act on it, the script has typically already fixed the underlying symptom itself.

## 5. Investigate and remediate through the console

This is the real, human-driven workflow — on any incident, whether from step 4 above or one you already have:

1. Open the incident and click **Start AI investigation**. This creates a durable `AgentRun` and takes you to its workspace page immediately, before any investigation work has actually happened yet.
2. Click **Run investigation**. This is a separate, explicit step that executes the agent up to its first interrupt — real evidence gathering, a real LLM-backed (or deterministic-stub, see the README) investigation report, and, if warranted, a proposed remediation.
3. If a remediation was proposed, review it and click **Approve** or **Reject**. This only *records* the decision — it does not execute anything by itself.
4. Click **Continue workflow**. This is a separate, explicit resume that actually executes an approved remediation through `tool-gateway` and then verifies recovery — or, on rejection, finalizes the run without executing anything.

Two command-line shortcuts exist but are **not** substitutes for the sequence above:

- `make investigate INCIDENT_ID=<uuid>` calls investigator-service directly and prints a one-shot investigation report. It never creates or touches a durable `AgentRun`, and there is nothing afterward to approve or resume.
- `make remediation-approve PROPOSAL_ID=<uuid>` / `make remediation-reject PROPOSAL_ID=<uuid>` record a real decision through control-plane directly — the command-line form of step 3 above — but, exactly as in the UI, this does **not** execute anything. The run still needs an authenticated **Continue workflow** resume (step 4) before remediation actually runs.

## Going deeper

- [Architecture overview](architecture/system-overview.md) and the per-phase docs under `architecture/` for full design rationale.
- [Deployment](architecture/phase-17a-deployment.md) and the [operational runbook](../deploy/README.md) for running this outside local development.
- `make help` lists every available target, including focused verification scripts for each subsystem.
