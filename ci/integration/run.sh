#!/usr/bin/env bash
# Integration: the real luach image started as a production deployment runs it, with the fake
# calendar and a fake OpenAI-compatible model, its store a Postgres as luach-db (postgres.sh),
# driven end to end over HTTP with pytest.
# Needs docker, python3 with pytest and httpx, and the image luach:ci (or IMAGE).
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
export FAKE_LLM_LOG=$(mktemp)
# The fake model listens on the docker bridge side so the container reaches it as host.docker.internal.
port=${FAKE_LLM_PORT:-38471}
python3 "$here/fake_llm.py" "$port" 0.0.0.0 & llm=$!
for _ in $(seq 20); do curl -fsS "http://127.0.0.1:$port/v1/models" >/dev/null 2>&1 && break; sleep 0.5; done
curl -fsS "http://127.0.0.1:$port/v1/models" >/dev/null || { echo "fake model did not start on port $port"; exit 1; }
state=$(docker volume create luach-ci-state)
docker rm -f luach >/dev/null 2>&1 || true
docker network create luach-ci >/dev/null 2>&1 || true
"$here/postgres.sh" luach-ci "${IMAGE:-luach:ci}"
docker run -d --name luach --network luach-ci -p 127.0.0.1:8004:8004 --add-host host.docker.internal:host-gateway --read-only --user 10001:10001 \
  --mount type=tmpfs,destination=/tmp \
  -v "$state:/var/lib/luach" \
  -e LUACH_CALENDAR=fake -e LUACH_GMAIL_POLL_MIN=0 -e LUACH_COOKIE_SECURE=0 \
  -e LUACH_DATABASE_URL=postgresql://luach@luach-db:5432/luach \
  -e OPENAI_BASE_URL="http://host.docker.internal:$port/v1" -e OPENAI_API_KEY=ci -e LUACH_MODEL=fake \
  "${IMAGE:-luach:ci}" >/dev/null
cleanup() { status=$?; [ $status -eq 0 ] || docker logs luach 2>&1 | tail -40; docker rm -f luach luach-db >/dev/null 2>&1; docker network rm luach-ci >/dev/null 2>&1; docker volume rm -f "$state" >/dev/null 2>&1; kill $llm 2>/dev/null; exit $status; }
trap cleanup EXIT
# the named volume is created root-owned; hand it to the app's uid like the pod's fsGroup does
docker run --rm -v "$state:/v" busybox chown 10001:10001 /v
docker restart luach >/dev/null
for _ in $(seq 60); do curl -fsS http://127.0.0.1:8004/api/health >/dev/null 2>&1 && break; sleep 1; done
python3 -m pytest -q -p no:cacheprovider "$here"
