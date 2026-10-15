#!/bin/sh
set -e

# ==============================================================================
# HireScan Container Startup & Release Entrypoint
# ==============================================================================

echo "==> Starting HireScan Application Container..."

# Wait for PostgreSQL database connectivity if configured
if [ "$DB_ENGINE" = "postgresql" ] || [ -n "$DATABASE_URL" ]; then
    echo "==> PostgreSQL database configured. Checking connection readiness..."
    python - <<'EOF'
import os
import sys
import time
import socket

db_host = os.getenv('DB_HOST', 'db')
db_port = int(os.getenv('DB_PORT', 5432))

# Extract from DATABASE_URL if present
db_url = os.getenv('DATABASE_URL', '')
if db_url.startswith(('postgres://', 'postgresql://')):
    from urllib.parse import urlparse
    parsed = urlparse(db_url)
    db_host = parsed.hostname or db_host
    db_port = parsed.port or db_port

print(f"==> Probing database host {db_host}:{db_port}...")
max_retries = 30
retry_count = 0

while retry_count < max_retries:
    try:
        with socket.create_connection((db_host, db_port), timeout=3):
            print(f"==> Database at {db_host}:{db_port} is accepting connections!")
            sys.exit(0)
    except (socket.timeout, ConnectionRefusedError, OSError):
        retry_count += 1
        print(f"==> Waiting for database at {db_host}:{db_port} (attempt {retry_count}/{max_retries})...")
        time.sleep(2)

print("==> ERROR: Timed out waiting for database. Exiting.", file=sys.stderr)
sys.exit(1)
EOF
fi

# Run database migrations safely during release phase
if [ "$RUN_MIGRATIONS" != "false" ]; then
    echo "==> Applying database migrations..."
    python manage.py migrate --noinput
else
    echo "==> Skipping migrations (RUN_MIGRATIONS=false)."
fi

# Collect static assets into STATIC_ROOT
if [ "$COLLECT_STATIC" != "false" ]; then
    echo "==> Collecting static assets..."
    python manage.py collectstatic --noinput
else
    echo "==> Skipping collectstatic (COLLECT_STATIC=false)."
fi

echo "==> HireScan initialization complete. Launching server process..."

# Execute the primary process (Gunicorn)
exec "$@"
