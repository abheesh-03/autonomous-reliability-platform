import { buildApp } from "./app.js";
import { shutdownTelemetry } from "./telemetry.js";

const HOST = "0.0.0.0";
const PORT = 8083;

async function main(): Promise<void> {
  const app = buildApp();

  try {
    await app.listen({ host: HOST, port: PORT });
  } catch (err) {
    app.log.error(err);
    // Telemetry has already started successfully by this point (this
    // module is only ever loaded, via bootstrap.ts's dynamic import,
    // after startTelemetry() returns), so it still gets a chance to
    // flush before the process exits on a startup failure.
    try {
      await shutdownTelemetry();
    } catch (shutdownErr) {
      app.log.error(shutdownErr);
    }
    process.exit(1);
  }

  const shutdown = async (signal: string): Promise<void> => {
    app.log.info(`received ${signal}, shutting down gracefully`);
    try {
      // Fastify closes first, so no further requests/spans are created;
      // telemetry shutdown (flush + close exporters) only happens
      // afterward, with its own bounded, independent timeout.
      await app.close();
      await shutdownTelemetry();
      process.exit(0);
    } catch (err) {
      app.log.error(err);
      process.exit(1);
    }
  };

  process.on("SIGTERM", () => void shutdown("SIGTERM"));
  process.on("SIGINT", () => void shutdown("SIGINT"));
}

main();
