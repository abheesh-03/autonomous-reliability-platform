import { defineConfig } from "@playwright/test";

// Run after `npm run build` and copying .next/static into
// .next/standalone/.next/static (the same layout as the Docker image).
// This needs only web-console: no Docker, database, or live backend.
export default defineConfig({
  testDir: "./e2e",
  testMatch: "demo-recorded-experience.spec.ts",
  grepInvert: /signed-in visitor/,
  timeout: 30_000,
  workers: 1,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:3218",
    browserName: "chromium",
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
      : undefined,
  },
  webServer: {
    command: "node .next/standalone/server.js",
    url: "http://127.0.0.1:3218/demo",
    timeout: 30_000,
    reuseExistingServer: false,
    env: {
      HOSTNAME: "127.0.0.1",
      PORT: "3218",
      BETTER_AUTH_SECRET: "offline-demo-test-secret-not-a-real-credential",
      SERVICE_ASSERTION_SIGNING_SECRET: "offline-demo-test-assertion-not-a-real-credential",
      CONTROL_PLANE_REQUIRE_ORGANIZATION_CONTEXT: "true",
      WEB_CONSOLE_TRUSTED_ORIGIN: "http://127.0.0.1:3218",
      WEB_CONSOLE_DB_HOST: "127.0.0.1",
      WEB_CONSOLE_DB_PORT: "9",
      WEB_CONSOLE_CONTROL_PLANE_URL: "http://127.0.0.1:9",
      WEB_CONSOLE_AGENT_RUNTIME_URL: "http://127.0.0.1:9",
    },
  },
});
