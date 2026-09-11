#!/bin/bash
set -euo pipefail
unset PYTHONPATH PYTHONHOME
export PYTHONNOUSERSITE=1
base=$(cd "$(dirname "$0")" && pwd -P)
root=${STASH_SKILL_HOME:-"$HOME/Library/Application Support/Stash Media Skill"}
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
  echo 'stash.sh doctor|inspect URL|download URL [--format mp4|mp3|original] [--quality best|1080|720|480] [--folder ABSOLUTE] [--request-id ID]|list [--status STATE]|status ID|play ID|retry ID [--request-id ID]|cancel ID|delete ID'
  exit 0
fi
/bin/bash "$base/bootstrap.sh" >&2
runtime=$(cat "$root/active.txt")
export STASH_SKILL_HOME="$root"
exec "$runtime/bin/python3" -I "$base/cli.py" "$@"
