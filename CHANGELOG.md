# Changelog

All notable changes to SomaFM Bar. The format is loosely based on
[Keep a Changelog](https://keepachangelog.com/), and versions follow the plugin
manifest's `version` field.

## [1.9.3]

### Changed

- **AirPlay volume is now instant.** The receiver's own volume is driven through
  cliairplay's command pipe (`VOLUME=<0-100>` → AP2 `SET_PARAMETER`) instead of
  riding the mpv volume behind the ~2s stream buffer. `player` keeps mpv at full
  scale on AirPlay and sends the level to the bridge; the stored volume is
  re-applied whenever the session starts or resumes, and `status` reports the
  stored volume (not mpv's 100) while AirPlay is active. The volume slider now
  also streams while dragging, not just on release.
- `airplay-bridge`: new `volume <0-100>` command.

## [1.9.2]

### Added

- **Announce** toggle in the hidden Fun panel, plus `./player fun set --announce
  off`. The automatic screensaver-entrance burst can now be silenced; the choice
  is persisted in `fun-prefs.json`.

### Fixed

- `fun-bridge`: `pref_field` no longer collapses a stored boolean `false` to the
  fallback (the `jq` `// empty` idiom treats `false` as absent). This was latent
  for every field and becomes visible with the new boolean `announce` setting.
- `fun-bridge`: fail fast with a clear message if `jq` is missing.

## [1.9.1]

### Fixed

- Fun settings (Mode, Driver, Intensity, Rhythm) now persist in
  `~/.local/share/somafm-bar/fun-prefs.json` and survive a shell restart or
  reboot, instead of resetting to defaults.
- `fun-bridge start`: seed default settings from `fun-prefs.json` rather than
  hard-coded values, and mark the session live before the screensaver maps, so
  the announce service does not fire on top of a freshly started session.
- The random `Screensaver` driver is seeded from `$RANDOM`, so its pattern no
  longer repeats for launches within the same second.
- The announce burst now reads the player's `status.json` (which carries
  `running`/`paused`) instead of `state.json`, so the pause check actually
  applies. It also respects **Mode** and skips quietly when the stream is paused
  or not playing.

### Added

- `./player fun set [--mode …] [--driver …] [--intensity …] [--bpm …]` to save
  settings without starting a session.

## [1.9.0]

### Added

- Hidden **Fun** mode: raises the Omarchy screensaver and glitches the mpv audio
  in place, linked so the glitch clears the moment the screensaver is dismissed.
- Hidden reveal hotkey (`Super + Ctrl + Shift + F` by default) via the
  `io.github.ltillegal.somafm-bar` IPC target.
- Magenta Fun panel: Glitch on/off, Mode (AirPlay / Local / Both), Driver
  (Timer / Screensaver), Intensity and Rhythm (bpm) controls.
- Automatic entrance burst: a short escalating stutter when any screensaver
  appears while audio is playing, driven by a background shell service.

## [1.7.1]

### Added

- Green play state and a stream quality readout in the popup card.

## [1.7.0]

### Changed

- AirPlay sessions start asynchronously, and outputs switch without pausing.
- Popup clicks are queued instead of dropped while a command is running.
- Pre-warmed AirPlay sessions are parked and the feature source is logged.
- `airplay-bridge` unloads its null-sink if the session dies unexpectedly.

### Added

- A dedicated AirPlay 2 output via `cliairplay`.

## [1.6.0]

### Added

- Favorites and station search, with scrollable lists.
- An audio output picker in the popup card.

### Fixed

- RAOP stability.
