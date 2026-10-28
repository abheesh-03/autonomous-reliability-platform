# Builder stage: installs dependencies and produces the standalone
# production server bundle. CI (.github/workflows/ci.yml) is the
# authoritative place for typecheck/lint/unit tests -- this build does
# NOT re-run them, so the image build stays focused on proving the
# production application actually builds and packages, without
# doubling CI's own test time for no benefit.
FROM node:24-slim AS builder
WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json next.config.ts postcss.config.mjs ./
COPY app/ app/
COPY lib/ lib/
COPY components/ components/

# lib/auth/auth.ts constructs its Better Auth instance eagerly at
# MODULE LOAD time (`export const auth = betterAuth({ secret:
# requiredEnv("BETTER_AUTH_SECRET"), ... })`), so `next build`'s route-
# configuration-collection phase requires a non-empty value even
# though this build performs no real database/auth operation at all.
# A cryptographically random, ephemeral, build-only value -- generated
# fresh in THIS shell command only, via Node's own built-in `crypto`
# module (already present in this exact base image, no new tool
# dependency) -- never persisted as an ENV/ARG in any image layer,
# never logged (Docker/BuildKit never echoes a command substitution's
# resolved value), and confirmed to leave no trace in the compiled
# .next/ output (its only use, Better Auth's own session signing, never
# touches a static asset or a NEXT_PUBLIC_ variable). The RUNTIME
# container (this Dockerfile's own "runner" stage below) never
# receives this value at all -- it reads its own separate, persistent
# BETTER_AUTH_SECRET from the real environment docker-compose.yml
# injects, completely independent of this build-time value.
RUN BETTER_AUTH_SECRET="$(node -e "console.log(require('crypto').randomBytes(32).toString('hex'))")" npm run build

# Runtime stage: Next.js standalone output only -- never the full
# node_modules tree or source files, matching the minimal-runtime-image
# convention every other service in this repository already follows.
FROM node:24-slim AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3101
ENV HOSTNAME=0.0.0.0

# The standalone build's own node_modules (only the packages actually
# needed at runtime) and server entrypoint, plus the static/public
# assets Next.js does not bundle into server.js itself.
COPY --from=builder /build/.next/standalone ./
COPY --from=builder /build/.next/static ./.next/static

USER node

EXPOSE 3101

CMD ["node", "server.js"]
