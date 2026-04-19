-- WolfPack Postgres initialisation script.
-- Runs once when the postgres container first creates its data volume.

-- pgvector extension for Haystack RAG (Phase 3+)
CREATE EXTENSION IF NOT EXISTS vector;

-- Phase 1 tables will be added in a follow-up migration.
-- This script guarantees the extension is available at first start.