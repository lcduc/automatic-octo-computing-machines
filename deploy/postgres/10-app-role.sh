#!/bin/sh
# Creates (or updates) the role the application connects as: it may read and
# write rows but not change the schema. Migrations and backups use the owner
# role (POSTGRES_USER).
#
# Runs automatically on the first start of an empty data volume
# (docker-entrypoint-initdb.d), and again on every `chatbot deploy`, so an
# existing volume gains the role and a rotated password is applied. Idempotent.
set -eu

: "${POSTGRES_APP_USER:?POSTGRES_APP_USER is not set}"
: "${POSTGRES_APP_PASSWORD:?POSTGRES_APP_PASSWORD is not set}"
case "$POSTGRES_APP_USER$POSTGRES_APP_PASSWORD" in
  *\'* | *\"* | *\\*) echo "10-app-role.sh: quotes and backslashes are not allowed in the app role or password" >&2; exit 1 ;;
esac

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${POSTGRES_APP_USER}') THEN
    CREATE ROLE "${POSTGRES_APP_USER}" LOGIN;
  END IF;
END
\$\$;
ALTER ROLE "${POSTGRES_APP_USER}" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '${POSTGRES_APP_PASSWORD}';
GRANT CONNECT ON DATABASE "${POSTGRES_DB}" TO "${POSTGRES_APP_USER}";
GRANT USAGE ON SCHEMA public TO "${POSTGRES_APP_USER}";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "${POSTGRES_APP_USER}";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "${POSTGRES_APP_USER}";
ALTER DEFAULT PRIVILEGES FOR ROLE "${POSTGRES_USER}" IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "${POSTGRES_APP_USER}";
ALTER DEFAULT PRIVILEGES FOR ROLE "${POSTGRES_USER}" IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO "${POSTGRES_APP_USER}";
EOSQL
