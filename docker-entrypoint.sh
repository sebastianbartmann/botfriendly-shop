#!/bin/sh
set -e

# Fix volume permissions if running as root
if [ "$(id -u)" = "0" ]; then
    chown -R app:app /app/data 2>/dev/null || true
    exec gosu app "$@"
fi

# Already running as non-root
exec "$@"
