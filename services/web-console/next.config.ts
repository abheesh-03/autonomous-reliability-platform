import type { NextConfig } from "next";

// `output: "standalone"` so the production Docker image copies only the
// self-contained server bundle (.next/standalone) -- never the full
// node_modules tree -- matching the minimal-runtime-image convention
// every other service in this repository already follows.
const nextConfig: NextConfig = {
  output: "standalone",
};

export default nextConfig;
