# Sourced by the scripts in ios/: where this checkout builds and which luach its tests use.
# Nothing here names a real host; each person's own values come from the environment or from
# ios/scripts/local.env (not committed; ios/README.md, "Settings"). The environment wins over
# the file.
#
#   LUACH_MAC_HOST        the Mac that builds, over ssh (`ssh <host>`); unset: this machine,
#                         which is then a Mac with Xcode
#   LUACH_MAC_DIR         where on that Mac each run keeps its copy, from its home folder
#                         (default Library/Caches/luach)
#   LUACH_DEV_SERVER      the luach the integration and UI tests use (https://…); unset: those
#                         tests are skipped and only the unit and hosted tests run
#   LUACH_DEV_KUBECONFIG  the kubeconfig that reaches that luach's pod, to mint the run's session
#                         (default: kubectl's own)
#   LUACH_DEV_NAMESPACE   that pod's namespace (default: the kubeconfig's)
#   LUACH_PROD_SERVER     the family's own luach: test-prod.sh reads it, and every test that
#                         writes refuses it

settings_file="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/local.env"
if [ -f "$settings_file" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line#"${line%%[![:space:]]*}"}"
    case "$line" in '' | '#'*) continue ;; esac
    line="${line#export }"
    key="${line%%=*}" value="${line#*=}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    case "$value" in \"*\") value="${value:1:${#value}-2}" ;; \'*\') value="${value:1:${#value}-2}" ;; esac
    [ -n "${!key+set}" ] || export "$key=$value"
  done < "$settings_file"
fi

LUACH_MAC_HOST="${LUACH_MAC_HOST:-}"
mac_dir="${LUACH_MAC_DIR:-Library/Caches/luach}"
mac_dir="${mac_dir#\~/}"
mac_dir="${mac_dir%/}"

# A server's host, for comparing two addresses: https://Luach.example.com:8443/x → luach.example.com
host_of() {
  local h="${1#*://}"
  h="${h%%/*}"
  h="${h%%:*}"
  echo "$h" | tr '[:upper:]' '[:lower:]'
}

# Runs a command line on the Mac, from its home folder, as `ssh <host> <line>` does.
mac() {
  if [ -n "$LUACH_MAC_HOST" ]; then
    ssh "$LUACH_MAC_HOST" "$@"
  else
    (cd ~ && bash -c "$*")
  fi
}

# A path on the Mac (relative to its home folder) as rsync and scp name it.
on_mac() {
  if [ -n "$LUACH_MAC_HOST" ]; then
    echo "$LUACH_MAC_HOST:$1"
  else
    case "$1" in /*) echo "$1" ;; *) echo "$HOME/$1" ;; esac
  fi
}

# With no Mac to reach, this machine has to be one.
if [ -z "$LUACH_MAC_HOST" ] && ! command -v xcodebuild > /dev/null; then
  echo "no Mac to build on: set LUACH_MAC_HOST, or run this on a Mac with Xcode (ios/README.md, \"Settings\")" >&2
  exit 2
fi
