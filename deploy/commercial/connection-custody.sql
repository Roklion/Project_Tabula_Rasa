-- Operator-only, once, in a dedicated EMPTY credential database. Never run
-- against bookkeeping, production or a restored target without exact approval.
-- No roles, passwords or external resources are created by this file.
BEGIN;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema NOT IN ('pg_catalog', 'information_schema')) THEN
        RAISE EXCEPTION 'Credential custody requires an empty dedicated database.';
    END IF;
END $$;
CREATE SCHEMA connection_custody;
REVOKE ALL ON SCHEMA connection_custody FROM PUBLIC;
CREATE TABLE connection_custody.grants (
    reference text PRIMARY KEY CHECK (reference ~ '^[0-9a-f]{32}$'),
    ciphertext bytea NOT NULL CHECK (octet_length(ciphertext) BETWEEN 1 AND 131072)
);
REVOKE ALL ON connection_custody.grants FROM PUBLIC;
COMMIT;
