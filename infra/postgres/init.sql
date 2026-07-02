-- Documents state machine table
CREATE TYPE doc_status AS ENUM (
    'pending',
    'ocr_done',
    'chunked',
    'embedded',
    'graph_done',
    'complete',
    'failed',
    'dead_letter'
);

CREATE TABLE IF NOT EXISTS documents (
    file_hash        VARCHAR(64) PRIMARY KEY,   -- SHA-256 of file content
    s3_key_raw       TEXT NOT NULL,             -- relative path: raw/filename.pdf
    s3_key_md        TEXT,                      -- relative path: processed/filename.md
    s3_key_chunks    TEXT,                      -- relative path: chunks/filename.jsonl
    batch_id         VARCHAR(64) NOT NULL,
    status           doc_status NOT NULL DEFAULT 'pending',
    retry_count      SMALLINT NOT NULL DEFAULT 0,
    error_msg        TEXT,
    page_count       INTEGER,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_documents_status ON documents(status);
CREATE INDEX idx_documents_batch_id ON documents(batch_id);
CREATE INDEX idx_documents_updated_at ON documents(updated_at);

-- Dead letter queue for permanently failed documents
CREATE TABLE IF NOT EXISTS failed_documents (
    id               SERIAL PRIMARY KEY,
    file_hash        VARCHAR(64) NOT NULL REFERENCES documents(file_hash),
    failed_stage     TEXT NOT NULL,
    last_error       TEXT NOT NULL,
    failed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    manual_review    BOOLEAN NOT NULL DEFAULT FALSE,
    notes            TEXT
);

CREATE INDEX idx_failed_manual_review ON failed_documents(manual_review) WHERE manual_review = FALSE;

-- Auto-update updated_at on documents
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER documents_updated_at
    BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
