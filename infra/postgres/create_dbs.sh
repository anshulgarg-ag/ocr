#!/bin/bash
# Creates extra databases needed alongside the primary POSTGRES_DB
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE prefect' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'prefect')\gexec
    GRANT ALL PRIVILEGES ON DATABASE prefect TO "$POSTGRES_USER";
    SELECT 'CREATE DATABASE sonarqube' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'sonarqube')\gexec
    GRANT ALL PRIVILEGES ON DATABASE sonarqube TO "$POSTGRES_USER";
EOSQL
