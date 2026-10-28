#!/usr/bin/env bash
# luach-db as a deployment has it, on docker network $1, migrated by the image under test ($2):
# Postgres 16 in the C locale, the owner role luach. Leaves a container named luach-db.
set -euo pipefail
net=$1
image=$2
docker rm -f luach-db >/dev/null 2>&1 || true
docker run -d --name luach-db --network "$net" \
  -e POSTGRES_USER=luach -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=luach \
  -e POSTGRES_INITDB_ARGS="--locale=C --encoding=UTF8" \
  mirror.gcr.io/library/postgres:16 >/dev/null
# Over TCP: the image's first, socket-only server during initdb is not the one luach meets.
for _ in $(seq 60); do
  docker exec luach-db pg_isready -q -h 127.0.0.1 -U luach -d luach && break
  sleep 1
done
docker run --rm --network "$net" --read-only --user 10001:10001 \
  -e LUACH_DATABASE_URL=postgresql://luach@luach-db:5432/luach \
  "$image" luach-migrate
