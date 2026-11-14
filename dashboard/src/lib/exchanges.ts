// Each exchange has one hue everywhere: chart lines, tags and swatches.
const EXCHANGES: Record<string, { name: string; cssVar: string }> = {
  binance: { name: "Binance", cssVar: "--binance" },
  kraken: { name: "Kraken", cssVar: "--kraken" },
  bybit: { name: "Bybit", cssVar: "--bybit" },
};

export function exchangeInfo(id: string): { name: string; cssVar: string; color: string } {
  const known = EXCHANGES[id];
  const cssVar = known?.cssVar ?? "--muted";
  return { name: known?.name ?? id, cssVar, color: `var(${cssVar})` };
}