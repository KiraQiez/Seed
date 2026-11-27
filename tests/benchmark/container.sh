#!/bin/sh
set -eu

export POSTGRES_USER=seed_benchmark POSTGRES_DB=seed_benchmark
POSTGRES_PASSWORD=$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(24))')
export POSTGRES_PASSWORD
export POSTGRES_INITDB_ARGS='--auth-host=scram-sha-256'
export SEED_BENCHMARK_URL="postgresql://seed_benchmark:$POSTGRES_PASSWORD@127.0.0.1:5432/seed_benchmark"

docker-entrypoint.sh postgres -c listen_addresses=127.0.0.1 >/tmp/seed-postgres.log 2>&1 &
db_pid=$!
trap 'kill "$db_pid" 2>/dev/null || true; wait "$db_pid" 2>/dev/null || true' EXIT
for attempt in $(seq 1 60); do
    if pg_isready -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q; then
        .venv/bin/python tests/benchmark/reference.py
        exit 0
    fi
    kill -0 "$db_pid"
    sleep 1
done
echo "The disposable benchmark database did not become ready." >&2
exit 1
