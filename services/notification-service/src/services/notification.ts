import { randomUUID } from "node:crypto";
import type { NotificationRequest, NotificationResponse } from "../types/notification.js";

// Simulates accepting a notification trigger. No real message is sent
// (no email/SMS/push provider), nothing is persisted, and there is no
// queue — every valid request currently succeeds deterministically,
// aside from the generated notification_id.
export function createNotification(request: NotificationRequest): NotificationResponse {
  return {
    notification_id: randomUUID(),
    checkout_id: request.checkout_id,
    kind: request.kind,
    recipient: request.recipient,
    status: "ACCEPTED",
  };
}
