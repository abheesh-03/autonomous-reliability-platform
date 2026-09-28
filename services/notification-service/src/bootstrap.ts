import { startTelemetry } from "./telemetry.js";

// Telemetry must start — and, critically, patch the `fastify` module via
// @fastify/otel's registerOnInitialization — before ./server.js (which
// statically imports ./app.js, which imports and calls Fastify()) is
// ever evaluated. A plain top-level `import "./server.js"` in this file
// would not guarantee that ordering, since ESM hoists and evaluates all
// static imports of a module (including transitive ones) before this
// module's own top-level statements run. A dynamic import() below is
// what actually defers loading ./server.js until after startTelemetry()
// has run.
try {
  startTelemetry();
} catch (err) {
  console.error("failed to start telemetry:", err);
  process.exit(1);
}

await import("./server.js");
