// Exact decimal arithmetic on money text, using BigInt. Never uses floating point.
// (BigInt() calls instead of 10n literals, so the default TypeScript target works.)

const ZERO = BigInt(0);
const TEN = BigInt(10);

type Parsed = { digits: bigint; scale: number };

function parse(value: string): Parsed | null {
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value.trim());
  if (!match) return null;
  const [, sign, whole, fraction = ""] = match;
  const digits = BigInt(whole + fraction);
  return { digits: sign ? -digits : digits, scale: fraction.length };
}

function align(a: Parsed, b: Parsed): [bigint, bigint, number] {
  const scale = Math.max(a.scale, b.scale);
  return [
    a.digits * TEN ** BigInt(scale - a.scale),
    b.digits * TEN ** BigInt(scale - b.scale),
    scale,
  ];
}

/** -1, 0 or 1; null if either text is not a plain decimal like "-12.50". */
export function compareDecimal(a: string, b: string): number | null {
  const pa = parse(a);
  const pb = parse(b);
  if (!pa || !pb) return null;
  const [x, y] = align(pa, pb);
  return x < y ? -1 : x > y ? 1 : 0;
}

/** a - b as exact text, keeping the larger number of decimals. Null for invalid input. */
export function subtractDecimal(a: string, b: string): string | null {
  const pa = parse(a);
  const pb = parse(b);
  if (!pa || !pb) return null;
  const [x, y, scale] = align(pa, pb);
  const difference = x - y;
  const negative = difference < ZERO;
  const digits = (negative ? -difference : difference).toString().padStart(scale + 1, "0");
  const whole = digits.slice(0, digits.length - scale);
  const fraction = scale > 0 ? digits.slice(digits.length - scale) : "";
  return `${negative ? "-" : ""}${whole}${fraction ? `.${fraction}` : ""}`;
}