# Changelog

All notable changes to SomaFM Bar. The format is loosely based on
[Keep a Changelog](https://keepachangelog.com/), and versions follow the plugin
manifest's `version` field.

## [1.11.2]

### Added

- Recordings carry **Genre: SomaFM**, allowing music libraries and iPods to
  group them by source. The station remains the album; artist and title retain
  the streamed song information.
- **Announcement filtering.** Skip Big Url and SomaFM station IDs, fundraising
  messages, and clips shorter than 30 seconds. `recordingMinSongSeconds` sets the
  duration threshold, measured from audio frames for MP3 and AAC.
- `./player record reload` applies recorder updates while keeping recording
  enabled, the completed-song count, and the session's quota usage. It discards
  the unfinished song and waits for the next full song.

## [1.11.1]

### Fixed

- Recording can start while playback is stopped or paused. Pausing, resuming,
  or stopping playback leaves recording uninterrupted, including the current
  song. Recording uses the selected station directly and follows station changes.
- Renamed the playback Stop button to **Stop playback** to distinguish it from
  **Stop recording**. The Record button is available without starting playback.

## [1.11.0]

### Added

- **Song recording.** Start recording from the popup while a stream plays.
  Complete songs are saved as separate, tagged MP3 or AAC files in the user's
  Music library under `SomaFM/<station>/`, using the stream's ICY metadata.
  Recording stays enabled through playback pauses, stops, and station changes.
  It skips songs already in progress and discards interrupted or unfinished songs.
- A configurable **20 GiB per-session quota** and disk reserve: recording stops
  before free space falls below 5 GiB or 5% of the filesystem, whichever is larger.
- A red bar indicator, recording status, and `./player record start|stop|status`.

## [1.10.0]

### Added

- **Local fallback when AirPlay cannot start.** If an AirPlay 2 session cannot be
  established — an unreachable receiver, or one that stops answering the session
  `SETUP` (the ap2 `SETUP` times out / RAOP answers `403`) — playback now
  continues on a local sink instead of going silent, with a notification naming
  the fallback. The remembered output is left on AirPlay and retried on the next
  fresh start; choosing an output, stopping, or a successful session clears the
  fallback. A detached watcher covers the async handshake, while immediate
  failures (refused port, missing host) fall back at once. Set
  `SOMAFM_AIRPLAY_FALLBACK=0` to disable.

## [1.9.4]

### Fixed

- The volume slider no longer jumps back and forth on AirPlay. Two sources fed
  the slider: `player status` (the effective volume) and the live `status.json`
  file, which reports mpv's own volume — pinned at 100 on AirPlay. The latter no
  longer drives the slider, so the effective volume is the single source.

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
