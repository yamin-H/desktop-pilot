CREATE TABLE trades (
    exchange    text        NOT NULL,
    trade_id    text        NOT NULL CHECK (trade_id <> ''),
    symbol      text        NOT NULL,
    side        text        NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity    numeric     NOT NULL CHECK (quantity > 0),
    price       numeric     NOT NULL CHECK (price > 0),
    fee         numeric     NOT NULL DEFAULT 0 CHECK (fee >= 0),
    fee_asset   text,
    executed_at timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now(),  -- when WE stored it
    -- The exchange's own ID identifies a trade: the same ID is the same trade.
    PRIMARY KEY (exchange, trade_id)
);

CREATE INDEX trades_symbol_time_idx ON trades (symbol, executed_at);