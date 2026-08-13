#!/usr/bin/env bash
set -euo pipefail

# depends_on: condition: service_healthy only guarantees Postgres itself is
# ready — the container network/DNS can still take a moment to settle right
# after everything starts together, so the first connection attempt is
# allowed a few retries before this is treated as a real failure.
echo "Applying migrations..."
for attempt in 1 2 3 4 5; do
  if alembic upgrade head; then
    break
  fi
  if [ "$attempt" = 5 ]; then
    echo "Migrations failed after 5 attempts, giving up."
    exit 1
  fi
  echo "Migration attempt $attempt failed, retrying in 3s..."
  sleep 3
done

if [ "${SEED_DEMO:-}" = "1" ]; then
  echo "Seeding roles + demo org (SEED_DEMO=1)..."
  python -m app.seed --demo
else
  echo "Seeding roles + bootstrap admin (idempotent, no demo data)..."
  python -m app.seed
fi

echo "Starting server..."
# Render/most PaaS inject the port to bind on via $PORT; fall back to 8000 for
# local Docker/compose where the port is fixed.
#
# WEB_CONCURRENCY = number of uvicorn worker processes. Each worker is its own
# process with its own event loop, so N workers use up to N CPU cores in
# parallel (the free-tier VM has 2). Default 2; override in compose/env. Keep
# it modest on the 1 GB box — every worker is ~120-180 MB RSS, and swap (4 GB)
# is the safety net for spikes, not a place to run steady-state.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}"
