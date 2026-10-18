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

COPY tsconfig.json next.config.ts ./
COPY app/ app/

RUN npm run build

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
