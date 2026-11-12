CREATE EXTENSION IF NOT EXISTS vector;

-- One row per source file or page.
CREATE TABLE documents (
    id           bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source       text        NOT NULL UNIQUE CHECK (source <> ''),
    title        text        NOT NULL,
    doc_type     text        NOT NULL CHECK (doc_type <> ''),
    -- sha256 of the text. Same hash on re-ingest means nothing changed, so skip the work.
    content_hash text        NOT NULL,
    metadata     jsonb       NOT NULL DEFAULT '{}',
    ingested_at  timestamptz NOT NULL DEFAULT now()
);

-- One row per searchable piece of a document.
CREATE TABLE chunks (
    id              bigint   GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id     bigint   NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    chunk_index     integer  NOT NULL CHECK (chunk_index >= 0),
    heading         text,
    content         text     NOT NULL CHECK (content <> ''),
    token_count     integer  NOT NULL CHECK (token_count > 0),
    -- 384 dimensions = BAAI/bge-small-en-v1.5. A different model means a new migration.
    embedding       vector(384) NOT NULL,
    -- Stored per row so a model change can never silently mix two embedding spaces.
    embedding_model text     NOT NULL,
    -- Keyword search index, kept in sync by the database itself.
    tsv             tsvector GENERATED ALWAYS AS (
                        to_tsvector('english', coalesce(heading, '') || ' ' || content)
                    ) STORED,
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX chunks_embedding_hnsw_idx ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX chunks_tsv_idx ON chunks USING gin (tsv);