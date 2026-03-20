-- MUA Precedents v7 — Table rename
-- Aligns the live table name with the code (pg_precedent_search.py, investigator.py)
-- which expects mua_precedents_v7.
--
-- The original 001 migration created "mua_precedents" but Beth's patches
-- query "mua_precedents_v7".  This migration reconciles the mismatch.
--
-- Safe: PostgreSQL renames carry indexes, triggers, and sequences automatically.
--
-- Run:
--   psql -d mira -f mira/mua/v7/migrations/003_rename_table_to_v7.sql
--
-- Date: 2026-02-08

BEGIN;

ALTER TABLE IF EXISTS mua_precedents RENAME TO mua_precedents_v7;

COMMIT;
