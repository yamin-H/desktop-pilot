CREATE TABLE announcements (
    source        text        NOT NULL,
    external_id   text        NOT NULL,   -- the announcement's absolute URL
    title         text        NOT NULL,
    url           text        NOT NULL,
    published_at  timestamptz,
    category      text        NOT NULL,
    assets        text[]      NOT NULL DEFAULT '{}',
    important     boolean     NOT NULL,
    first_seen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    alerted_at    timestamptz,            -- NULL = not alerted yet
    PRIMARY KEY (source, external_id)
);

CREATE INDEX announcements_seen_idx ON announcements (first_seen_at DESC);