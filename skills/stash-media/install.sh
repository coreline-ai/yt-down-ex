#!/bin/bash
set -euo pipefail
umask 077
source_dir=$(cd "$(dirname "$0")" && pwd -P)
destination="${CODEX_HOME:-$HOME/.codex}/skills/stash-media"
cd "$source_dir"
/usr/bin/shasum -a 256 -c SHA256SUMS >/dev/null
mkdir -p "$(dirname "$destination")"
if [[ "$source_dir" != "$destination" ]]; then
  if [[ -e "$destination" ]]; then
    echo "Skill already exists: $destination. Existing files were preserved; use its install.sh or explicitly replace it after review." >&2
    exit 3
  fi
  /usr/bin/ditto "$source_dir" "$destination"
fi
/bin/bash "$destination/scripts/bootstrap.sh"
echo "Installed skill: $destination" >&2
echo 'Use a new task or refresh skills, then ask: 이 주소 MP4로 다운해줘.' >&2
