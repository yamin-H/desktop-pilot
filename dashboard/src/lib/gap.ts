import { compareDecimal, subtractDecimal } from "./decimal";

/** The exact gap between the first two exchanges, or null if either price is missing or stale. */
export function gapText(
  prices: Record<string, string>,
  stale: string[],
  exchanges: string[],
): string | null {
  const [first, second] = exchanges;
  const a = prices[first];
  const b = prices[second];
  if (a === undefined || b === undefined || stale.includes(first) || stale.includes(second)) return null;
  const order = compareDecimal(a, b);
  if (order === null) return null;
  return order >= 0 ? subtractDecimal(a, b) : subtractDecimal(b, a);
}