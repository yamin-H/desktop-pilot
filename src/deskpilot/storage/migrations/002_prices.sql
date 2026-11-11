CREATE TABLE prices (
    exchange      text        NOT NULL,
    symbol        text        NOT NULL,
    price         numeric     NOT NULL CHECK (price > 0),
    exchange_time timestamptz NOT NULL,
    received_time timestamptz NOT NULL,
    -- This key is the duplicate rule: the same record saved twice is stored once.
    PRIMARY KEY (exchange, symbol, exchange_time, price)
);

-- Turn it into a time-series table, stored in one-day chunks.
SELECT create_hypertable('prices', by_range('exchange_time', INTERVAL '1 day'));