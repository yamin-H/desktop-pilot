export type PriceRow = {
  exchange: string;
  symbol: string;
  price: string;
  time: string;
  age_seconds: number;
  fresh: boolean;
};

export type SpreadRow = {
  symbol: string;
  high: { exchange: string; price: string };
  low: { exchange: string; price: string };
  amount: string;
  percent: string;
};

export type Market = {
  time: string;
  max_age_seconds: number;
  prices: PriceRow[];
  spreads: SpreadRow[];
};

export type PnlPosition = {
  exchange: string;
  symbol: string;
  quote_currency: string;
  quantity: string;
  average_cost: string | null;
  cost_basis: string;
  realized_pnl: string;
  price: string | null;
  price_time: string | null;
  price_is_stale: boolean | null;
  market_value: string | null;
  unrealized_pnl: string | null;
  total_pnl: string | null;
};

export type PnlTotals = {
  quote_currency: string;
  realized_pnl: string;
  unrealized_pnl: string | null;
  total_pnl: string | null;
  missing_prices: string[];
};

export type PnlResponse = { positions: PnlPosition[]; totals: PnlTotals[]; note: string };

export type AnnouncementRow = {
  source: string;
  title: string;
  url: string;
  category: string;
  assets: string[];
  important: boolean;
  time: string | null;
};
export type Health = {
  status: string;
  database: string;
  redis: string;
  market_source: string;
  market_poller: string;
  time: string;
};

export type TradeRow = {
  exchange: string;
  trade_id: string;
  symbol: string;
  side: string;
  quantity: string;
  price: string;
  fee: string;
  fee_asset: string | null;
  time: string;
};

export type TradesResponse = { total_matching: number; shown: number; trades: TradeRow[] };
export type ChatResult = { answer: string; tools: { name: string; arguments: string; ok: boolean }[] };