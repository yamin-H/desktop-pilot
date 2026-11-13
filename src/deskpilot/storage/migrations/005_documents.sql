CREATE TABLE documents (
    id           bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source       text        NOT NULL UNIQUE,  -- stable name, e.g. runbooks/reconciliation.md
    title        text        NOT NULL,
    content_hash text        NOT NULL,         -- fingerprint of the file + pipeline settings
    ingested_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE document_chunks (
    id          bigint  GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id bigint  NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    chunk_index integer NOT NULL,
    heading     text,
    page        integer,
    content     text    NOT NULL,
    -- 384 dimensions = BAAI/bge-small-en-v1.5. Another model needs a new migration.
    embedding   vector(384) NOT NULL,
    -- keyword search text, maintained by the database itself
    tsv         tsvector GENERATED ALWAYS AS (
                    to_tsvector('english', coalesce(heading, '') || ' ' || content)
                ) STORED,
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX document_chunks_embedding_idx
    ON document_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX document_chunks_tsv_idx ON document_chunks USING gin (tsv);