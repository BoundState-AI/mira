-- MUA v7 Session Table
-- Stores server-side state for the 5-step MUA wizard

CREATE TABLE IF NOT EXISTS mua_sessions (
    session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT,
    current_step TEXT NOT NULL DEFAULT 'define',
    status TEXT NOT NULL DEFAULT 'active',
    center TEXT DEFAULT 'MSFC',

    -- Step 1: Define
    material TEXT,
    environment JSONB,
    process_params JSONB,
    application TEXT,

    -- Step 2: Investigate (cached)
    investigation_result JSONB,

    -- Step 3: Review (human decisions)
    review_decisions JSONB,
    divergence_labels JSONB DEFAULT '[]'::jsonb,

    -- Step 4: Draft
    draft_text TEXT,
    draft_metadata JSONB,
    edit_history JSONB DEFAULT '[]'::jsonb,
    fact_check_report JSONB,

    -- Step 5: Finalize
    finalized_at TIMESTAMPTZ,
    reviewer TEXT,
    applied_standard_version TEXT,
    dependency_links JSONB,
    export_format TEXT
);

-- Indexes
CREATE INDEX idx_mua_sessions_user ON mua_sessions(created_by, status);
CREATE INDEX idx_mua_sessions_updated ON mua_sessions(updated_at);
CREATE INDEX idx_mua_sessions_status ON mua_sessions(status);

-- Auto-update updated_at trigger
CREATE OR REPLACE FUNCTION update_mua_sessions_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_mua_sessions_updated_at
    BEFORE UPDATE ON mua_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_mua_sessions_updated_at();
