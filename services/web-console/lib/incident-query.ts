// Safely parses/clamps/validates raw, browser-supplied URL search
// params for the incident list -- an unrecognized status/severity is
// silently dropped (never forwarded to control-plane, which would
// otherwise 422), a non-numeric or out-of-range limit/offset is
// clamped or defaulted. Framework-agnostic (plain Next.js
// searchParams shape), so it is testable without rendering anything.

import {
  INCIDENT_SEVERITIES,
  INCIDENT_STATUSES,
  type IncidentSeverity,
  type IncidentStatus,
} from "./types/incident";

export interface ParsedIncidentListParams {
  status?: IncidentStatus;
  severity?: IncidentSeverity;
  source?: string;
  limit: number;
  offset: number;
}

export type RawSearchParams = Record<string, string | string[] | undefined>;

const DEFAULT_LIMIT = 20;
const MIN_LIMIT = 1;
const MAX_LIMIT = 100;
const MAX_SOURCE_LENGTH = 200;

function firstValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function isIncidentStatus(value: string | undefined): value is IncidentStatus {
  return value !== undefined && (INCIDENT_STATUSES as readonly string[]).includes(value);
}

function isIncidentSeverity(value: string | undefined): value is IncidentSeverity {
  return value !== undefined && (INCIDENT_SEVERITIES as readonly string[]).includes(value);
}

export function parseIncidentListSearchParams(searchParams: RawSearchParams): ParsedIncidentListParams {
  const rawStatus = firstValue(searchParams.status);
  const rawSeverity = firstValue(searchParams.severity);
  const rawSource = firstValue(searchParams.source);
  const rawLimit = firstValue(searchParams.limit);
  const rawOffset = firstValue(searchParams.offset);

  const status = isIncidentStatus(rawStatus) ? rawStatus : undefined;
  const severity = isIncidentSeverity(rawSeverity) ? rawSeverity : undefined;
  const trimmedSource = rawSource?.trim();
  const source = trimmedSource && trimmedSource.length > 0 ? trimmedSource.slice(0, MAX_SOURCE_LENGTH) : undefined;

  const parsedLimit = rawLimit !== undefined ? Number.parseInt(rawLimit, 10) : Number.NaN;
  const limit = Number.isFinite(parsedLimit) ? Math.min(MAX_LIMIT, Math.max(MIN_LIMIT, parsedLimit)) : DEFAULT_LIMIT;

  const parsedOffset = rawOffset !== undefined ? Number.parseInt(rawOffset, 10) : Number.NaN;
  const offset = Number.isFinite(parsedOffset) ? Math.max(0, parsedOffset) : 0;

  return { status, severity, source, limit, offset };
}
