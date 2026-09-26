# Akai Force → FL Studio

The Akai Force as a full FL Studio controller (touchscreen, pads, knob OLEDs, transport),
the way it works with Ableton Live.

## Install

**📖 [User manual (PDF)](docs/Akai-Force-FL-Studio-Manual.pdf)**: setup, every mode and control, troubleshooting.

1. Install Akai's **Network Driver** (inMusic Software Center → My Hardware, or akaipro.com), restart, and pair
   your Force in the Akai Network Driver app. Windows and Intel Macs only.
2. Install the script, whichever way is easiest:
   - **Download** `AkaiForceLive-v1.2.0.zip` from [Releases](../../releases/latest), unzip, double-click **`install.bat`**.
   - **PowerShell one-liner:**
     ```powershell
     irm https://raw.githubusercontent.com/Pyrodrifter/akai-force-fl-studio/main/install.ps1 | iex
     ```
   - **macOS (Intel, untested):**
     ```sh
     curl -fsSL https://raw.githubusercontent.com/Pyrodrifter/akai-force-fl-studio/main/install.sh | sh
     ```
3. In FL Studio, set up MIDI Settings as described in [FL Studio setup](#fl-studio-setup) below.
4. On the Force: **MENU → LIVE CONTROL**.

No server, VST or extra software is needed: the script runs inside FL Studio, which has its own Python.
To uninstall, run `install.bat -Uninstall`.

## How it works

The Force's "Live Control" mode uses a plain-MIDI protocol over the **Akai Network MIDI**
driver, on the `Akai Network - DAW Control` port. The protocol comes from Ableton's own
`Akai_Force_MPC` remote script:

- **Handshake:** the host sends `F0 47 00 7F 00 F7` about every 3 s, and the Force replies
  `F0 47 00 40 01 F7`.
- **The host never draws the screen.** The Force draws its own session, mixer and device
  pages from names (SysEx text), colors (a 70-color palette) and values (CC / note velocity).
- **Pads send pressure as repeated note-ons.** The first one is the velocity, later ones are
  pressure, and velocity 0 is the release.

```
Akai Force ──(Akai Network - DAW Control)──> FL Studio: device_AkaiForce.py + force_protocol.py
```

No VST and no separate bridge app. FL's Python controller script is the go-between.

## Files

| File | What it is |
|---|---|
| `device_AkaiForce.py` | The FL Studio controller script |
| `force_protocol.py` | Protocol constants, message builders, full control map (no dependencies) |
| `force_plugin_maps.py` | Your own knob pages per plugin (see [Plugin pages](#plugin-pages)). The installer copies it once and never overwrites it |
| `install.ps1` / `install.bat` / `install.sh` | Installers: copy both script files into FL's Hardware folder, check for FL and the Akai driver, `-Uninstall` to remove |
| `docs/` | The PDF manual and `build_manual.py`, which rebuilds it (needs Chrome or Edge) |
| `requirements.txt` | Python packages for the optional desktop tools only |
| `fl_sim.py` | Runs the script outside FL against a fake project: `python fl_sim.py` (checks), `--live` (real Force). Without FL installed: `pip install fl-studio-api-stubs` |
| `force_probe.py` | Low-level protocol probe / logger, no DAW involved |

## Requirements

- An Akai Force with Live Control (the Ableton controller mode), on the same network as the PC.
- The **Akai Network MIDI** driver on the PC (it provides the `Akai Network - DAW Control` port).
- FL Studio with Python controller scripting. Developed and tested on FL Studio 2026 (v26.1).
- For the optional desktop tools only: Python 3 with `pip install mido python-rtmidi`.

## FL Studio setup

1. Close anything else using the DAW Control port (Ableton, `force_probe.py`, `fl_sim.py --live`).
2. FL: **Options → MIDI Settings**.
   - Input `Akai Network - DAW Control`: enable it, set Controller type to
     **Akai Force (Live Control)**, and set Port to any free number, e.g. **1**.
   - Output `Akai Network - DAW Control`: set Port to the **same number**.
3. Put the Force in Live Control mode. The knob OLEDs briefly show `PERFORM` when it connects.
4. For PERFORM mode, turn on Performance Mode in FL's playlist.

If the script isn't in the Controller type list, click **Update MIDI scripts** in MIDI Settings (or restart FL).

## Controls

| Control | Action |
|---|---|
| LAUNCH / SHIFT+LAUNCH | Next / previous pad mode (the mode name flashes on the knob OLEDs) |
| Pads | Depends on mode (see below) |
| Right-hand row buttons | Depends on mode (see below) |
| ◀ ▶ | Mixer bank (SHIFT = ×8). PERFORM: scroll blocks. STEPS: page steps. In both, SHIFT+◀ ▶ banks the mixer |
| ▲ ▼ (SHIFT = coarse or fine) | Playlist tracks / pattern page / channels / octave (SHIFT = semitone) / drum bank / marker page |
| Knobs, mixer mode | Volume of the 8 visible inserts. Touch a knob to see dB on its OLED. SHIFT = fine |
| Knobs, device mode | 8 params of the selected channel's plugin, the selected insert's FX slot, or a focused effect window |
| Track select row | Select mixer insert |
| MUTE / SOLO / REC ARM / CLIP STOP | Set what the lower button row does (mixer inserts). In PERFORM they also set the right-hand buttons: mute / solo / stop the playlist track. CLIP STOP row in PERFORM: launch the block column above |
| SHIFT + first lower-row button | Quantize the selected channel (also the on-screen Quantize button) |
| COPY | Clone the current pattern. PLUGIN: SHIFT+COPY prints the plugin's parameters for `force_plugin_maps.py` |
| SHIFT+DELETE | STEPS: clear the selected channel's steps in this pattern |
| SHIFT+SELECT | Pad pressure → poly aftertouch on/off (SELECT lights when on) |
| PLAY / STOP / REC | Transport |
| TAP TEMPO / SHIFT+TAP | Tap tempo / metronome. Flashes on the beat while playing |
| ASSIGN A | Show the next FL window: mixer → channel rack → playlist → piano roll (SHIFT = back) |
| ASSIGN B | Pattern / song mode (lit in song mode) |
| UNDO / SHIFT+UNDO | Undo / redo |
| MASTER | Select the master track (lit while selected) |
| Touchscreen | Faders, pan, sends, mute/solo/arm, clip grid, device params, tempo entry, song-position encoder, transport buttons (below) |
| Device page prev/next device | Previous/next channel, or FX slot. SHIFT+prev/next switches between the channel's plugin and the selected insert's effect chain |

ASSIGN A / B can do other things: set `ASSIGN_A` / `ASSIGN_B` in the script to one of `windows`, `song_mode`,
`mixer`, `channel_rack`, `playlist`, `piano_roll`, `browser`, `metronome`, `loop_record`, `step_edit` or `none`.

### On-screen transport buttons

| Button | Action |
|---|---|
| Metronome / Loop | Metronome / pattern-song mode (both light when on) |
| Overdub | FL's overdub recording. SHIFT = loop recording. FL can't report overdub's state, so this one doesn't light |
| Automation arm | FL's count-in before recording (lit when on). FL has no script access to automation recording |
| Arrangement record | Record into the song: song mode + record + play. Again = stop recording (lit while recording in song mode) |
| Follow | STEPS, PATTERNS and SONG pages follow the playhead (lit when on) |
| Device lock | Keep the device page / PLUGIN mode on the current plugin while you select others (lit when locked) |
| Nudge − / + | Tempo −/+ 1 BPM (SHIFT = 0.1) |
| Quantize value | Step FL's snap: none, 1/4 step, 1/2 step, step, 1/2 beat, beat, bar (SHIFT = back) |
| Insert scene | New empty pattern. SHIFT = add a playlist marker at the playhead |

### Pad modes

| Mode | Pads | Right-hand buttons |
|---|---|---|
| PERFORM | FL Performance Mode, laid out like the playlist: rows = playlist tracks, columns = blocks. SHIFT+pad = launch the whole column. Needs Performance Mode switched on in FL (the screen says so if it's off) | Mute / solo / stop that track (follows the MUTE/SOLO/CLIP STOP buttons) |
| PATTERNS | 64 patterns. Press to select. The current pattern shows as playing. While playing in pattern mode, a pad queues its pattern (it blinks) and FL switches at the next bar; press it again or SHIFT+pad to switch now | – |
| STEPS | Step sequencer: rows = channels, columns = 8 steps of the current pattern. Pads mirror the channel rack: lit = on, dark = off. Tap = toggle. **Hold a step and turn knobs 1–7** to edit its pitch, velocity, release, fine pitch, pan, Mod X, Mod Y (values on the OLEDs). The playhead runs along the button row under the pads. Piano-roll channels are marked "(piano roll)" and show no steps, like FL's channel rack. New steps take the pad's velocity (hit hard = accent). **Hold a step and tap another in the row** to fill the steps between. SHIFT+pad selects the channel | Select that channel. **Hold one and press another** to copy the first channel's steps to the second |
| KEYS | Keyboard to the selected channel. Chromatic: rows a 4th apart. In a scale, only in-key notes, rows 3 degrees apart. Root = bottom-left note (▲▼ octave, SHIFT+▲▼ semitone) | Pick the scale: Chromatic, Major, Minor, Dorian, Mixolydian, Harmonic minor, Major/Minor pentatonic |
| DRUMS | 4×4 quadrants from C3 (FPC / Slicex / drum plugins) to the selected channel | – |
| CHANNELS | Each pad triggers a channel-rack channel. SHIFT+pad selects it | – |
| SONG | One pad per bar of the song; press to jump there (switches FL to song mode). The current bar lights and the page follows playback. With playlist markers, marker bars show the marker name and each section takes the marker's colour; without markers, 4-bar phrases alternate shades | – |

### Plugin pages

The device page and PLUGIN mode step through a plugin's parameters 8 at a time. For the plugins you use most, you
can choose and name the pages yourself in `force_plugin_maps.py`:

```python
PLUGIN_MAPS = {
    "Sytrus": [
        ("Filter", ["Cutoff", "Resonance", "Env", "", "", "", "Drive", "Mix"]),
        ("Amp", ["Attack", "Decay", "Sustain", "Release"]),
    ],
}
```

Select the plugin, go to PLUGIN mode and press SHIFT+COPY: the script prints an entry with every parameter in
FL's **View → Script output**, ready to paste and trim. Parameters can be names (not case-sensitive) or numbers.
Your pages come first, then the automatic banks (`APPEND_ALL_PARAMS`). Click **Reload script** after editing.

### Sends

The mixer page's send knobs A–D control routing from each strip to up to four "send" inserts.
By default the script uses the first four inserts whose names contain *send, reverb, verb,
delay, bus* or *fx*. Set `SEND_TRACKS` in the script to choose them yourself, e.g. `(20, 21)`.
Turning a send on a strip that isn't routed yet creates the route.

## Building sets with Claude

The companion [flstudio-mcp fork](https://github.com/Pyrodrifter/flstudio-mcp) lets Claude
drive FL Studio directly. It can lay out a whole Performance Mode set for the PERFORM pads:
clips in a grid, block markers and the Start marker, per-track launch settings, notes, FL presets
and mixer effects. Its
[`examples/techno_live`](https://github.com/Pyrodrifter/flstudio-mcp/tree/main/examples/techno_live)
builds a 12-row, 8-scene techno set from an empty project; launch it from PERFORM mode.

## Known limits

- The mixer strips and knobs are FL **mixer inserts**; the PERFORM pad rows are **playlist
  tracks**. FL doesn't tie these together the way Ableton tracks are.
- SONG mode: FL's script API can name markers but not say where they are, so the script maps
  marker positions when you enter SONG mode (only while stopped), briefly moving the playhead and
  putting it back. Bars always work, markers or not.
- STEPS channel loops (hold a channel button + tap a pad = loop that channel at that step) use an undocumented FL
  function, so they're off until you set `STEPS_CHANNEL_LOOP = True`.
- PATTERNS queueing switches from FL's idle loop, so the switch can land a few milliseconds after the bar line.
- STEPS mode can't ask FL whether a channel is a piano-roll channel. It treats a generator plugin
  whose notes use more than one pitch as piano roll. If that hides a real step pattern, set
  `STEPS_HIDE_PIANO_ROLL = False` in the script.
- Dark FL colours (like the default channel grey) are brightened so pads don't look unlit
  (`MIN_BRIGHTNESS` in the script).
- Not possible in Live Control mode: custom screens, note repeat, the crossfader, and the loop
  start/length encoders (FL has no script access to the playlist loop).
- `Akai Network - MIDI` (the second port) is separate from this script. Enable it in FL as a
  generic input to record the Force's own sequencer, or send FL's MIDI clock to it when the Force
  runs standalone.

## License

MIT, see [LICENSE](LICENSE).
