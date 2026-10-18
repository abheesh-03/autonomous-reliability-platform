// Container healthcheck target only (docker-compose.yml, Dockerfile
// HEALTHCHECK). Deliberately returns a minimal, bounded, static body --
// no backend dependency, no environment value, nothing that could ever
// leak a secret. Stage 1 has no backend calls to report on at all.
export function GET() {
  return Response.json({ status: "UP" });
}
