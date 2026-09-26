# Akai Force → FL Studio

The Akai Force as a full FL Studio controller (touchscreen, pads, knob OLEDs, transport),
the way it works with Ableton Live.

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
| `install.ps1` | Copies both files to `Documents\Image-Line\FL Studio\Settings\Hardware\Akai Force Live` |
| `fl_sim.py` | Runs the script outside FL against a fake project: `python fl_sim.py` (checks), `--live` (real Force) |
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
| COPY | Clone the current pattern |
| SHIFT+DELETE | STEPS: clear the selected channel's steps in this pattern |
| SHIFT+SELECT | Pad pressure → poly aftertouch on/off (SELECT lights when on) |
| PLAY / STOP / REC | Transport |
| TAP TEMPO / SHIFT+TAP | Tap tempo / metronome |
| UNDO / SHIFT+UNDO | Undo / redo |
| MASTER | Select the master track |
| Touchscreen | Faders, pan, sends, mute/solo/arm, clip grid, device params, tempo entry, song-position encoder |
| Device page prev/next device | Previous/next channel, or FX slot. SHIFT+prev/next switches between the channel's plugin and the selected insert's effect chain |

### Pad modes

| Mode | Pads | Right-hand buttons |
|---|---|---|
| PERFORM | FL Performance Mode, laid out like the playlist: rows = playlist tracks, columns = blocks. SHIFT+pad = launch the whole column. Needs Performance Mode switched on in FL (the screen says so if it's off) | Mute / solo / stop that track (follows the MUTE/SOLO/CLIP STOP buttons) |
| PATTERNS | 64 patterns. Press to select. The current pattern shows as playing | – |
| STEPS | Step sequencer: rows = channels, columns = 8 steps of the current pattern. Pads mirror the channel rack: lit = on, dark = off. Tap = toggle. **Hold a step and turn knobs 1–7** to edit its pitch, velocity, release, fine pitch, pan, Mod X, Mod Y (values on the OLEDs). The playhead runs along the button row under the pads. Piano-roll channels are marked "(piano roll)" and show no steps, like FL's channel rack. SHIFT+pad selects the channel | Select that channel |
| KEYS | Keyboard to the selected channel. Chromatic: rows a 4th apart. In a scale, only in-key notes, rows 3 degrees apart. Root = bottom-left note (▲▼ octave, SHIFT+▲▼ semitone) | Pick the scale: Chromatic, Major, Minor, Dorian, Mixolydian, Harmonic minor, Major/Minor pentatonic |
| DRUMS | 4×4 quadrants from C3 (FPC / Slicex / drum plugins) to the selected channel | – |
| CHANNELS | Each pad triggers a channel-rack channel. SHIFT+pad selects it | – |
| SONG | One pad per bar of the song; press to jump there (switches FL to song mode). The current bar lights and the page follows playback. With playlist markers, marker bars show the marker name and each section takes the marker's colour; without markers, 4-bar phrases alternate shades | – |

### Sends

The mixer page's send knobs A–D control routing from each strip to up to four "send" inserts.
By default the script uses the first four inserts whose names contain *send, reverb, verb,
delay, bus* or *fx*. Set `SEND_TRACKS` in the script to choose them yourself, e.g. `(20, 21)`.
Turning a send on a strip that isn't routed yet creates the route.

## Known limits

- The mixer strips and knobs are FL **mixer inserts**; the PERFORM pad rows are **playlist
  tracks**. FL doesn't tie these together the way Ableton tracks are.
- SONG mode: FL's script API can name markers but not say where they are, so the script maps
  marker positions when you enter SONG mode (only while stopped), briefly moving the playhead and
  putting it back. Bars always work, markers or not.
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
