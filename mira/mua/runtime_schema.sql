-- MUA Runtime schema for sessioned review, synthesis traceability, and learning events.
-- Safe to re-run.

BEGIN;

CREATE SCHEMA IF NOT EXISTS mua_runtime;

CREATE TABLE IF NOT EXISTS mua_runtime.sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    material_text   TEXT NOT NULL,
    maptis_code     TEXT,
    material_name   TEXT,
    material_class  TEXT,
    alloy_family    TEXT,
    media           TEXT NOT NULL,
    environment     TEXT DEFAULT 'non-habitable',
    project         TEXT DEFAULT '',
    system          TEXT DEFAULT '',
    ratings_input   JSONB NOT NULL,
    decisions       JSONB,
    status          TEXT DEFAULT 'draft',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mua_runtime.evidence_bundles (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id        UUID REFERENCES mua_runtime.sessions(id),
    issue             TEXT NOT NULL,
    rating            TEXT NOT NULL,
    evidence_hash     TEXT NOT NULL,
    precedent_count   JSONB,
    precedent_ring    TEXT,
    exemplar_muas     JSONB,
    extracted_phrases JSONB,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mua_runtime.synthesis_drafts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id          UUID REFERENCES mua_runtime.sessions(id),
    evidence_id         UUID REFERENCES mua_runtime.evidence_bundles(id),
    issue               TEXT NOT NULL,
    rationale_draft     TEXT NOT NULL,
    disposition_draft   TEXT NOT NULL,
    claims              JSONB NOT NULL,
    model_id            TEXT NOT NULL,
    prompt_version      TEXT NOT NULL,
    tokens_used         INT,
    latency_ms          INT,
    template_fallback   BOOLEAN DEFAULT FALSE,
    verified            BOOLEAN DEFAULT FALSE,
    blocked_claims      JSONB,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mua_runtime.engineer_actions (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id            UUID REFERENCES mua_runtime.sessions(id),
    issue                 TEXT NOT NULL,
    action                TEXT NOT NULL,
    original_rationale    TEXT,
    edited_rationale      TEXT,
    original_disposition  TEXT,
    edited_disposition    TEXT,
    comment               TEXT,
    created_at            TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mua_runtime.final_documents (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id         UUID REFERENCES mua_runtime.sessions(id),
    mua_number         TEXT,
    final_rationale    TEXT NOT NULL,
    final_disposition  TEXT NOT NULL,
    final_form_fields  JSONB NOT NULL,
    docx_hash          TEXT,
    docx_path          TEXT,
    generated_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mua_runtime.learning_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID REFERENCES mua_runtime.sessions(id),
    event_type  TEXT NOT NULL,
    payload     JSONB NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mua_runtime_learning_type
    ON mua_runtime.learning_events(event_type);

CREATE INDEX IF NOT EXISTS idx_mua_runtime_learning_session
    ON mua_runtime.learning_events(session_id);

CREATE INDEX IF NOT EXISTS idx_mua_runtime_sessions_status
    ON mua_runtime.sessions(status);

CREATE INDEX IF NOT EXISTS idx_mua_runtime_final_documents_session
    ON mua_runtime.final_documents(session_id);

COMMIT;
