import { test } from "node:test";
import assert from "node:assert/strict";
import { buildApp } from "../src/app.js";

const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const validPayload = {
  checkout_id: "chk_12345",
  kind: "ORDER_CONFIRMATION",
  recipient: "customer@example.com",
};

interface NotificationResponseBody {
  notification_id: string;
  checkout_id: string;
  kind: string;
  recipient: string;
  status: string;
}

test("POST /notifications returns 200 with expected body for a valid request", async () => {
  const app = buildApp();

  const response = await app.inject({ method: "POST", url: "/notifications", payload: validPayload });

  assert.equal(response.statusCode, 200);
  assert.match(response.headers["content-type"] ?? "", /application\/json/);

  const body = response.json() as NotificationResponseBody;
  assert.equal(body.checkout_id, validPayload.checkout_id);
  assert.equal(body.kind, validPayload.kind);
  assert.equal(body.recipient, validPayload.recipient);
  assert.equal(body.status, "ACCEPTED");
  assert.match(body.notification_id, uuidPattern);

  await app.close();
});

test("POST /notifications rejects an empty checkout_id", async () => {
  const app = buildApp();

  const response = await app.inject({
    method: "POST",
    url: "/notifications",
    payload: { checkout_id: "", kind: "ORDER_CONFIRMATION", recipient: "customer@example.com" },
  });

  assert.equal(response.statusCode, 400);

  await app.close();
});

test("POST /notifications rejects a missing checkout_id", async () => {
  const app = buildApp();

  const response = await app.inject({
    method: "POST",
    url: "/notifications",
    payload: { kind: "ORDER_CONFIRMATION", recipient: "customer@example.com" },
  });

  assert.equal(response.statusCode, 400);

  await app.close();
});

test("POST /notifications rejects an unsupported kind", async () => {
  const app = buildApp();

  const response = await app.inject({
    method: "POST",
    url: "/notifications",
    payload: { checkout_id: "chk_12345", kind: "PASSWORD_RESET", recipient: "customer@example.com" },
  });

  assert.equal(response.statusCode, 400);

  await app.close();
});

test("POST /notifications rejects an empty recipient", async () => {
  const app = buildApp();

  const response = await app.inject({
    method: "POST",
    url: "/notifications",
    payload: { checkout_id: "chk_12345", kind: "ORDER_CONFIRMATION", recipient: "" },
  });

  assert.equal(response.statusCode, 400);

  await app.close();
});

test("POST /notifications rejects a missing recipient", async () => {
  const app = buildApp();

  const response = await app.inject({
    method: "POST",
    url: "/notifications",
    payload: { checkout_id: "chk_12345", kind: "ORDER_CONFIRMATION" },
  });

  assert.equal(response.statusCode, 400);

  await app.close();
});

test("GET /notifications does not succeed", async () => {
  const app = buildApp();

  const response = await app.inject({ method: "GET", url: "/notifications" });

  assert.notEqual(response.statusCode, 200);

  await app.close();
});

test("POST /notifications produces different notification_id values across calls", async () => {
  const app = buildApp();

  const first = await app.inject({ method: "POST", url: "/notifications", payload: validPayload });
  const second = await app.inject({ method: "POST", url: "/notifications", payload: validPayload });

  const firstBody = first.json() as NotificationResponseBody;
  const secondBody = second.json() as NotificationResponseBody;

  assert.notEqual(firstBody.notification_id, secondBody.notification_id);

  await app.close();
});
