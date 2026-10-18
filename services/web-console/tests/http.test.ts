import { describe, expect, it, vi } from "vitest";
import { fetchAllPages, ok, fail, type BackendResult, type PageEnvelope } from "../lib/server/http";

interface Item {
  id: number;
}

type FetchPageMock = ReturnType<typeof vi.fn<(limit: number, offset: number) => Promise<BackendResult<PageEnvelope<Item>>>>>;

describe("fetchAllPages", () => {
  it("1. returns everything from a single page when total fits in one request", async () => {
    const fetchPage: FetchPageMock = vi
      .fn()
      .mockResolvedValue(ok({ items: [{ id: 1 }, { id: 2 }], total: 2, limit: 100, offset: 0 }));
    const result = await fetchAllPages(fetchPage);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toEqual([{ id: 1 }, { id: 2 }]);
    }
    expect(fetchPage).toHaveBeenCalledTimes(1);
  });

  it("1b. a genuinely empty history (total=0) is a real success, not a failure", async () => {
    const fetchPage: FetchPageMock = vi
      .fn()
      .mockResolvedValue(ok({ items: [], total: 0, limit: 100, offset: 0 }));
    const result = await fetchAllPages(fetchPage);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data).toEqual([]);
    }
  });

  it("2. follows multiple pages until the reported total is reached", async () => {
    const fetchPage: FetchPageMock = vi
      .fn()
      .mockResolvedValueOnce(ok({ items: [{ id: 1 }, { id: 2 }], total: 5, limit: 2, offset: 0 }))
      .mockResolvedValueOnce(ok({ items: [{ id: 3 }, { id: 4 }], total: 5, limit: 2, offset: 2 }))
      .mockResolvedValueOnce(ok({ items: [{ id: 5 }], total: 5, limit: 2, offset: 4 }));

    const result = await fetchAllPages(fetchPage);
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.data.map((i) => i.id)).toEqual([1, 2, 3, 4, 5]);
    }
    expect(fetchPage).toHaveBeenCalledTimes(3);
    // Each call must request the maximum allowed page size, never the
    // page's own previous size, and advance by the number of items
    // actually returned, not a fixed increment.
    expect(fetchPage).toHaveBeenNthCalledWith(2, 100, 2);
    expect(fetchPage).toHaveBeenNthCalledWith(3, 100, 4);
  });

  it("3. fails closed (malformed) when an empty page arrives before the reported total was collected", async () => {
    const fetchPage: FetchPageMock = vi
      .fn()
      .mockResolvedValue(ok({ items: [], total: 50, limit: 100, offset: 0 }));
    const result = await fetchAllPages(fetchPage);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.kind).toBe("malformed");
    }
    // A mismatched/adversarial `total` (claims 50, returns nothing)
    // must never be retried past the first empty page, and must never
    // be reported as a truncated "success" either.
    expect(fetchPage).toHaveBeenCalledTimes(1);
  });

  it("4. fails closed (malformed) when the safety cap is reached before the reported total was collected", async () => {
    let calls = 0;
    const fetchPage: FetchPageMock = vi.fn().mockImplementation(async () => {
      calls += 1;
      return ok({ items: [{ id: calls }], total: Number.MAX_SAFE_INTEGER, limit: 100, offset: calls - 1 });
    });
    const result = await fetchAllPages(fetchPage);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.kind).toBe("malformed");
    }
    // MAX_PAGES (50) bounds this regardless of the claimed total --
    // never an unbounded/infinite loop, and never a silently truncated
    // "success" once the bound is hit.
    expect(fetchPage.mock.calls.length).toBeLessThanOrEqual(50);
  });

  it("5. propagates a page failure instead of returning partial data silently", async () => {
    const fetchPage: FetchPageMock = vi
      .fn()
      .mockResolvedValueOnce(ok({ items: [{ id: 1 }], total: 5, limit: 1, offset: 0 }))
      .mockResolvedValueOnce(fail("unavailable", "control-plane unreachable"));

    const result = await fetchAllPages(fetchPage);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.kind).toBe("unavailable");
    }
  });

  it("6a. fails closed (malformed) when a page's `items` is not an array", async () => {
    const fetchPage = vi
      .fn()
      .mockResolvedValue(ok({ items: "not-an-array" as unknown as Item[], total: 1, limit: 100, offset: 0 }));
    const result = await fetchAllPages(fetchPage);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.kind).toBe("malformed");
    }
  });

  it("6b. fails closed (malformed) when a page's `total` is negative", async () => {
    const fetchPage: FetchPageMock = vi
      .fn()
      .mockResolvedValue(ok({ items: [{ id: 1 }], total: -1, limit: 100, offset: 0 }));
    const result = await fetchAllPages(fetchPage);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.kind).toBe("malformed");
    }
  });

  it("6c. fails closed (malformed) when a page's `total` is not finite", async () => {
    const fetchPage: FetchPageMock = vi
      .fn()
      .mockResolvedValue(ok({ items: [{ id: 1 }], total: Number.POSITIVE_INFINITY, limit: 100, offset: 0 }));
    const result = await fetchAllPages(fetchPage);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.kind).toBe("malformed");
    }
  });
});
