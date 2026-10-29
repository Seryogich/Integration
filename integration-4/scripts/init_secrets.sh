#!/usr/bin/env bash
# Generate the two secret files (random values, mode 0600). Never overwrites
# existing files unless --force is given.
set -euo pipefail
cd "$(dirname "$0")/.."

FORCE="${1:-}"
umask 077
mkdir -p secrets

make_secret() {
  local name="$1" bytes="$2"
  local path="secrets/${name}"
  if [[ -f "$path" && "$FORCE" != "--force" ]]; then
    echo "exists, kept : $path (use --force to rotate)"
    return
  fi
  # printf '%s' => no trailing newline; written in place with '>' (same inode)
  printf '%s' "$(openssl rand -base64 "$bytes")" > "$path"
  chmod 600 "$path"
  echo "created      : $path ($(wc -c < "$path" | tr -d ' ') bytes, mode 600)"
}

make_secret db_password 24
make_secret jwt_secret_key 48
