// Stub for the real `server-only` package (services/web-console/node_modules/server-only),
// aliased in vitest.config.mts ONLY for tests. The real package throws
// unconditionally unless the bundler sets the `react-server` export
// condition -- which Next.js's own build does, but Vitest/Vite does
// not -- so importing the real package here would fail every single
// test that transitively imports lib/server/*, not just the one file
// actually violating the server/client boundary. This stub is a
// no-op: it does not and cannot replace the real enforcement, which
// still happens for real inside `next build`/`next dev`.
export {};
