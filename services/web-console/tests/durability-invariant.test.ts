import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

// Strips `//`-prefixed comment lines before matching -- this repo's
// own convention explains the ABSENCE of a resume call in prose
// (e.g. "This handler NEVER calls POST .../resume"), which would
// otherwise produce a false positive against the exact substring
// this test is trying to rule out of actual CODE.
function nonCommentSource(path: string): string {
  const raw = readFileSync(join(ROOT, path), "utf-8");
  return raw
    .split("\n")
    .filter((line) => !line.trim().startsWith("//"))
    .join("\n");
}

// Phase 7's core durability invariant: the caller must receive the
// durable run_id BEFORE any fallible graph execution/resume begins.
// These are static source checks, not just behavioral mocks (see
// start-investigation-route.test.ts's own dynamic proof) -- a direct
// textual guarantee that the string "/resume" never appears in actual
// CODE (comments excluded -- see nonCommentSource above) in Stage 4's
// own BFF or Client Component, now or in a future accidental
// reintroduction.
describe("durable run-id-before-execution invariant", () => {
  it("the start-investigation Route Handler never calls /resume", () => {
    const source = nonCommentSource("app/api/incidents/[incidentId]/investigations/route.ts");
    expect(source).not.toMatch(/\/resume/);
  });

  it("the agent-runtime server client's createAgentRun path never calls /resume", () => {
    // Scoped to createAgentRun's own function body -- Gate B
    // legitimately added a separate resumeAgentRun export to this
    // same file (called only from a separate resume Route Handler,
    // never from createAgentRun or the start-investigation route), so
    // a whole-file check would now false-positive on that unrelated,
    // intentional addition.
    const source = nonCommentSource("lib/server/agent-runtime-client.ts");
    const match = source.match(/export async function createAgentRun[\s\S]*?\n}\n/);
    expect(match).not.toBeNull();
    expect(match![0]).not.toMatch(/\/resume/);
  });

  it("the StartInvestigationControl Client Component never calls /resume and navigates with the real run_id after success", () => {
    const source = nonCommentSource("components/StartInvestigationControl.tsx");
    expect(source).not.toMatch(/\/resume/);
    expect(source).toMatch(/router\.push\(`\/agent-runs\/\$\{runId\}`\)/);
  });
});
