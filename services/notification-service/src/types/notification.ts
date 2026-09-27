// This phase supports exactly one notification kind and one outcome
// status — both are intentionally narrow, not speculative.
export type NotificationKind = "ORDER_CONFIRMATION";
export type NotificationStatus = "ACCEPTED";

export interface NotificationRequest {
  checkout_id: string;
  kind: NotificationKind;
  recipient: string;
}

export interface NotificationResponse {
  notification_id: string;
  checkout_id: string;
  kind: NotificationKind;
  recipient: string;
  status: NotificationStatus;
}
