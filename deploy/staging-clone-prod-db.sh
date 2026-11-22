#!/usr/bin/env bash
# Replace the STAGING database (and uploads) with a fresh copy of PRODUCTION.
# Run on the VM. Production is only read (pg_dump), never written.
#
#   bash deploy/staging-clone-prod-db.sh
#
# Staging then has real members' data, which is why the staging backend runs
# with MAIL_BACKEND=disabled (docker-compose.staging.yml).
set -euo pipefail

PROD_DB=portal-db
STAGING_DB=portal-staging-db
STAGING_BACKEND=portal-staging-backend
PROD_UPLOADS=mtr_portal_portal_uploads
STAGING_UPLOADS=portal-staging_staging_uploads

docker inspect "$STAGING_DB" >/dev/null || { echo "Staging stack isn't up yet (no $STAGING_DB)."; exit 1; }

echo "Stopping staging backend..."
docker stop "$STAGING_BACKEND" >/dev/null 2>&1 || true

echo "Recreating staging database..."
docker exec "$STAGING_DB" psql -U portal -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS portal WITH (FORCE);" -c "CREATE DATABASE portal OWNER portal;"

echo "Copying production -> staging..."
docker exec "$PROD_DB" pg_dump -U portal -d portal -Fc --no-owner \
  | docker exec -i "$STAGING_DB" pg_restore -U portal -d portal --no-owner --exit-on-error

if docker volume inspect "$PROD_UPLOADS" >/dev/null 2>&1; then
  echo "Copying uploads..."
  docker run --rm -v "$PROD_UPLOADS":/from:ro -v "$STAGING_UPLOADS":/to alpine \
    sh -c 'rm -rf /to/* && cp -a /from/. /to/'
fi

echo "Starting staging backend (runs migrations on boot)..."
docker start "$STAGING_BACKEND" >/dev/null
echo "Done."
