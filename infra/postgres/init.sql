-- WolfPack Postgres initialisation script.
-- Runs once when the postgres container first creates its data volume.

-- pgvector extension for Haystack RAG (Phase 3+)
CREATE EXTENSION IF NOT EXISTS vector;

-- Application schema for Phase 1 tables
CREATE SCHEMA IF NOT EXISTS wolfpack;

-- MLflow tracking server database (used by 'full' compose profile)
CREATE DATABASE mlflow;

-- Phase 1 tables are managed by Alembic migrations.
-- This script guarantees extensions and base schema exist at first start.