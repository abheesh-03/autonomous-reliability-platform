import type { FastifyInstance } from "fastify";

interface HealthResponse {
  status: string;
  service: string;
}

const SERVICE_NAME = "notification-service";

export async function healthRoutes(app: FastifyInstance): Promise<void> {
  app.get("/health", async (_request, reply) => {
    const body: HealthResponse = { status: "UP", service: SERVICE_NAME };
    reply.code(200);
    return body;
  });
}
