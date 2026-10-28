#!/usr/bin/env bash
#
# The lock files: pyproject.toml resolved to exact versions, with hashes.
#
#   requirements.lock      [project] dependencies -- what the image installs (Dockerfile)
#   requirements-dev.lock  the same pins plus the [dev] extra -- what hatch's envs install, so CI
#                          tests exactly the packages the image ships
#
# Both are universal (every Python from 3.12 up, every platform), because CI runs the suite on
# 3.13 on main as well as the image's 3.12. Each file's header is the command that made it,
# which is what Renovate's pip-compile manager reads to refresh it: keep the header intact.
#
#   scripts/lock.sh          refresh after editing pyproject.toml. Versions already in the lock
#                            are kept where they still fit; only what the edit needs moves.
#   scripts/lock.sh --check  CI's guard: fail if pyproject.toml asks for something the lock does
#                            not hold. Writes nothing.
#
# To take newer releases on purpose: scripts/lock.sh --upgrade (or --upgrade-package NAME).
# Needs uv on PATH (pipx install uv).
set -euo pipefail
cd "$(dirname "$0")/.."

compile() {
    # $1: the lock to write; the rest goes to uv. Both files share these options.
    local out=$1
    shift
    uv pip compile pyproject.toml "$@" --universal --python-version=3.12 --generate-hashes \
        --output-file="$out" --quiet
}

refresh() {
    # $1: the directory the two locks live in ("" for here); the rest goes to uv (--upgrade).
    local dir=${1:+$1/}
    shift
    compile "${dir}requirements.lock" "$@"
    compile "${dir}requirements-dev.lock" --extra=dev --constraint="${dir}requirements.lock" "$@"
}

if [[ ${1:-} != --check ]]; then
    # Relative paths in place, so the header records the command a person (or Renovate) reruns.
    refresh "" "$@"
    exit 0
fi

# Check: refresh copies elsewhere and compare the pins. uv keeps a version the output file
# already holds, so the copies come back unchanged unless pyproject.toml needs a change. Hashes
# are left out of the comparison: a wheel uploaded later for a pinned version is not drift.
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cp requirements.lock requirements-dev.lock "$tmp/"
refresh "$tmp"
pins() { grep -oE '^[A-Za-z0-9._-]+==[^ ;\\]+' "$1" | sort; }
stale=0
for lock in requirements.lock requirements-dev.lock; do
    if ! diff -u --label "$lock (committed)" --label "$lock (pyproject.toml now)" \
        <(pins "$lock") <(pins "$tmp/$lock"); then
        stale=1
    fi
done
if ((stale)); then
    echo >&2 "*** the lock files do not match pyproject.toml. Refresh them and commit the result:"
    echo >&2 "        scripts/lock.sh"
    exit 1
fi
echo "ok: requirements.lock and requirements-dev.lock match pyproject.toml"
