// Plain, framework-agnostic formatting -- safe to import from both
// Server and Client Components (unlike lib/server/*, nothing here
// touches a backend credential or secret).

export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toISOString().replace("T", " ").replace(/\.\d+Z$/, " UTC").replace(/Z$/, " UTC");
}
