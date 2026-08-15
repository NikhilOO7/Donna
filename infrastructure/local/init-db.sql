-- infrastructure/local/init-db.sql
-- Runs ONCE, on first boot of an empty Postgres volume
-- (docker-entrypoint-initdb.d).
--
-- SCOPE: schema and extensions ONLY. It must not create tables.
--
-- Why: the schema is owned exclusively by Alembic (see ADR / invariant 9 in
-- the architecture book). This file used to CREATE TABLE documents,
-- document_chunks, contextual_embeddings, conversation_sessions and
-- analytics_events — the same tables migration 57e05bb92c70 creates. On a
-- fresh volume the backend then died on boot with:
--
--     DuplicateTableError: relation "conversation_sessions" already exists
--
-- ...because the container's CMD runs `alembic upgrade head` first. Two
-- owners of one schema is a contradiction; the migration chain wins, because
-- it is reviewed, versioned and drift-checked in CI.

CREATE SCHEMA IF NOT EXISTS doc_intel;

-- Required by migrations and by gen_random_uuid() defaults.
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Tables, indexes and constraints are applied by:
--     alembic upgrade head
-- which the backend container runs before starting uvicorn.
