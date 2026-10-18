import { describe, expect, it } from "vitest";
import { parseIncidentListSearchParams } from "../lib/incident-query";

describe("parseIncidentListSearchParams", () => {
  it("passes through valid status/severity/source filters", () => {
    const parsed = parseIncidentListSearchParams({
      status: "open",
      severity: "critical",
      source: "alertmanager",
    });
    expect(parsed.status).toBe("open");
    expect(parsed.severity).toBe("critical");
    expect(parsed.source).toBe("alertmanager");
    expect(parsed.limit).toBe(20);
    expect(parsed.offset).toBe(0);
  });

  it("silently drops an unrecognized status instead of forwarding it", () => {
    const parsed = parseIncidentListSearchParams({ status: "deleted-by-hacker" });
    expect(parsed.status).toBeUndefined();
  });

  it("silently drops an unrecognized severity instead of forwarding it", () => {
    const parsed = parseIncidentListSearchParams({ severity: "catastrophic" });
    expect(parsed.severity).toBeUndefined();
  });

  it("clamps an out-of-range limit into [1, 100]", () => {
    expect(parseIncidentListSearchParams({ limit: "99999" }).limit).toBe(100);
    expect(parseIncidentListSearchParams({ limit: "0" }).limit).toBe(1);
    expect(parseIncidentListSearchParams({ limit: "-5" }).limit).toBe(1);
  });

  it("defaults a non-numeric limit rather than forwarding garbage", () => {
    expect(parseIncidentListSearchParams({ limit: "not-a-number" }).limit).toBe(20);
  });

  it("clamps a negative offset to zero", () => {
    expect(parseIncidentListSearchParams({ offset: "-10" }).offset).toBe(0);
  });

  it("takes the first value when a param is duplicated in the URL", () => {
    const parsed = parseIncidentListSearchParams({ status: ["open", "closed"] });
    expect(parsed.status).toBe("open");
  });

  it("trims and bounds an overlong source value rather than rejecting the whole request", () => {
    const longSource = "a".repeat(500);
    const parsed = parseIncidentListSearchParams({ source: `  ${longSource}  ` });
    expect(parsed.source?.length).toBe(200);
  });

  it("treats an empty source as absent", () => {
    const parsed = parseIncidentListSearchParams({ source: "   " });
    expect(parsed.source).toBeUndefined();
  });
});
