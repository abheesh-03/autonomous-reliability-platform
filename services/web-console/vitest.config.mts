import path from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // The real `server-only` package throws unless the bundler sets
      // the `react-server` export condition, which Next.js's own
      // build does but Vitest does not -- see tests/stubs/server-only.ts.
      "server-only": path.resolve(dirname, "tests/stubs/server-only.ts"),
      // Mirrors tsconfig.json's own "@/*" -> "./*" path mapping --
      // Next.js's own bundler (and `tsc`) already resolve this; Vitest
      // needs the same alias explicitly, or any file importing via
      // "@/..." (e.g. lib/server/actor.ts's "@/lib/auth/auth") fails
      // to even load under Vitest, failing every test in that file's
      // whole import graph before a single test can run.
      "@": dirname,
    },
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.{ts,tsx}"],
    setupFiles: ["tests/setup.ts"],
    env: {
      // lib/auth/auth.ts requires this at MODULE LOAD time (never a
      // real value -- just enough for any test file that imports it,
      // even transitively via lib/server/actor.ts, to load at all).
      // Every test that actually exercises auth behavior still mocks
      // auth.api.* itself; this only satisfies the top-level
      // requiredEnv() guard so the import graph doesn't throw first.
      BETTER_AUTH_SECRET: "test-only-not-a-real-secret-at-least-32-chars-long",
      // lib/server/actor.ts's signAssertion() reads this directly (not
      // via a settings object) every time a real actor successfully
      // resolves -- needed for any test exercising a Route Handler's
      // or Server Component's authenticated happy path.
      SERVICE_ASSERTION_SIGNING_SECRET: "test-only-not-a-real-secret-at-least-32-chars-long",
    },
  },
});
