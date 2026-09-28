# Builder stage: installs dependencies, typechecks, tests, and compiles
# TypeScript to JavaScript. Host Node differs from the target version, so
# this build is also the authoritative local validation path (see Makefile).
FROM node:24 AS builder
WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json ./
COPY src/ src/
COPY test/ test/

RUN npm run typecheck
RUN npm test
RUN npm run build

# Drop devDependencies (typescript, tsx, @types/node) now that the build
# and tests are done — only production dependencies are needed at runtime.
RUN npm prune --omit=dev

# Runtime stage: smaller image, same Node major version, compiled JS only.
FROM node:24-slim
WORKDIR /app

COPY --from=builder /build/node_modules ./node_modules
COPY --from=builder /build/dist ./dist
COPY --from=builder /build/package.json ./package.json

USER node

EXPOSE 8083

# dist/bootstrap.js (not dist/server.js) is the entrypoint: it starts
# OpenTelemetry (patching the `fastify` module via @fastify/otel) before
# dynamically importing dist/server.js, which is what actually
# constructs and starts the Fastify app — required ordering for
# instrumentation to observe the application at all (see src/bootstrap.ts).
CMD ["node", "dist/bootstrap.js"]
