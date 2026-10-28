// Independent-review correction round, BLOCKER 4: safely parses/clamps
// raw, browser-supplied URL search params for the (now genuinely
// paginated) services list -- mirrors lib/incident-query.ts exactly, so
// the two list pages never silently diverge in pagination behavior.

export interface ParsedServiceListParams {
  limit: number;
  offset: number;
}

export type RawSearchParams = Record<string, string | string[] | undefined>;

const DEFAULT_LIMIT = 20;
const MIN_LIMIT = 1;
const MAX_LIMIT = 100;

function firstValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export function parseServiceListSearchParams(searchParams: RawSearchParams): ParsedServiceListParams {
  const rawLimit = firstValue(searchParams.limit);
  const rawOffset = firstValue(searchParams.offset);

  const parsedLimit = rawLimit !== undefined ? Number.parseInt(rawLimit, 10) : Number.NaN;
  const limit = Number.isFinite(parsedLimit) ? Math.min(MAX_LIMIT, Math.max(MIN_LIMIT, parsedLimit)) : DEFAULT_LIMIT;

  const parsedOffset = rawOffset !== undefined ? Number.parseInt(rawOffset, 10) : Number.NaN;
  const offset = Number.isFinite(parsedOffset) ? Math.max(0, parsedOffset) : 0;

  return { limit, offset };
}
