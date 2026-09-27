import { test } from "node:test";
import assert from "node:assert/strict";
import { buildApp } from "../src/app.js";

test("GET /health returns 200 with expected body", async () => {
  const app = buildApp();

  const response = await app.inject({ method: "GET", url: "/health" });

  assert.equal(response.statusCode, 200);
  assert.match(response.headers["content-type"] ?? "", /application\/json/);

  const body = response.json() as { status: string; service: string };
  assert.equal(body.status, "UP");
  assert.equal(body.service, "notification-service");

  await app.close();
});

test("POST /health does not return the valid health response", async () => {
  const app = buildApp();

  const response = await app.inject({ method: "POST", url: "/health" });

  assert.notEqual(response.statusCode, 200);

  await app.close();
});
