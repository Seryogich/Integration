-- Creates the MLflow backend database.
-- This script runs only on a fresh PostgreSQL data volume (docker-entrypoint-initdb.d).
-- If the volume already exists, create the database manually:
--   docker compose exec postgres psql -U orders -c "CREATE DATABASE mlflow;"
CREATE DATABASE mlflow;
