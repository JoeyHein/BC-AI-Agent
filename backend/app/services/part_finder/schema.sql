-- Part Finder index schema (SQLite).
-- Consumed by the search API and the Claude-Vision identification layer.
-- Mirrors cleanly onto Postgres later (the column set is intentionally portable).

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- One row per PDF document in the corpus.
CREATE TABLE IF NOT EXISTS documents (
    doc_id          TEXT PRIMARY KEY,   -- stable id: sha256[:16], else path hash
    rel_path        TEXT NOT NULL,      -- path relative to library root (POSIX form)
    filename        TEXT NOT NULL,
    category        TEXT,               -- e.g. 01-Garage-Door-Panels
    category_label  TEXT,               -- e.g. "Garage Door Panels"
    region          TEXT,               -- North-America / Europe / Asia-Pacific / ...
    brand           TEXT,               -- brand folder name
    doc_type        TEXT,               -- Install / Owner-Manual / Brochure / Spec / ...
    title           TEXT,               -- PDF /Title metadata or derived from filename
    page_count      INTEGER,
    size_bytes      INTEGER,
    sha256          TEXT,
    source_url      TEXT,
    -- Brand enrichment joined from manufacturers-master.csv:
    manufacturer    TEXT,
    parent_company  TEXT,
    hq_country      TEXT,
    hq_state        TEXT,
    hq_city         TEXT,
    brand_status    TEXT,               -- Active / Discontinued
    website         TEXT,
    product_lines   TEXT,
    sub_category    TEXT,               -- Residential / Commercial / ...
    -- Extraction results:
    text_chars      INTEGER DEFAULT 0,
    is_scanned      INTEGER DEFAULT 0,  -- 1 = image-only, needs OCR/vision
    cover_image     TEXT,               -- rel path under images/ to cover webp
    ingested_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_documents_brand    ON documents(brand);
CREATE INDEX IF NOT EXISTS idx_documents_category ON documents(category);
CREATE INDEX IF NOT EXISTS idx_documents_region   ON documents(region);
CREATE INDEX IF NOT EXISTS idx_documents_doctype  ON documents(doc_type);

-- One row per page.
CREATE TABLE IF NOT EXISTS pages (
    doc_id      TEXT NOT NULL,
    page_no     INTEGER NOT NULL,       -- 1-based
    char_count  INTEGER DEFAULT 0,
    needs_ocr   INTEGER DEFAULT 0,
    text        TEXT,
    PRIMARY KEY (doc_id, page_no),
    FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE
);

-- Full-text search over page text. External-content FTS keyed to pages.rowid
-- would couple us to rowids across runs; we keep it standalone and populate
-- it directly during ingest for simplicity and portability.
CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
    text,
    doc_id UNINDEXED,
    page_no UNINDEXED,
    brand UNINDEXED,
    tokenize = 'unicode61'
);

-- Extracted model / part / catalog numbers, one row per (doc, page, token).
CREATE TABLE IF NOT EXISTS part_numbers (
    doc_id   TEXT NOT NULL,
    page_no  INTEGER NOT NULL,
    token    TEXT NOT NULL,             -- normalized (upper, no spaces)
    raw      TEXT,                      -- as found in text
    kind     TEXT,                      -- labeled | alnum | numeric
    freq     INTEGER DEFAULT 1,
    FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pn_token ON part_numbers(token);
CREATE INDEX IF NOT EXISTS idx_pn_doc   ON part_numbers(doc_id);

-- Broken / unreadable PDFs, held out for re-download.
CREATE TABLE IF NOT EXISTS quarantine (
    rel_path    TEXT PRIMARY KEY,
    filename    TEXT,
    brand       TEXT,
    category    TEXT,
    reason      TEXT,
    size_bytes  INTEGER,
    source_url  TEXT
);

-- One row per ingest run, for auditability.
CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id          TEXT PRIMARY KEY,
    started_at      TEXT,
    finished_at     TEXT,
    library_root    TEXT,
    docs_ok         INTEGER,
    docs_broken     INTEGER,
    docs_scanned    INTEGER,
    pages           INTEGER,
    part_numbers    INTEGER,
    notes           TEXT
);
