# Security review — 2026-10-25

Reviewed upstream `ltillegal/somafm-bar` at
`a02ff6c1933bef7d5e705c01ff4f5554857e4832` (version 1.10.0), then applied the
hardening below in `jlmrt/somafm-bar` before installation.

## Result

No malicious behavior, telemetry, credential harvesting, automatic dependency
installation, or automatic privilege escalation was found. Suitable for normal
SomaFM playback after the hardening below, within the limits of a source review.
This is not a guarantee that the software is free of vulnerabilities.

## Scope

Read all executable source: `BarWidget.qml`, `Service.qml`, `player`,
`player-status.lua`, `airplay-bridge`, and `fun-bridge`. Also inspected all other
tracked files, the Git tree, manifest, configuration, license, and recent history.
There are no vendored executables, submodules, package-install hooks, dependency
lockfiles, or GitHub Actions workflows in this revision. The plugin uses existing
system programs, including mpv, curl, jq, socat, PipeWire tools, and wl-copy.

Reviewed process execution, network requests, clipboard access, persistent writes,
IPC, PID handling, AirPlay, and screensaver integration. Dynamic text is passed
as command arguments or JSON rather than evaluated as shell code. Runtime/data
directories use mode 0700 and helpers use umask 077. The main player verifies its
tracked process start time before stopping it.

## Hardening applied

- Changed the default and fallback stream from HTTP to HTTPS. Confirmed the
  default HTTPS endpoint responds successfully.
- Restricted catalog fetching to HTTPS, reject HTTP errors, and cap downloads,
  accepted responses, and cache reads at 4 MiB. Oversized caches are ignored;
  failed downloads can still use an acceptable stale cache.
- Added the `--` argument separator to wl-copy so a track title beginning with
  a dash is treated as text.
- Fixed an upstream first-run error: `station_url` read an uninitialized local
  variable under `set -u` before any station override existed. A regression
  test reproduces the original failure and verifies the default HTTPS URL.
- Corrected the README's privacy claim: the catalog, selected stream/playlist,
  and configured AirPlay receivers can use different hosts.

## Remaining limits and optional features

- Omarchy plugins run unsandboxed with the user's permissions. Review subsequent
  changes before updating; this review covers the specified revision and patches.
- HTTP custom/catalog streams remain supported. A stream or playlist can lead
  to other hosts. The media stack and system dependencies were not audited.
- AirPlay is optional and needs a separately installed `cliairplay`. No sender,
  receiver configuration, passwords, or network capabilities were installed as
  part of this setup. If configured later, receiver passwords are supplied as
  command arguments and may be visible through local process inspection.
- The AirPlay feature probe has a socket timeout but no total response-size
  limit. Only configure receivers you trust. The AirPlay and Fun helpers track
  PIDs without the main player's start-time check, so stale state may target an
  unrelated process after PID reuse. Those optional paths were reviewed but
  were not exercised against real receivers or a screensaver session.
- The hidden Fun service observes screensaver events and can change audio
  filters when its saved output mode allows it. Its default AirPlay mode is
  inactive for ordinary local playback without AirPlay targets.

## Validation

Run `python3 tests/security.py` for isolated catalog download/cache regression
tests. Also checked Bash syntax, Lua syntax, QML parsing, Git object integrity,
and Omarchy manifest validation. Playback and shell integration results are
reported separately at installation time.

Installation verification on 2026-10-25: six regression tests passed. Installed
and enabled from `https://github.com/jlmrt/somafm-bar.git` in the left bar section.
The live catalog returned 51 stations, and the shell successfully opened and
closed the widget. At code revision
`70fa4cc17625a24d3208e596aa57acd1d03917ce`, a zero-volume test confirmed decoded
HTTPS audio, track metadata, pause, resume, and stop. Original volume was restored
and playback left stopped. The installed code matched the Projects checkout.
The shell configuration was backed up before installation.
