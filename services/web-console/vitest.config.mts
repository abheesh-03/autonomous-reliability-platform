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
    },
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.{ts,tsx}"],
    setupFiles: ["tests/setup.ts"],
  },
});
