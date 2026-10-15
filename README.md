# SomaFM Bar

Bar widget for [Omarchy](https://omarchy.org/) that plays a SomaFM station through `mpv`, with a popup card for playback control.

![preview](preview.png)

## What it does

- A note icon in the bar that turns green while the station is playing.
- Left-click opens the popup card under the icon — nothing starts playing until you press **Play**.
- Popup card: current track title, Play/Pause (highlighted green while playing), Stop, a volume slider, and the list of audio outputs.
- The playback state and the stream quality (for example `128 kbps MP3`, parsed from the station URL) are shown in the card and in the bar tooltip.
- Copy button next to the title puts the current track title on the clipboard and closes the card.
- Right-click the bar icon stops playback, middle-click toggles play/pause, scroll wheel changes volume in 5% steps.
- The popup closes on outside click or `Esc`.
- Volume and audio output are remembered between sessions.
- A hidden **Fun** mode raises the Omarchy screensaver and glitches the audio along with it — see [Hidden: Fun](#hidden-fun-glitch--screensaver).

Every PipeWire sink shows up in the **Output** list of the card, so the stream can go to the built-in speakers, headphones or a network device such as an AirPlay speaker (Sonos, HomePod, Apple TV). AirPlay 2 receivers configured in `airplay.json` also appear as a dedicated **AirPlay 2 (<name>)** output. Selecting a row switches playback immediately while the stream keeps playing.

## Requirements

External commands used by the plugin (all in the Arch `extra`/`multilib` repositories):

| Command | Package | Used for |
| --- | --- | --- |
| `mpv` | `mpv` | audio playback and ICY track metadata |
| `jq` | `jq` | JSON parsing for config and IPC payloads |
| `socat` | `socat` | talking to the `mpv` IPC socket |
| `wl-copy` | `wl-clipboard` | the copy-title button |
| `pactl` | `pipewire-pulse` (or `pipewire-utils`) | listing audio outputs |
| `python3` | `python` | reading AirPlay 2 receiver features (optional) |

Omarchy itself already provides `mpv` and PipeWire on most installations. `mpv` is started with `--audio-display=no`, so the stream never produces a video window. The AirPlay 2 output additionally needs the `cliairplay` sender (see [AirPlay 2 output](#airplay-2-output)).

## Install

```bash
omarchy plugin add https://github.com/ltillegal/somafm-bar.git --enable
```

Or by hand:

```bash
git clone https://github.com/ltillegal/somafm-bar.git ~/.config/omarchy/plugins/io.github.ltillegal.somafm-bar
omarchy-shell shell rescanPlugins
omarchy plugin enable io.github.ltillegal.somafm-bar
```

The plugin id must match the directory name (`io.github.ltillegal.somafm-bar`), which is what `omarchy plugin add` does for you.

## Uninstall

```bash
omarchy plugin remove io.github.ltillegal.somafm-bar
```

If you added the keyboard shortcut below, remove it from `~/.config/hypr/bindings.lua` and run `hyprctl reload`.

## Configuration

Edit `config.json` in the plugin folder and then use **Stop** and **Play** (or restart the shell):

```json
{
  "station": "SomaFM Bossa Nova",
  "url": "http://ice6.somafm.com/bossa-128-mp3"
}
```

- `station` — the name shown in the widget tooltip when nothing is playing.
- `url` — a direct SomaFM stream URL. Channel names map to `https://ice2.somafm.com/<channel>-128-mp3`, for example `groovesalad`, `dronezone`, `indiepop`, `secretagent`, `defcon`, `thetrip`, `sonicuniverse`, `u80s`, `fluid`, `beatblender`, `cliqhop`, `dubstep`, `space-station-soma`, `metal`, `covers`, `folkfwd`, `left coast 70s`, `piano bar`, `voodooclub`.

Playback volume and audio output live outside the repository and are stored per user:

- `$XDG_RUNTIME_DIR/somafm-bar/` — mpv IPC socket, player pid, `status.json`, `mpv.log`
- `$XDG_DATA_HOME/somafm-bar/state.json` — remembered volume and output

### Audio output

The **Output** list in the popup card picks the PipeWire sink. The same switch works headlessly with the `player` script in this folder:

```bash
./player outputs     # id + label of every PipeWire sink
./player output <id> # switch, e.g. ./player output alsa_output.pci-0000_00_1b.0.analog-stereo
./player output      # go back to the system default
```

Legacy AirPlay 1 / RAOP sinks such as Sonos show up once `pipewire-zeroconf` and the `raop-discover` module are configured — see the
[omacom/omarchy AirPlay guide](https://github.com/omacom/omarchy/discussions/3943).

### AirPlay 2 output

Newer Apple receivers (macOS Ventura and later, HomePod, Apple TV) refuse the legacy RAOP/AirPlay 1 handshake and answer `403 Forbidden`. For those the plugin ships a dedicated AirPlay 2 output driven by the `cliairplay` AirPlay 2 sender.

It creates a private PipeWire null-sink named after the target and pipes that sink's monitor into `cliairplay`, so playback, pause/resume, volume and output switching behave like any other sink. The session is always torn down with a graceful AirPlay `STOP`.

While an AirPlay 2 output is active the level is applied on the **receiver** itself (AP2 `SET_PARAMETER`), so moving the slider is heard immediately instead of lagging behind the stream's ~2s buffer. `mpv` is held at full scale and the remembered volume lives in `state.json`, exactly as for local outputs.

Requirements:

- `python3` — used to read the receiver's `GET /info` `features`; optional, falls back to the `txt` field below.
- `cliairplay` on `PATH`, with permission to bind the PTP ports:

```bash
sudo setcap cap_net_bind_service=+ep "$(command -v cliairplay)"
```

Configure one or more targets in `$XDG_DATA_HOME/somafm-bar/airplay.json`:

```json
{
  "targets": [
    {
      "id": "airplay2.LivingRoom",
      "name": "Living Room",
      "host": "LivingRoom.local",
      "port": 7000,
      "password": "",
      "txt": "features=0x4A7FCFD5,0x38174FDE flags=0x284 model=AppleTV6,2 srcvers=870.14.25 deviceid=AA:BB:CC:DD:EE:FF acl=0 fex=1c9/St5PFzg2IQw protovers=1.1"
    }
  ]
}
```

- `id` — the synthetic output id; also the PipeWire sink name (`airplay2.LivingRoom`).
- `name` — shown in the Output list as `AirPlay 2 (<name>)`.
- `host` / `port` — the receiver; `host` may be an mDNS name or an IP.
- `password` — the receiver's AirPlay password (may be empty).
- `txt` — fallback AirPlay TXT record carrying the device `features`. The receiver's own `GET /info` plist supplies this automatically when reachable; the fallback is required when `/info` is refused. A wrong or missing feature set selects NTP timing and the stream `SETUP` fails (PTP timing is required).

The bridge helper lives at `airplay-bridge` in this folder and is driven by the `player` script; you normally never call it directly.

## Stations & Favorites

The popup card now includes a searchable station list with favorites:

- **Favorites** — scrollable list of your saved stations. Click a favorite to switch instantly. Click the star to remove it.
- **All Stations / Search results** — scrollable list pulled live from SomaFM (cached for 1 hour). Type in "Search stations..." to filter by name/description. Click the star to add/remove from favorites.
- Stations are switched directly from the popup (the card stays responsive while switching).

Manage favorites headlessly with the player script:

```bash
./player stations     # list all SomaFM stations (JSON)
./player fav-list     # list favorites (JSON)
./player fav-add "Station Name" "http://..."  # add favorite
./player fav-remove "http://..."              # remove by URL
./player switch "Station Name" "http://..."   # switch station
```

## Hidden: Fun (glitch + screensaver)

The **Fun** panel is a hidden feature — it does not show up in the popup card
unless you know the gesture.

<details>
<summary>Spoiler — click to reveal how to open Fun</summary>

**Press `Super + Ctrl + Shift + F`.** The card opens with the magenta **Fun**
panel pinned above the Output and station lists; the panel is hidden again as
soon as the card closes. A plain left click opens the normal card as usual.

The key is not bound for you — add it to `~/.config/hypr/bindings.lua` and run
`hyprctl reload`:

```lua
o.bind("SUPER + CTRL + SHIFT + F", "SomaFM Fun", "omarchy-shell io.github.ltillegal.somafm-bar fun")
```

(`SUPER + SHIFT + F` is Omarchy's **File manager** default, so the extra `Ctrl`
keeps this hidden key out of the way.)

The hidden entry point is just an IPC target, so you can bind any key (or call
it by hand):

```bash
omarchy-shell io.github.ltillegal.somafm-bar fun
```

`Ctrl + left click` on the icon would be the natural choice, but the bar host
swallows bar-widget left clicks and re-dispatches them without the modifier, so
a hotkey is what actually works.

Once revealed, **Glitch: off/on** turns playback into something you can feel: it
raises the Omarchy screensaver (the `ttfx` full-screen text effects) and, while
it is on screen, glitches the mpv audio in place. The two are hard-linked — the
moment the screensaver is dismissed (any keystroke or pointer motion) the glitch
is cleared and the session ends.

The glitch is synthetic: an `acrusher` (bit/sample-crusher) chain is applied to
mpv through its IPC socket, so it needs no extra CPU load and works on any
machine. It is heard on the output that is currently playing.

- **Mode** — which output the glitch may play on: `AirPlay`, `Local`, or `Both`.
  Audio goes to one sink at a time, so this is a guard: picking `AirPlay` while
  the stream plays locally leaves the screensaver running but keeps the audio
  clean. `AirPlay` also matches the synthetic AirPlay 2 outputs.
- **Driver** — the tempo source. `Timer` fires discrete glitch bursts at the
  **Rhythm** (bpm; `0` = steady). `Screensaver` keeps a light base glitch with
  random spikes, mimicking the changing text effects.
- **Intensity** — how hard the bit/sample reduction bites.
- **Announce** — whether the automatic entrance burst (below) fires at all.

Mode, Driver, Intensity, Rhythm and Announce are remembered: they are written to
`~/.local/share/somafm-bar/fun-prefs.json`, so the panel comes back exactly as
you left it after a shell restart or a reboot.

Whenever the screensaver appears — whether the Fun hotkey raised it or the
machine drifted into idle on its own — the widget announces the transition with
a short glitch burst: a ~3-second escalating stutter that then clears. It runs
from a background shell service, so it fires with the popup closed, and it
stays silent whenever a full Fun session already owns the glitch, the stream is
paused, or the active output is excluded by **Mode**. Turn it off with the
**Announce** toggle in the panel (or `./player fun set --announce off`) if the
idle transition should stay quiet.

Requirements: the same terminal the Omarchy screensaver needs (Alacritty, Foot,
Ghostty or Kitty), and the screensaver must be enabled (`omarchy toggle
screensaver`).

Headless control, through the `player` script:

```bash
./player fun start --mode airplay --driver timer --intensity 70 --bpm 120
./player fun start --mode both --driver screensaver --intensity 50 --bpm 0
./player fun set --intensity 50   # save settings without starting a session
./player fun set --announce off   # silence the automatic entrance burst
./player fun stop
./player fun burst 90        # one-shot announcement burst, then clean audio
./player fun status
```

</details>

## Keyboard shortcut

Optional. The widget ships an IPC target, so any toggle works. Add to `~/.config/hypr/bindings.lua` and run `hyprctl reload`:

```lua
o.bind("SUPER + SHIFT + R", "SomaFM", "omarchy-shell shell toggle io.github.ltillegal.somafm-bar")
```

The widget is driven by the shell's generic plugin targets:

```bash
omarchy-shell shell toggle io.github.ltillegal.somafm-bar   # open or close the card
omarchy-shell shell summon io.github.ltillegal.somafm-bar   # open
omarchy-shell shell hide io.github.ltillegal.somafm-bar     # close
```

## Privacy

The plugin talks to exactly one host: the stream URL from `config.json` (SomaFM). It writes no telemetry, reads no files outside the plugin folder and the two directories above, and touches the clipboard only when you click the copy button.

## License

MIT — see [LICENSE](LICENSE).