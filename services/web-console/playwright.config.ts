import { defineConfig } from "@playwright/test";

// Gate F: ONE real end-to-end acceptance test against the live local
// stack (docker compose), never a mocked backend. This never starts
// its own web server -- it expects web-console (and every Phase 0-8
// backend it depends on) to already be running via docker compose,
// exactly like scripts/verify-remediation.sh expects the same live
// stack. The full remediation workflow this spec drives genuinely
// takes several real minutes (sustained failing traffic until a real
// Prometheus alert fires, then several more minutes for its rate()
// window to naturally recover) -- timeouts here are generous and
// intentionally mirror verify-remediation.sh's own bounded-retry
// windows, never shortened to make the test "faster" than the real
// system it is observing.
export default defineConfig({
  testDir: "./e2e",
  timeout: 20 * 60 * 1000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.WEB_CONSOLE_BASE_URL ?? "http://127.0.0.1:3101",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
