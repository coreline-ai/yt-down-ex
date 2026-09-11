#!/bin/bash
set -euo pipefail
unset PYTHONPATH PYTHONHOME
export PYTHONNOUSERSITE=1
umask 077
base=$(cd "$(dirname "$0")" && pwd -P)
root=${STASH_SKILL_HOME:-"$HOME/Library/Application Support/Stash Media Skill"}
case "$root" in /*) ;; *) echo 'STASH_SKILL_HOME must be absolute' >&2; exit 2;; esac
if [[ $(uname -s) != Darwin || $(uname -m) != arm64 ]]; then
  echo 'This package supports macOS Apple Silicon (arm64).' >&2; exit 2
fi
mkdir -p "$root"
if [[ -L "$root" ]]; then echo 'Runtime root must not be a symlink' >&2; exit 2; fi
if [[ -f "$root/active.txt" ]]; then
  runtime=$(cat "$root/active.txt")
  if [[ "$runtime" == "$root"/runtime-* && -x "$runtime/bin/python3" && -x "$runtime/bin/ffmpeg" && -x "$runtime/bin/ffprobe" && -x "$runtime/bin/node" && -x "$runtime/bin/yt-dlp" && -f "$root/tools.json" ]]; then
    echo "Runtime ready: $runtime" >&2
    exit 0
  fi
fi
if ! mkdir "$root/setup.lock" 2>/dev/null; then
  echo 'Setup is already running, or was interrupted. Check setup.lock/pid before removing the stale lock.' >&2; exit 3
fi
echo $$ > "$root/setup.lock/pid"
runtime="$root/runtime-1-$(date +%s)-$$"
cleanup() {
  if [[ ${runtime:-} == "$root"/runtime-* && -d "$runtime" ]] && [[ ! -f "$root/active.txt" || $(cat "$root/active.txt") != "$runtime" ]]; then
    rm -rf "$runtime"
  fi
  rm -rf "$root/setup.lock"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
mkdir -p "$root/bin"
manager="$root/bin/micromamba"
expected=d8d506fe8f8bc8d8c923a9434f5eba90d4ce3444a63ca1db08be8bb5ee51bc18
if [[ ! -f "$manager" ]] || [[ $(/usr/bin/shasum -a 256 "$manager" | /usr/bin/awk '{print $1}') != "$expected" ]]; then
  /usr/bin/curl --fail --location --proto '=https' --proto-redir '=https' --connect-timeout 20 --max-time 180 --retry 2 \
    https://github.com/mamba-org/micromamba-releases/releases/download/2.3.2-0/micromamba-osx-arm64 -o "$root/setup.lock/micromamba"
  [[ $(/usr/bin/shasum -a 256 "$root/setup.lock/micromamba" | /usr/bin/awk '{print $1}') == "$expected" ]] || { echo 'Bootstrap SHA-256 mismatch' >&2; exit 4; }
  chmod 700 "$root/setup.lock/micromamba"
  mv "$root/setup.lock/micromamba" "$manager"
fi
echo 'Installing isolated Python, FFmpeg/ffprobe and Node (first use only)…' >&2
"$manager" --no-rc --root-prefix "$root/mamba" create --yes --prefix "$runtime" --override-channels --channel https://conda.anaconda.org/conda-forge --strict-channel-priority 'python=3.11' 'ffmpeg=8' 'nodejs=22' pip >&2
"$runtime/bin/python3" -I -m pip --isolated install --disable-pip-version-check --no-deps --require-hashes --only-binary=:all: --index-url https://pypi.org/simple --timeout 30 --retries 2 -r "$base/requirements-engine.txt" >&2
"$runtime/bin/python3" -I - "$root" "$runtime" <<'PY'
import json,os,subprocess,sys
from pathlib import Path
root,runtime=map(Path,sys.argv[1:])
tools={k:str(runtime/'bin'/k) for k in ('ffmpeg','ffprobe','node','yt-dlp')}
versions={}
for name,path in tools.items():
    versions[name]=subprocess.check_output([path,'-version' if name in ('ffmpeg','ffprobe') else '--version'],stderr=subprocess.STDOUT,timeout=20,text=True).splitlines()[0]
subprocess.run([sys.executable,'-c','import yt_dlp, yt_dlp_ejs'],check=True,timeout=20)
enc=subprocess.check_output([tools['ffmpeg'],'-hide_banner','-encoders'],stderr=subprocess.STDOUT,timeout=20,text=True)
if 'libx264' not in enc or ' aac ' not in enc:raise RuntimeError('Required MP4 encoders unavailable')
for name,value in [('tools.json',tools),('runtime-versions.json',versions)]:
    temp=root/(name+'.tmp');temp.write_text(json.dumps(value,indent=2));os.replace(temp,root/name)
temp=root/'active.tmp';temp.write_text(str(runtime));os.replace(temp,root/'active.txt')
print(json.dumps({'ok':True,'runtime':str(runtime),'versions':versions}))
PY
