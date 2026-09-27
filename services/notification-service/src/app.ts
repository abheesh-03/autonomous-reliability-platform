import Fastify, { type FastifyInstance } from "fastify";
import { healthRoutes } from "./routes/health.js";
import { notificationRoutes } from "./routes/notifications.js";

// Builds and configures the Fastify instance without binding a port, so
// tests can use app.inject() against it directly.
export function buildApp(): FastifyInstance {
  const app = Fastify({ logger: true });

  app.register(healthRoutes);
  app.register(notificationRoutes);

  return app;
}
