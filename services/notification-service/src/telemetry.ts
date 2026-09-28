import { NodeSDK } from "@opentelemetry/sdk-node";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { OTLPMetricExporter } from "@opentelemetry/exporter-metrics-otlp-http";
import { PeriodicExportingMetricReader } from "@opentelemetry/sdk-metrics";
import { HttpInstrumentation } from "@opentelemetry/instrumentation-http";
// @fastify/otel's type declarations (`export =` + a namespace exposing
// both a named export and a synthetic `default`) don't resolve cleanly
// through a default import under this project's NodeNext + esModuleInterop
// config — `import FastifyOtelInstrumentation from "@fastify/otel"`
// type-checks as the whole namespace, not the class, and fails to
// compile ("not constructable"). The named import below resolves to
// the actual class correctly; confirmed by a real `tsc --noEmit` run.
import { FastifyOtelInstrumentation } from "@fastify/otel";

// PeriodicExportingMetricReader's own exportIntervalMillis default
// (60000) is NOT env-aware on its own — confirmed by inspecting the
// installed package source — unlike NodeSDK's traceExporter option
// below, whose BatchSpanProcessor IS constructed by NodeSDK itself via
// an env-aware helper that honors OTEL_BSP_SCHEDULE_DELAY. So the
// metric export interval is read from OTEL_METRIC_EXPORT_INTERVAL here
// explicitly, matching the same short-interval convention used by the
// other three services.
const DEFAULT_METRIC_EXPORT_INTERVAL_MILLIS = 60000;
const metricExportIntervalMillis =
  Number(process.env.OTEL_METRIC_EXPORT_INTERVAL) || DEFAULT_METRIC_EXPORT_INTERVAL_MILLIS;

const TELEMETRY_SHUTDOWN_TIMEOUT_MILLIS = 10000;

// No `resource`, `serviceName`, or `resourceDetectors` option is passed
// below — NodeSDK's own default resource detectors
// ([envDetector, processDetector, hostDetector]) already read
// OTEL_SERVICE_NAME and OTEL_RESOURCE_ATTRIBUTES from the environment,
// so the service name is never hard-coded here.
const sdk = new NodeSDK({
  traceExporter: new OTLPTraceExporter(),
  metricReaders: [
    new PeriodicExportingMetricReader({
      exporter: new OTLPMetricExporter(),
      exportIntervalMillis: metricExportIntervalMillis,
    }),
  ],
  instrumentations: [
    new HttpInstrumentation(),
    // registerOnInitialization patches the `fastify` module itself at
    // SDK-start time, so any Fastify instance constructed afterward is
    // auto-instrumented with no application-level app.register() call
    // needed — this only works if telemetry starts before `fastify`
    // (and anything importing it) is ever imported, which is why this
    // module is started from a dedicated bootstrap entrypoint before
    // ./server.js is dynamically imported.
    new FastifyOtelInstrumentation({ registerOnInitialization: true }),
  ],
});

export function startTelemetry(): void {
  sdk.start();
}

export async function shutdownTelemetry(): Promise<void> {
  await Promise.race([
    sdk.shutdown(),
    new Promise<never>((_resolve, reject) => {
      setTimeout(
        () => reject(new Error("telemetry shutdown timed out")),
        TELEMETRY_SHUTDOWN_TIMEOUT_MILLIS,
      );
    }),
  ]);
}
