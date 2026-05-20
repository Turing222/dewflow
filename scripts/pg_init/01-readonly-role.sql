-- MCP sidecar reader role — defense-in-depth for query_db tool.
-- The MCP code also has keyword guards, but this is the real enforcement layer.
-- Runs automatically on first database init via docker-entrypoint-initdb.d.
-- For existing databases, run manually with superuser.

DO
$$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'mcp_reader') THEN
        CREATE ROLE mcp_reader WITH LOGIN PASSWORD 'mcp_reader' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END
$$;

-- Grant schema access
GRANT USAGE ON SCHEMA public TO mcp_reader;

-- Grant SELECT on all current tables
GRANT SELECT ON ALL TABLES IN SCHEMA public TO mcp_reader;

-- Grant SELECT on future tables (default privileges for admin user)
ALTER DEFAULT PRIVILEGES FOR ROLE admin IN SCHEMA public GRANT SELECT ON TABLES TO mcp_reader;
