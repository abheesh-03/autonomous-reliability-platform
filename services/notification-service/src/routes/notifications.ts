import type { FastifyInstance } from "fastify";
import type { NotificationRequest, NotificationResponse } from "../types/notification.js";
import { createNotification } from "../services/notification.js";

// Request validation uses Fastify's built-in JSON schema (Ajv) support
// rather than adding a separate validation library.
const notificationRequestSchema = {
  type: "object",
  required: ["checkout_id", "kind", "recipient"],
  properties: {
    checkout_id: { type: "string", minLength: 1, maxLength: 100 },
    kind: { type: "string", const: "ORDER_CONFIRMATION" },
    recipient: { type: "string", minLength: 1, maxLength: 254 },
  },
} as const;

export async function notificationRoutes(app: FastifyInstance): Promise<void> {
  app.post<{ Body: NotificationRequest }>(
    "/notifications",
    { schema: { body: notificationRequestSchema } },
    async (request, reply) => {
      const body: NotificationResponse = createNotification(request.body);
      reply.code(200);
      return body;
    },
  );
}
