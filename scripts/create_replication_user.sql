-- =============================================================================
-- Create a dedicated PostgreSQL replication user with minimal privileges.
--
-- Run this on the PRIMARY node's database.  The standby connects using
-- this user for logical replication instead of the superuser.
--
-- Usage (from host):
--   docker exec -i invoicing-postgres-1 psql -U postgres -d workshoppro < scripts/create_replication_user.sql
--
-- The password below is a placeholder — change it for production!
-- =============================================================================

-- Create the replication user (idempotent)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'replicator') THEN
        CREATE USER replicator WITH REPLICATION LOGIN PASSWORD 'replicator-dev-password';
        RAISE NOTICE 'Created user "replicator"';
    ELSE
        -- Update password if user already exists
        ALTER USER replicator WITH PASSWORD 'replicator-dev-password';
        RAISE NOTICE 'User "replicator" already exists — password updated';
    END IF;
END
$$;

-- Grant SELECT on all existing tables in public schema
-- (required for logical replication initial data copy)
GRANT USAGE ON SCHEMA public TO replicator;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO replicator;

-- Ensure future tables also get SELECT granted
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO replicator;

-- Verify
SELECT rolname, rolreplication, rolcanlogin
FROM pg_roles
WHERE rolname = 'replicator';
