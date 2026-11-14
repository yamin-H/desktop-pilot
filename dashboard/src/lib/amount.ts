export type AmountParts = { value: number; fractionDigits: number };

const PLAIN = /^(-?)(\d+)(?:\.(\d+))?$/;

/** A number for the rolling-digits display, but ONLY if a double holds the text exactly
 *  (15 significant digits). Otherwise null: the caller shows the exact text instead. */
export function amountParts(text: string): AmountParts | null {
  const match = PLAIN.exec(text.trim());
  if (!match) return null;
  const [, , whole, fraction = ""] = match;
  if ((whole + fraction).replace(/^0+/, "").length > 15) return null;
  const value = Number(text);
  return Number.isFinite(value) ? { value, fractionDigits: fraction.length } : null;
}