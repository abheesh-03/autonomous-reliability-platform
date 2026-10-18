import "server-only";

const DEFAULT_TIMEOUT_MS = 5000;

// Narrow, safe failure categories a page can render a tailored
// operator-facing state for -- never a raw backend exception body or
// stack trace. "unavailable" covers both a network-level failure
// (timeout, connection refused, DNS failure) and an unexpected non-2xx
// status this caller did not explicitly handle; "malformed" covers a
// response that could not even be parsed as JSON.
export type BackendErrorKind = "not_found" | "validation" | "unavailable" | "malformed";

export class BackendError extends Error {
  readonly kind: BackendErrorKind;
  constructor(kind: BackendErrorKind, message: string) {
    super(message);
    this.name = "BackendError";
    this.kind = kind;
  }
}

export type BackendResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: BackendError };

export function ok<T>(data: T): BackendResult<T> {
  return { ok: true, data };
}

export function fail<T = never>(kind: BackendErrorKind, message: string): BackendResult<T> {
  return { ok: false, error: new BackendError(kind, message) };
}

type GetJsonResult =
  | { status: number; body: unknown; parseError: false }
  | { status: number; body: null; parseError: true }
  | { networkError: true };

/**
 * Bounded-timeout GET. Never throws: a timeout, connection refusal, or
 * DNS failure resolves to { networkError: true } rather than an
 * uncaught rejection, so every caller can distinguish "the backend is
 * unreachable" from "the backend answered with an error" without a
 * try/catch of its own.
 */
export async function getJson(url: string, timeoutMs: number = DEFAULT_TIMEOUT_MS): Promise<GetJsonResult> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { signal: controller.signal, cache: "no-store" });
    const text = await response.text();
    if (text.length === 0) {
      return { status: response.status, body: null, parseError: false };
    }
    try {
      return { status: response.status, body: JSON.parse(text), parseError: false };
    } catch {
      return { status: response.status, body: null, parseError: true };
    }
  } catch {
    return { networkError: true };
  } finally {
    clearTimeout(timer);
  }
}

/** Builds a query string, omitting any parameter whose value is undefined. */
export function buildQuery(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) continue;
    search.set(key, String(value));
  }
  const qs = search.toString();
  return qs.length > 0 ? `?${qs}` : "";
}

export interface PageEnvelope<TItem> {
  items: TItem[];
  total: number;
  limit: number;
  offset: number;
}

// The API's own hard max; never requested above this regardless of
// caller input.
export const MAX_PAGE_LIMIT = 100;

// A bounded safety cap on the number of pages a "fetch the complete
// durable history" call will ever request, independent of what the
// backend reports as `total` -- a defensive bound against a
// malformed/adversarial `total` value, never a realistic ceiling for
// this product's current incident volume (50 x 100 = 5000 items).
const MAX_PAGES = 50;

/**
 * Repeatedly pages through a control-plane list endpoint at the
 * maximum allowed page size until every item the backend reports via
 * `total` has been collected. Callers (the incident detail page) use
 * this to claim they have rendered the COMPLETE durable history, so
 * this function FAILS CLOSED rather than returning a silently
 * truncated "success":
 *
 * - an empty page (no forward progress possible) while still short of
 *   `total` is a "malformed" failure, never a quiet `ok(partial)`;
 * - exhausting MAX_PAGES while still short of `total` is the same
 *   failure, never a quiet `ok(partial)`;
 * - a per-page envelope that fails basic sanity (`items` not an
 *   array, `total` not a finite non-negative number) is the same
 *   failure, never trusted into a wrong-shaped success.
 *
 * `ok(...)` is returned ONLY when `collected.length >= total` was
 * actually reached.
 */
export async function fetchAllPages<TItem>(
  fetchPage: (limit: number, offset: number) => Promise<BackendResult<PageEnvelope<TItem>>>,
): Promise<BackendResult<TItem[]>> {
  const collected: TItem[] = [];
  let offset = 0;
  let total = Infinity;
  let pages = 0;

  while (collected.length < total && pages < MAX_PAGES) {
    const page = await fetchPage(MAX_PAGE_LIMIT, offset);
    if (!page.ok) return page;

    const envelope = page.data;
    if (!Array.isArray(envelope.items) || !Number.isFinite(envelope.total) || envelope.total < 0) {
      return fail("malformed", "paginated backend response had an invalid envelope (total/items)");
    }
    total = envelope.total;

    if (envelope.items.length === 0) {
      // No forward progress possible at this offset -- stop rather
      // than request the exact same page again. Whether this counts
      // as complete is decided by the collected-vs-total check below,
      // never assumed here.
      break;
    }

    collected.push(...envelope.items);
    offset += envelope.items.length;
    pages += 1;
  }

  if (collected.length < total) {
    return fail("malformed", "paginated backend response ended before reported total was collected");
  }

  return ok(collected);
}
