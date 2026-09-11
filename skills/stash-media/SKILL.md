---
name: stash-media
description: Download a video URL as verified MP4, extract MP3 audio, list or retry local downloads, and open saved media when the user asks to download or play media (다운해줘, 음원만 받아줘, 받은 영상 재생해줘). Runs independently of Chrome with automatic local tool setup on macOS Apple Silicon.
---

# Stash Media

Use this skill's `scripts/stash.sh` by its absolute installed path. First execution installs its isolated runtime automatically; no Chrome extension, Node project, Homebrew or system Python is required. Natural-language interpretation belongs to the agent; the command accepts structured arguments, not natural-language strings.

## Requests → commands

| User intent | Command arguments after stash.sh |
|---|---|
| Download video / MP4로 다운해줘 | `download URL --format mp4 --request-id UUID` |
| Extract audio / 음원만 MP3로 | `download URL --format mp3 --request-id UUID` |
| Preserve source format | `download URL --format original --request-id UUID` |
| Inspect available metadata | `inspect URL` |
| List downloads / failed ones | `list` / `list --status failed` |
| Check one job | `status JOB_ID` |
| Play a downloaded file | `play JOB_ID` |
| Retry a failed job | `retry JOB_ID --request-id NEW_UUID` |
| Cancel a running job | `cancel JOB_ID` |
| Delete a record | `delete JOB_ID` (file is retained) |
| Diagnose installation | `doctor` |

Use `--quality best|1080|720|480` and `--folder ABSOLUTE_PATH` only when requested. Default: MP4 and `~/Downloads/Stash Media`. Quote each shell argument safely; never interpolate URL/title text as shell code. Missing URL: use an unambiguous URL already supplied in the conversation or ask for it. Do not guess a site URL.

Keep the returned jobId for “방금 요청한 것”. If the target is not in this conversation, list records and use a single unambiguous match; clarify when multiple records fit. Preserve the request ID when retrying a command whose response was lost; use a new request ID for an intentional new download. Duplicate requests return the existing job rather than starting another download.

## Execution and truthful results

- stdout is one final JSON object; progress events are JSON on stderr. A long-running command must be awaited/polled using the host's process/session tools until completion. Do not repeat a still-running download.
- Only `ok:true` with job state `completed` and `verification.decodeExitCode:0` proves a successful download. Report the absolute file path and actual video/audio codecs. Do not report MP4 success for an OGG original or an audio-only file.
- `play` verifies the saved file identity and asks macOS's default player to open it. `opened:true` means the OS accepted the open request, not that playback or sound was observed. If inline local media display is available, also show the returned file using that host's supported syntax. Do not claim playback was observed unless it was actually checked.
- On `DOWNLOAD_BUSY`, inspect existing jobs or wait; do not kill an unrelated process or switch databases. Only one download runs at a time. List/status/cancel remain available while it runs.
- Records/runtime are under `~/Library/Application Support/Stash Media Skill`, separate from the Chrome app. Closing the agent's process can interrupt a download; there is no persistent background service or shared Chrome history.
- Temporary network failures have at most three automatic retries. Access-denied, format and verification failures are returned explicitly. Do not bypass login/DRM restrictions or substitute another sample and claim the requested URL worked.
- Setup is user-local and network-dependent. If setup fails, report the real failure. Never remove a live setup.lock; its pid file identifies the installer. The supported/validated platform is macOS arm64.
