import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

let currentPathname = "/demo";

vi.mock("next/headers", () => ({
  headers: vi.fn(async () => new Headers({ "x-pathname": currentPathname })),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => currentPathname,
}));
vi.mock("../lib/server/actor", () => ({
  resolveActor: vi.fn(),
  getSessionUser: vi.fn(),
}));
vi.mock("../lib/auth/auth", () => ({
  auth: { api: { listOrganizations: vi.fn() } },
}));

import { RootShell } from "../components/shell/root-shell";
import { resolveActor, getSessionUser } from "../lib/server/actor";

const resolveActorMock = resolveActor as unknown as ReturnType<typeof vi.fn>;
const getSessionUserMock = getSessionUser as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  resolveActorMock.mockReset();
  getSessionUserMock.mockReset();
});

// Phase 18, Section 3: RootShell must handle `/demo` deliberately --
// never a global auth bypass. These prove both directions: `/demo`
// gets the dedicated demo chrome WITHOUT ever resolving a session or
// actor (so a signed-in visitor's real org never appears in that
// chrome), and every other path -- including one carrying an
// attacker-supplied `x-pathname: /demo`-shaped header, which
// middleware.ts's own real behavior (see demo-middleware.test.ts)
// never actually allows through unmodified -- still goes through the
// real, unchanged session/actor resolution.
describe("RootShell: deliberate /demo branch", () => {
  it("renders the demo shell for /demo without resolving actor or session", async () => {
    currentPathname = "/demo";
    const jsx = await RootShell({ children: <div data-testid="demo-child">demo content</div> });
    render(jsx);

    expect(screen.getByText("Recorded demo")).toBeDefined();
    expect(screen.getByTestId("demo-child")).toBeDefined();
    expect(resolveActorMock).not.toHaveBeenCalled();
    expect(getSessionUserMock).not.toHaveBeenCalled();
  });

  it("renders the demo shell for a nested /demo/* path without resolving actor or session", async () => {
    currentPathname = "/demo/incident/abc";
    const jsx = await RootShell({ children: <div data-testid="demo-child">demo content</div> });
    render(jsx);

    expect(screen.getByTestId("demo-child")).toBeDefined();
    expect(resolveActorMock).not.toHaveBeenCalled();
    expect(getSessionUserMock).not.toHaveBeenCalled();
  });

  it("still resolves session/actor normally for a real protected path, proving the demo branch is narrowly scoped", async () => {
    currentPathname = "/incidents/11111111-1111-1111-1111-111111111111";
    getSessionUserMock.mockResolvedValue(null);
    resolveActorMock.mockResolvedValue(null);

    const jsx = await RootShell({ children: <div data-testid="live-child">live content</div> });
    render(jsx);

    expect(getSessionUserMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Recorded demo")).toBeNull();
  });

  it("does not match a path that merely CONTAINS /demo as a substring, e.g. /organizations/demo-org", async () => {
    currentPathname = "/organizations/demo-org";
    getSessionUserMock.mockResolvedValue(null);
    resolveActorMock.mockResolvedValue(null);

    const jsx = await RootShell({ children: <div>x</div> });
    render(jsx);

    expect(getSessionUserMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Recorded demo")).toBeNull();
  });
});
