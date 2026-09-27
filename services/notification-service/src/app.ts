import Fastify, { type FastifyInstance } from "fastify";
import { healthRoutes } from "./routes/health.js";

// Builds and configures the Fastify instance without binding a port, so
// tests can use app.inject() against it directly.
export function buildApp(): FastifyInstance {
  const app = Fastify({ logger: true });

  app.register(healthRoutes);

  return app;
}
