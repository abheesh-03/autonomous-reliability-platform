"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Check, Copy, Loader2, Plus, ShieldAlert, Trash2 } from "lucide-react";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "../ui/dialog";
import { ConfirmDialog } from "../ui/confirm-dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../ui/tabs";
import { useToast } from "../ui/toast";
import { formatTimestamp } from "../../lib/format";
import type { IntegrationCredential } from "../../lib/types/integration";

/**
 * Phase 16 Gate 7: the real onboarding flow for one registered
 * service -- generate a real credential (the secret is shown exactly
 * once, straight from control-plane's own one-time response, never
 * persisted or re-fetchable afterward), then real, copyable setup
 * instructions for Java/Python/Go/Node.js.
 *
 * CORRECTION ROUND (independent review, item 3): the previous round's
 * snippets set `OTEL_EXPORTER_OTLP_PROTOCOL=http/json` and pointed a
 * GENERIC `OTEL_EXPORTER_OTLP_ENDPOINT` at this platform's base URL --
 * two separate real bugs. Independent verification of the actual
 * official OpenTelemetry Python SDK exporter
 * (`opentelemetry-exporter-otlp-proto-http`) found it hardcodes
 * protobuf (`Content-Type: application/x-protobuf`) and has NO JSON
 * code path at all, so `http/json` was never real for that exporter
 * regardless of this env var. And the generic endpoint env var gets
 * the SPEC'S OWN `/v1/metrics` suffix auto-appended by the exporter --
 * never this platform's real, custom
 * `/api/v1/telemetry/otlp/v1/metrics` route -- so traffic sent that
 * way would 404, not reach this endpoint at all.
 *
 * Every snippet below now uses `http/protobuf` (the real OTLP spec
 * default, and the one actually verified end-to-end this round against
 * the official Python SDK/exporter -- see
 * docs/architecture/phase-16-secure-telemetry-onboarding.md Gate 3) and
 * the signal-SPECIFIC `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` env var set
 * to the exact, full ingestion URL (used verbatim by a spec-compliant
 * exporter -- never suffixed) instead of the generic, signal-agnostic
 * one.
 *
 * A THIRD real finding from that same verification: the official
 * SDK's own metrics exporter defaults to CUMULATIVE temporality for
 * histograms (not DELTA) unless told otherwise -- this endpoint
 * requires DELTA outright (item 1) and a CUMULATIVE export is a clean
 * 400, not silently accepted. `OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_
 * PREFERENCE=delta` is the real, spec-defined, zero-code env var that
 * makes the official SDK emit DELTA -- every snippet below sets it;
 * without it, even the corrected protocol/endpoint above would still
 * fail with a 400.
 *
 * Gate 7: "Do not pretend that all SDK languages have been
 * independently validated." Only the Python path (the official SDK,
 * this round) was actually exercised end-to-end -- every other
 * language tab says so explicitly, not just the ones that weren't
 * tried; their corrected protocol/endpoint values follow each SDK's
 * own documented OTLP/HTTP configuration but have NOT been
 * independently run against this backend.
 */

const INGEST_PATH = "/api/v1/telemetry/otlp/v1/metrics";

function snippetFor(language: string, bearerToken: string, otlpEndpoint: string): string {
  const metricsEndpoint = `${otlpEndpoint.replace(/\/+$/, "")}${INGEST_PATH}`;
  switch (language) {
    case "python":
      return `pip install opentelemetry-distro opentelemetry-exporter-otlp-proto-http
opentelemetry-bootstrap -a install

export OTEL_SERVICE_NAME="your-service"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
export OTEL_EXPORTER_OTLP_METRICS_ENDPOINT="${metricsEndpoint}"
export OTEL_EXPORTER_OTLP_METRICS_HEADERS="Authorization=Bearer ${bearerToken}"
export OTEL_METRIC_EXPORT_INTERVAL="5000"
export OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE="delta"

opentelemetry-instrument python your_app.py`;
    case "node":
      return `npm install --save @opentelemetry/sdk-node @opentelemetry/auto-instrumentations-node \\
  @opentelemetry/exporter-metrics-otlp-proto

export OTEL_SERVICE_NAME="your-service"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
export OTEL_EXPORTER_OTLP_METRICS_ENDPOINT="${metricsEndpoint}"
export OTEL_EXPORTER_OTLP_METRICS_HEADERS="Authorization=Bearer ${bearerToken}"
export OTEL_METRIC_EXPORT_INTERVAL="5000"
export OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE="delta"

node --require @opentelemetry/auto-instrumentations-node/register your-app.js`;
    case "java":
      return `# Download the official OpenTelemetry Java agent:
# https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases

export OTEL_SERVICE_NAME="your-service"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
export OTEL_EXPORTER_OTLP_METRICS_ENDPOINT="${metricsEndpoint}"
export OTEL_EXPORTER_OTLP_METRICS_HEADERS="Authorization=Bearer ${bearerToken}"
export OTEL_METRIC_EXPORT_INTERVAL="5000"
export OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE="delta"

java -javaagent:opentelemetry-javaagent.jar -jar your-app.jar`;
    case "go":
      return `go get go.opentelemetry.io/otel \\
  go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp \\
  go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp

export OTEL_SERVICE_NAME="your-service"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
export OTEL_EXPORTER_OTLP_METRICS_ENDPOINT="${metricsEndpoint}"
export OTEL_EXPORTER_OTLP_METRICS_HEADERS="Authorization=Bearer ${bearerToken}"
export OTEL_METRIC_EXPORT_INTERVAL="5000"
export OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE="delta"

# Wrap your HTTP handlers with otelhttp.NewHandler(...); the Go SDK's
# otlpmetrichttp exporter also defaults to protobuf, so no extra
# protocol configuration is required beyond the endpoint/headers above.`;
    default:
      return "";
  }
}

const LANGUAGES: { id: string; label: string; validated: boolean }[] = [
  { id: "python", label: "Python", validated: true },
  { id: "node", label: "Node.js", validated: false },
  { id: "java", label: "Java", validated: false },
  { id: "go", label: "Go", validated: false },
];

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 2000);
        } catch {
          // Per-viewer clipboard-permission failure only -- never
          // throws, never blocks the credential from being read/
          // selected manually instead.
        }
      }}
    >
      {copied ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : <Copy className="h-3.5 w-3.5" aria-hidden="true" />}
      {copied ? "Copied" : label}
    </Button>
  );
}

export function IntegrationSetupFlow({
  serviceId,
  initialCredentials,
  canManage,
  otlpEndpoint,
}: {
  serviceId: string;
  initialCredentials: IntegrationCredential[];
  canManage: boolean;
  otlpEndpoint: string;
}) {
  const router = useRouter();
  const toast = useToast();
  const [credentials, setCredentials] = useState(initialCredentials);
  const [generating, setGenerating] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [newSecret, setNewSecret] = useState<{ token: string; credentialId: string } | null>(null);
  const [language, setLanguage] = useState("python");

  async function generate() {
    setGenerating(true);
    try {
      const response = await fetch(`/api/services/${serviceId}/integrations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        const message =
          body && typeof body === "object" && typeof body.message === "string" ? body.message : "Could not generate a credential.";
        toast({ title: "Could not generate credential", description: message, tone: "critical" });
        return;
      }
      setCredentials((prev) => [body.credential, ...prev]);
      setNewSecret({ token: body.bearer_token, credentialId: body.credential.credential_id });
      router.refresh();
    } catch {
      toast({ title: "Could not reach the server", tone: "critical" });
    } finally {
      setGenerating(false);
    }
  }

  async function revoke(integrationId: string) {
    setRevoking(integrationId);
    try {
      const response = await fetch(`/api/services/${serviceId}/integrations/${integrationId}/revoke`, {
        method: "POST",
      });
      if (!response.ok) {
        toast({ title: "Could not revoke credential", tone: "critical" });
        return;
      }
      setCredentials((prev) =>
        prev.map((c) => (c.id === integrationId ? { ...c, status: "revoked", revoked_at: new Date().toISOString() } : c)),
      );
      toast({ title: "Credential revoked", tone: "success" });
      router.refresh();
    } catch {
      toast({ title: "Could not reach the server", tone: "critical" });
    } finally {
      setRevoking(null);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-fg">OpenTelemetry integration</h3>
          <p className="mt-0.5 text-xs text-fg-muted">
            Authenticated metrics ingestion for this service only -- a credential never grants access to any other
            service or organization.
          </p>
        </div>
        {canManage ? (
          <Button onClick={generate} loading={generating} disabled={generating}>
            <Plus className="h-4 w-4" aria-hidden="true" />
            Generate credential
          </Button>
        ) : (
          <Badge tone="neutral">Requires OWNER / ADMIN / ENGINEER</Badge>
        )}
      </div>

      {credentials.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-4 text-sm text-fg-muted">
          No integration credentials yet. Generate one to connect a real external application.
        </div>
      ) : (
        <ul className="space-y-2">
          {credentials.map((cred) => (
            <li
              key={cred.id}
              className="flex items-center justify-between gap-3 rounded-lg border border-border bg-surface px-3 py-2.5"
            >
              <div className="min-w-0">
                <p className="truncate font-mono text-xs text-fg">{cred.credential_id}</p>
                <p className="mt-0.5 text-xs text-fg-subtle">
                  Created {formatTimestamp(cred.created_at)}
                  {cred.last_verified_telemetry_at
                    ? ` · last telemetry ${formatTimestamp(cred.last_verified_telemetry_at)}`
                    : " · no telemetry observed yet"}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <Badge tone={cred.status === "active" ? "success" : "neutral"} dot>
                  {cred.status}
                </Badge>
                {canManage && cred.status === "active" && (
                  <ConfirmDialog
                    trigger={
                      <DialogTrigger asChild>
                        <Button variant="ghost" size="icon" aria-label="Revoke credential" disabled={revoking === cred.id}>
                          {revoking === cred.id ? (
                            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                          ) : (
                            <Trash2 className="h-4 w-4" aria-hidden="true" />
                          )}
                        </Button>
                      </DialogTrigger>
                    }
                    title="Revoke this credential?"
                    description="Any external application using it will immediately be denied -- this cannot be undone. A new credential can be generated separately."
                    confirmLabel="Revoke"
                    onConfirm={() => revoke(cred.id)}
                  />
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      <Dialog open={newSecret !== null} onOpenChange={(open) => !open && setNewSecret(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ShieldAlert className="h-4 w-4 text-warning-fg" aria-hidden="true" />
              Credential generated
            </DialogTitle>
            <DialogDescription>
              This is shown once. Copy it now -- it cannot be retrieved again (only revoked and replaced).
            </DialogDescription>
          </DialogHeader>

          {newSecret && (
            <div className="space-y-4">
              <div className="flex items-center gap-2 rounded-lg border border-border bg-surface-sunken p-3">
                <code className="flex-1 overflow-x-auto whitespace-nowrap font-mono text-xs text-fg">{newSecret.token}</code>
                <CopyButton text={newSecret.token} label="Copy" />
              </div>

              <div>
                <p className="mb-2 text-sm font-medium text-fg">Configure your application</p>
                <Tabs value={language} onValueChange={setLanguage}>
                  <TabsList>
                    {LANGUAGES.map((lang) => (
                      <TabsTrigger key={lang.id} value={lang.id}>
                        {lang.label}
                      </TabsTrigger>
                    ))}
                  </TabsList>
                  {LANGUAGES.map((lang) => (
                    <TabsContent key={lang.id} value={lang.id} className="mt-3">
                      {!lang.validated && (
                        <p className="mb-2 flex items-center gap-1.5 text-xs text-warning-fg">
                          <ShieldAlert className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                          This configuration has not been independently end-to-end validated this round -- it follows
                          the official OpenTelemetry {lang.label} SDK&rsquo;s own documented OTLP/HTTP configuration.
                        </p>
                      )}
                      {lang.validated && (
                        <p className="mb-2 flex items-center gap-1.5 text-xs text-success-fg">
                          <Check className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                          Verified end-to-end this round against the real, official OpenTelemetry Python SDK and
                          HTTP metrics exporter (protobuf) -- not merely this platform&rsquo;s own hand-built
                          samples/otel-sample-app/ JSON client, which is a separate, simpler walkthrough.
                        </p>
                      )}
                      <div className="relative">
                        <pre className="max-h-64 overflow-auto rounded-lg border border-border bg-surface-sunken p-3 text-xs text-fg-muted">
                          <code>{snippetFor(lang.id, newSecret.token, otlpEndpoint)}</code>
                        </pre>
                        <div className="mt-2 flex justify-end">
                          <CopyButton text={snippetFor(lang.id, newSecret.token, otlpEndpoint)} label="Copy snippet" />
                        </div>
                      </div>
                    </TabsContent>
                  ))}
                </Tabs>
              </div>

              <p className="text-xs text-fg-subtle">
                Submits to <code className="font-mono">{INGEST_PATH}</code>. Once your application starts emitting
                real HTTP server request metrics, this service&rsquo;s connection status below will change to
                &ldquo;Receiving telemetry.&rdquo;
              </p>
            </div>
          )}

          <DialogFooter>
            <Button onClick={() => setNewSecret(null)}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
