#!/bin/sh
# Demo business database init (mounted as docker-entrypoint-initdb.d/10-demo_role.sh):
# the read-only role the chatbot uses. 20-demo_schema.sql (demo_schema.sql) then
# creates the demo shop. Development/staging only.
set -eu
: "${BUSINESS_DB_READER_PASSWORD:?BUSINESS_DB_READER_PASSWORD is not set}"
case "$BUSINESS_DB_READER_PASSWORD" in
  *\'* | *\\*) echo "demo_role.sh: quotes and backslashes are not allowed in the password" >&2; exit 1 ;;
esac

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'chatbot_reader') THEN
    CREATE ROLE chatbot_reader LOGIN;
  END IF;
END
\$\$;
ALTER ROLE chatbot_reader WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD '${BUSINESS_DB_READER_PASSWORD}';
ALTER ROLE chatbot_reader SET default_transaction_read_only = on;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
EOSQL
