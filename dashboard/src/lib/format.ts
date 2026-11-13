// Money arrives as exact text ("60393.93"). It is formatted with string operations only,
// never converted to a floating-point number.

export function withThousands(value: string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const match = /^(-?)(\d+)(\.\d+)?$/.exec(value);
  if (!match) return value;
  const [, sign, whole, fraction = ""] = match;
  return `${sign}${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${fraction}`;
}

export type Sign = "gain" | "loss" | "flat" | "unknown";

export function signClass(value: string | null | undefined): Sign {
  if (value === null || value === undefined) return "unknown";
  if (value.startsWith("-")) return "loss";
  return /^0(\.0+)?$/.test(value) ? "flat" : "gain";
}

export function ageText(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

// Links come from scraped pages: only plain http(s) links are ever clickable.
export function safeHref(url: string): string {
  const trimmed = url.trim();
  return /^https?:\/\/[^\s]+$/i.test(trimmed) ? trimmed : "#";
}