-- Self-hosted (OSS) Postgres bootstrap. Runs once on first DB init.
--
-- Creates the assistants schema (owned by this service) AND a minimal stub of
-- the user schema. The stub exists only so the alembic migration graph — which
-- still declares a couple of payments-owned tables (user_credits,
-- user_billing_status) with FKs to <user_schema>.users — can be applied against
-- a standalone database. In local mode the gateway never reads these tables
-- (auth + billing are self-contained), so they stay empty.
--
-- (Long-term: move those payments-owned tables out of this service's migrations
-- so no user-schema stub is needed. Tracked in planning/oss-v2.)

CREATE SCHEMA IF NOT EXISTS assistants;
CREATE SCHEMA IF NOT EXISTS mlpal_test;

-- Minimal users table so the FK targets resolve. app-enforced elsewhere; here it
-- only needs to exist. Includes a system user (id 0) matching the bootstrap key.
CREATE TABLE IF NOT EXISTS mlpal_test.users (
    id          SERIAL PRIMARY KEY,
    email       VARCHAR(255),
    cognito_sub VARCHAR(255) UNIQUE
);
INSERT INTO mlpal_test.users (id, email) VALUES (0, 'admin@localhost')
    ON CONFLICT (id) DO NOTHING;
