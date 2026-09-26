# name=Akai Force (Live Control)
"""
Akai Force -> FL Studio controller script.

Speaks the Force's "Live Control" protocol (the one it uses with Ableton) on
the "Akai Network - DAW Control" port, so the Force's own touchscreen, pads,
knob OLEDs and buttons all drive FL Studio.

Setup (Options > MIDI Settings):
  Input  "Akai Network - DAW Control": enable, Controller type = this script, any free Port (e.g. 1)
  Output "Akai Network - DAW Control": the same Port number
Then put the Force in Live Control mode.

Pad modes (LAUNCH button cycles, SHIFT+LAUNCH goes back):
  PERFORM   FL Performance Mode clips, laid out like the playlist
            (rows = playlist tracks, columns = blocks)
  PATTERNS  64 pads = patterns; press to select
  STEPS     step sequencer: rows = channels, columns = steps of the current pattern
  KEYS      keyboard -> selected channel; right-hand buttons pick a scale
  DRUMS     4x4 quadrants from C3 (FPC / Slicex / drum plugins) -> selected channel
  CHANNELS  each pad triggers a channel-rack channel (sample kits)
  PLUGIN    8 vertical faders for the current plugin's parameters; presets on up/down
  SONG      one pad per bar of the song; press to jump there
"""

import math
import random
import time

import arrangement
import channels
import device
import general
import midi
import mixer
import patterns
import playlist
import plugins
import transport
import ui

import force_protocol as fp

VERSION = "1.1.0"

# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------
PING_INTERVAL = 1.0          # seconds between keep-alive pings
PONG_TIMEOUT = 8.0           # no pong for this long -> Force considered gone (FL stalls while loading)
REFRESH_INTERVAL = 0.04      # max rate of full state refreshes (s)
VOLUME_STEP = 0.004          # mixer volume per knob tick (0..1 range)
PARAM_STEP = 0.008           # plugin parameter per knob tick
FINE = 0.2                   # SHIFT multiplier for knobs
PAD_AFTERTOUCH = False       # pass pad pressure on as poly aftertouch in note modes
MAX_PARAM_SCAN = 4096        # plugin params scanned for names (VSTs report thousands)
PARAM_SKIP = ("MIDI CC", "MIDI Channel")   # FL's generic per-channel MIDI slots on VSTs: never on the knobs
PARAM_FIRST = ("macro", "master")          # parameters whose names start like this come first
SLOT_ON = 1 << 30            # FL's event value for an enabled mixer effect slot (0 = bypassed)
FLASH_TIME = 1.2             # seconds the mode name stays on the knob OLEDs
HEAL_INTERVAL = 0.25         # resend one pad row this often, in case network MIDI dropped something
SEND_TRACKS = ()             # mixer inserts for the send knobs A-D, e.g. (20, 21); empty = auto-detect
SEND_KEYWORDS = ("send", "reverb", "verb", "delay", "bus", "fx")   # auto-detect: insert names containing these
FX_SLOTS = 10                # mixer effect slots per insert
MIN_BRIGHTNESS = 200         # FL colours darker than this (0-255) are brightened so pads don't look off
STEPS_HIDE_PIANO_ROLL = True # STEPS: don't show piano-roll channels' note starts as steps (FL doesn't either)

MODES = ("PERFORM", "PATTERNS", "STEPS", "KEYS", "DRUMS", "CHANNELS", "PLUGIN", "SONG")
SCALES = (                   # KEYS mode: right-hand buttons 1-8 pick one of these
    ("Chromatic", ()),
    ("Major", (0, 2, 4, 5, 7, 9, 11)),
    ("Minor", (0, 2, 3, 5, 7, 8, 10)),
    ("Dorian", (0, 2, 3, 5, 7, 9, 10)),
    ("Mixolydian", (0, 2, 4, 5, 7, 9, 10)),
    ("Harm minor", (0, 2, 3, 5, 7, 8, 11)),
    ("Maj pent", (0, 2, 4, 7, 9)),
    ("Min pent", (0, 3, 5, 7, 10)),
)
STEP_PARAMS = (              # STEPS: hold a step, knobs 1-7 edit these (name, FL step param, min, max)
    ("Pitch", 0, 0, 127),
    ("Vel", 1, 0, 127),
    ("Release", 2, 0, 127),
    ("Fine", 3, 0, 240),
    ("Pan", 4, 0, 128),
    ("Mod X", 5, 0, 255),
    ("Mod Y", 6, 0, 255),
)
ASSIGN_MODES = {100: "mute", 101: "solo", 102: "arm", 103: "stop"}   # button note -> row function

# palette values used for UI colouring
C_WHITE = fp.palette(13)
C_LIGHT = fp.palette(27)
C_MID = fp.palette(41)
C_DARK = fp.palette(69)
KEY_ROOT = fp.palette(22)    # KEYS: root notes when the channel has no real colour (deep blue)
KEY_WHITE = fp.palette(55)   # KEYS: natural / in-scale notes (dim grey)
KEY_BLACK = fp.palette(69)   # KEYS: sharps (darkest grey)


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def note_name(n):
    """FL Studio naming: note 60 = C5."""
    return ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")[n % 12] + str(n // 12)


def rgb_of(color):
    color &= 0xFFFFFF
    return (color >> 16) & 0xFF, (color >> 8) & 0xFF, color & 0xFF


class Force:
    def __init__(self):
        self.connected = False
        self.last_ping = 0.0
        self.last_pong = 0.0
        self.sent = {}            # (status, d1) -> d2    output cache
        self.texts = {}           # slot -> str           output cache
        self.palette_cache = {}
        self.dirty = True
        self.last_refresh = 0.0
        self.mode = 0
        self.track_ofs = 0        # first visible column (0-based)
        self.scene_ofs = 0        # perform: first block (leftmost column)
        self.perf_track_ofs = 0   # perform: first playlist track (top row), 0-based
        self.pattern_ofs = 0      # patterns: first pattern - 1
        self.key_base = 36        # keys: note of bottom-left pad
        self.drum_base = 36       # drums: note of bottom-left pad
        self.chan_ofs = 0         # channels: first channel
        self.assign = "mute"
        self.shift = False
        self.held = {}            # (t, s) -> action data for release
        self.touch_mixer = [False] * 8
        self.touch_device = [False] * 8
        self.flash_text = ""
        self.flash_until = 0.0
        self.param_bank = 0
        self.param_cache_key = None
        self.param_list = []
        self.meters = [[0, 0] for _ in range(8)]
        self.heal_row = 0
        self.last_heal = 0.0
        self.step_ofs = 0         # steps: first visible step
        self.step_chan_ofs = 0    # steps: first visible channel (top row)
        self.scale = 0            # keys: index into SCALES
        self.aftertouch = PAD_AFTERTOUCH
        self.fx_mode = False      # device page follows the selected insert's effect chain
        self.fx_slot = 0
        self.markers = []         # song: [(name, ticks or None)]
        self.song_ofs = 0
        self.sends = []
        self.sends_time = 0.0
        self.held_step = None     # steps: [channel, step, edited] while a step pad is held
        self.pr_cache = {}        # (pattern, channel) -> (is_piano_roll, time)
        self.pv = None            # plugin mode: (target, params, values, names, value texts, colour)
        self.rand_snapshot = None  # plugin mode: values before the last randomize, for UNDO
        self.preset_text = ""

    # ------------------------------------------------------------------ output
    def _out(self, status, d1, d2, force=False):
        key = (status, d1)
        if not force and self.sent.get(key) == d2:
            return
        if not device.isAssigned():       # FL raises RuntimeError if no output port is linked
            return
        self.sent[key] = d2
        device.midiOutMsg(status | (d1 << 8) | (d2 << 16))

    def note(self, ch, n, v, force=False):
        self._out(0x90 | ch, n, clamp(int(v), 0, 127), force)

    def cc(self, ch, n, v, force=False):
        self._out(0xB0 | ch, n, clamp(int(v), 0, 127), force)

    def text(self, slot, s):
        s = str(s)[:fp.TEXT_MAX_CHARS]
        if self.texts.get(slot) == s or not device.isAssigned():
            return
        self.texts[slot] = s
        device.midiOutSysex(bytes(fp.sysex_text(slot, s)))

    def color_of(self, fl_color):
        """FL colour -> Force palette value. Dark colours (FL's default channel grey is
        0x5C656A) are brightened first; on the pads they would otherwise look unlit."""
        c = fl_color & 0xFFFFFF
        v = self.palette_cache.get(c)
        if v is None:
            r, g, b = rgb_of(c)
            m = max(r, g, b)
            if m == 0:
                v = C_MID
            else:
                if m < MIN_BRIGHTNESS:
                    k = MIN_BRIGHTNESS / m
                    r, g, b = min(255, int(r * k)), min(255, int(g * k)), min(255, int(b * k))
                v = fp.palette(fp.nearest_palette_index(r, g, b))
            self.palette_cache[c] = v
        return v

    def hint(self, msg):
        ui.setHintMsg("Force: " + msg)

    def flash(self, msg):
        self.flash_text = msg
        self.flash_until = time.time() + FLASH_TIME
        self.hint(msg)
        self.dirty = True

    # --------------------------------------------------------------- lifecycle
    def on_init(self):
        # FL re-runs OnInit on the same instance whenever MIDI settings change,
        # so start from a clean slate: handshake again and resend everything.
        self.connected = False
        self.sent.clear()
        self.texts.clear()
        self.held.clear()
        self.dirty = True
        device.setHasMeters()
        print("Akai Force script v%s loaded - pinging the Force..." % VERSION)
        if not device.isAssigned():
            self.hint("set the DAW Control OUTPUT port to the same number as the input")
            print("Output port not linked: give the DAW Control OUTPUT the same Port number as the input")
        self.ping()

    def on_deinit(self):
        if not self.connected or not device.isAssigned():
            return
        for t in range(8):
            self.note(0, fp.TUI_TRACK_TYPE + t, fp.TRACK_NONE)
            self.text(fp.TXT_TRACK_NAME(t), "")
            self.text(fp.TXT_OLED_MIXER(t), "")
            for s in range(8):
                self.cc(fp.CH_PHYS, fp.pad_color_cc(t, s), 0)
                self.note(fp.CH_PHYS, fp.pad_note(t, s), 0)

    def ping(self):
        self.last_ping = time.time()
        if device.isAssigned():
            device.midiOutSysex(bytes(fp.sysex_ping()))

    def on_idle(self):
        now = time.time()
        if now - self.last_ping >= PING_INTERVAL:
            self.ping()
            if self.connected and now - self.last_pong > PONG_TIMEOUT:
                self.connected = False
                self.hint("disconnected")
                print("Akai Force disconnected (no reply to pings)")
        if not self.connected:
            return
        if self.flash_until and now > self.flash_until:
            self.flash_until = 0.0
            self.dirty = True
        if MODES[self.mode] in ("PERFORM", "STEPS", "SONG") and transport.isPlaying() and now - self.last_refresh > 0.1:
            self.dirty = True
        try:
            if MODES[self.mode] == "SONG" and transport.isPlaying():
                bar = self.current_bar()
                if not self.song_ofs <= bar < self.song_ofs + 64:
                    self.song_ofs = bar - bar % 8      # page follows playback
                    self.dirty = True
            if self.dirty and now - self.last_refresh >= REFRESH_INTERVAL:
                self.dirty = False
                self.last_refresh = now
                self.refresh()
            elif now - self.last_heal >= HEAL_INTERVAL:
                self.last_heal = now
                self.heal()
        except RuntimeError:
            # FL refuses some calls at certain moments ("Operation unsafe at current
            # time"), e.g. while a project loads. Try again shortly.
            self.dirty = True
            self.last_refresh = now + 0.5

    def on_sysex(self, event):
        event.handled = True
        if not event.sysex:
            return
        parsed = fp.parse_sysex(list(event.sysex))
        if parsed[0] == "pong" and parsed[1] == fp.FORCE:
            self.last_pong = time.time()
            if not self.connected and device.isAssigned():
                self.connected = True
                print("Akai Force connected")
                self.sent.clear()
                self.texts.clear()
                self.dirty = True
                self.flash(MODES[self.mode])
        elif parsed[0] == "text" and parsed[1] == fp.TXT_TEMPO:
            try:
                bpm = clamp(float(parsed[2]), 10.0, 522.0)
                general.processRECEvent(midi.REC_Tempo, int(bpm * 1000), midi.REC_Control | midi.REC_UpdateControl)
            except ValueError:
                pass
            self.texts.pop(fp.TXT_TEMPO, None)
            self.dirty = True

    def on_refresh(self, flags):
        self.dirty = True

    # ----------------------------------------------------------------- helpers
    def last_insert(self):
        return mixer.trackCount() - 2      # excludes master (0) and "current" (last)

    def insert(self, t):
        """Mixer insert for column t, or None."""
        i = self.track_ofs + 1 + t
        return i if i <= self.last_insert() else None

    def max_track_ofs(self):
        return max(0, self.last_insert() - 8)

    def perf_track(self, s):
        """Playlist track (1-based) on pad row s in PERFORM mode, or None."""
        tr = self.perf_track_ofs + 1 + s
        return tr if tr <= playlist.trackCount() else None

    def send_tracks(self):
        """Mixer inserts the Force's send knobs A-D control (cached for 2 s)."""
        if not hasattr(mixer, "getRouteToLevel"):     # older FL API: no send levels
            return []
        now = time.time()
        if now - self.sends_time > 2.0:
            self.sends_time = now
            last = self.last_insert()
            if SEND_TRACKS:
                self.sends = [i for i in SEND_TRACKS if 1 <= i <= last][:4]
            else:
                found = []
                for i in range(1, last + 1):
                    name = mixer.getTrackName(i).lower()
                    if not name.startswith("insert") and any(k in name for k in SEND_KEYWORDS):
                        found.append(i)
                        if len(found) == 4:
                            break
                self.sends = found
        return self.sends

    def pattern_steps(self):
        # getPatternLength's docs say "beats", but FL 2026 returns steps
        # (a 128-step pattern reports 128 and its last step is index 127).
        try:
            n = int(patterns.getPatternLength(patterns.patternNumber()))
        except (AttributeError, TypeError):
            n = 0
        return n if n > 0 else 16

    def perf_on(self):
        try:
            return bool(playlist.getPerformanceModeState())
        except AttributeError:
            return True

    def is_piano_roll(self, c):
        """FL's channel rack shows a piano-roll preview instead of steps for channels
        holding piano-roll notes, but getGridBit still reports their note starts. The API
        can't say which is which, so: a generator plugin whose notes use more than one
        pitch is treated as piano roll (drum samples and single-pitch steps stay steps)."""
        if not STEPS_HIDE_PIANO_ROLL:
            return False
        key = (patterns.patternNumber(), c)
        now = time.time()
        hit = self.pr_cache.get(key)
        if hit and now - hit[1] < 2.0:
            return hit[0]
        result = False
        try:
            if channels.getChannelType(c) == midi.CT_GenPlug:
                pitches = set()
                for step in range(self.pattern_steps()):
                    if channels.getGridBit(c, step):
                        pitches.add(channels.getStepParam(0, midi.pPitch, c, step, 1))
                        if len(pitches) > 1:
                            result = True
                            break
        except (AttributeError, TypeError):
            pass
        self.pr_cache[key] = (result, now)
        return result

    def step_param_text(self, i):
        if not self.held_step or i >= len(STEP_PARAMS):
            return ""
        name, p = STEP_PARAMS[i][:2]
        v = channels.getStepParam(0, p, self.held_step[0], self.held_step[1], 1)
        return "%s %s" % (name, note_name(v) if p == midi.pPitch else v)

    def edit_step_param(self, i, delta):
        if i >= len(STEP_PARAMS):
            return
        name, p, lo, hi = STEP_PARAMS[i]
        c, step = self.held_step[0], self.held_step[1]
        v = clamp(channels.getStepParam(0, p, c, step, 1) + delta * (2 if hi > 127 else 1), lo, hi)
        channels.setStepParameterByIndex(channels.getChannelIndex(c), patterns.patternNumber(), step, p, v, True)
        self.held_step[2] = True

    def song_bars(self):
        return max(1, int(transport.getSongLength(midi.SONGLENGTH_BARS)))

    def current_bar(self):
        return int(self.song_ticks() // max(1, general.getRecPPB()))

    def marker_bars(self):
        """{bar: (marker index, name)} for markers whose position is known."""
        ppb = max(1, general.getRecPPB())
        return {int(t // ppb): (i, n) for i, (n, t) in enumerate(self.markers) if t is not None}

    def jump_bar(self, bar):
        transport.setSongPos(bar * general.getRecPPB(), midi.SONGLENGTH_ABSTICKS)
        name = self.marker_bars().get(bar, (0, ""))[1]
        self.hint("bar %d%s" % (bar + 1, (" - " + name) if name else ""))

    def play_step(self):
        return mixer.getSongStepPos() % self.pattern_steps()

    def song_ticks(self):
        return transport.getSongPos(midi.SONGLENGTH_ABSTICKS)

    def column_playing(self, t):
        block = self.scene_ofs + t
        for s in range(8):
            tr = self.perf_track(s)
            if tr is not None and playlist.getLiveBlockStatus(tr, block) & 4:
                return True
        return False

    # ------------------------------------------------------------ full refresh
    def refresh(self):
        self.refresh_tracks()
        self.refresh_grid()
        self.refresh_transport()
        self.refresh_device()

    def refresh_tracks(self):
        flashing = self.flash_until > 0.0
        selected = mixer.trackNumber()
        sends = self.send_tracks()
        self.cc(fp.NUM_SENDS_CH, fp.NUM_SENDS_CC, len(sends))
        for t in range(8):
            i = self.insert(t)
            ch = t + 1
            if i is None:
                self.note(0, fp.TUI_TRACK_TYPE + t, fp.TRACK_NONE)
                self.text(fp.TXT_TRACK_NAME(t), "")
                self.text(fp.TXT_OLED_MIXER(t), self.flash_text if flashing else "")
                self.note(fp.CH_KNOBS, fp.OLED_STYLE_MIXER + t, fp.OLED_OFF)
                self.cc(0, fp.TUI_TRACK_COLOR_CC + t, 0)
                self.cc(fp.CH_PHYS, fp.PHYS_TRACK_SELECT_COLOR + t, 0)
                self.cc(fp.CH_PHYS, fp.PHYS_TRACK_ASSIGN_COLOR + t, 0)
                continue
            name = mixer.getTrackName(i)
            color = self.color_of(mixer.getTrackColor(i))
            vol = mixer.getTrackVolume(i)
            pan = mixer.getTrackPan(i)
            vol_txt = self.db_text(i)
            self.note(0, fp.TUI_TRACK_TYPE + t, fp.TRACK_AUDIO)
            self.text(fp.TXT_TRACK_NAME(t), name)
            self.cc(0, fp.TUI_TRACK_COLOR_CC + t, color)
            self.cc(fp.CH_PHYS, fp.PHYS_TRACK_SELECT_COLOR + t, fp.COLOR_ON if i == selected else color)
            # strip
            self.cc(ch, fp.STRIP_VOLUME_CC, round(vol * 127))
            self.cc(ch, fp.STRIP_PAN_CC, round(pan * 63.5 + 63.5))
            self.text(fp.TXT_VOLUME(t), vol_txt)
            self.text(fp.TXT_PAN(t), self.pan_text(pan))
            for k, dest in enumerate(sends):
                routed = dest != i and mixer.getRouteSendActive(i, dest)
                level = mixer.getRouteToLevel(i, dest) if routed else 0.0
                self.cc(ch, fp.STRIP_SEND_CC + k, round(level * 127))
                self.text(fp.TXT_SEND(t, k), ("%d%%" % round(level * 125)) if routed else "off")
            muted, solo, armed = mixer.isTrackMuted(i), mixer.isTrackSolo(i), mixer.isTrackArmed(i)
            self.note(ch, fp.STRIP_MUTE_NOTE, fp.COLOR_1 if muted else 0)
            self.note(ch, fp.STRIP_SOLO_NOTE, fp.COLOR_2 if solo else 0)
            self.note(ch, fp.STRIP_ARM_NOTE, fp.COLOR_3 if armed else 0)
            # knob OLED: style + value (draws the bar) + text (name, or dB while touched)
            self.note(fp.CH_KNOBS, fp.OLED_STYLE_MIXER + t, fp.OLED_UNIPOLAR)
            self.cc(fp.CH_KNOBS, fp.KNOB_MIXER + t, round(vol * 127))
            if self.held_step:
                oled = self.step_param_text(t)
            elif self.touch_mixer[t]:
                oled = vol_txt
            else:
                oled = self.flash_text if flashing else name
            self.text(fp.TXT_OLED_MIXER(t), oled)
            # assign row (below pads)
            if self.assign == "mute":
                lit = fp.COLOR_1 if muted else 0
            elif self.assign == "solo":
                lit = fp.COLOR_2 if solo else 0
            elif self.assign == "arm":
                lit = fp.COLOR_3 if armed else 0
            else:
                # CLIP STOP row: in PERFORM each button launches the block column above it
                lit = 0
                if MODES[self.mode] == "PERFORM":
                    lit = fp.COLOR_4 if self.column_playing(t) else C_DARK
            if MODES[self.mode] == "STEPS" and transport.isPlaying():
                lit = fp.COLOR_ON if self.step_ofs + t == self.play_step() else 0   # playhead
            self.cc(fp.CH_PHYS, fp.PHYS_TRACK_ASSIGN_COLOR + t, lit)
        for note_, name in ASSIGN_MODES.items():
            self.note(fp.CH_PHYS, note_, fp.COLOR_ON if self.assign == name else 0)

    def db_text(self, i):
        try:
            db = mixer.getTrackVolume(i, 1)
        except TypeError:
            return "%d%%" % round(mixer.getTrackVolume(i) * 125)
        if db is None or db <= -100 or math.isinf(db):
            return "-inf dB"
        return "%.1f dB" % db

    @staticmethod
    def pan_text(pan):
        p = round(pan * 100)
        return "C" if p == 0 else ("L%d" % -p if p < 0 else "R%d" % p)

    # ------------------------------------------------------------------- grid
    def cell(self, t, s):
        """Return (color, state, name) for grid cell (column t, row s from top)."""
        mode = MODES[self.mode]
        if mode == "PERFORM":
            tr = self.perf_track(s)
            if tr is None or not self.perf_on():
                return 0, fp.CLIP_EMPTY, ""
            block = self.scene_ofs + t
            st = playlist.getLiveBlockStatus(tr, block)
            if not st & 1:
                return 0, fp.CLIP_EMPTY_WITH_STOP, ""
            state = fp.CLIP_PLAYING if st & 4 else fp.CLIP_TRIGGERED if st & 2 else fp.CLIP_STOPPED
            return self.color_of(playlist.getLiveBlockColor(tr, block)), state, playlist.getTrackName(tr)
        if mode == "PATTERNS":
            p = self.pattern_ofs + s * 8 + t + 1
            if p > patterns.patternMax():
                return 0, fp.CLIP_EMPTY, ""
            if p > patterns.patternCount():
                return 0, fp.CLIP_EMPTY_WITH_STOP, ""
            state = fp.CLIP_PLAYING if p == patterns.patternNumber() else fp.CLIP_STOPPED
            return self.color_of(patterns.getPatternColor(p)), state, patterns.getPatternName(p)
        if mode == "STEPS":
            # Pads mirror the channel rack exactly: lit = step on, dark = off.
            # (The playhead runs along the button row under the pads.)
            c, step = self.step_chan_ofs + s, self.step_ofs + t
            if c >= channels.channelCount() or step >= self.pattern_steps() or self.is_piano_roll(c):
                return 0, fp.CLIP_EMPTY, ""
            if not channels.getGridBit(c, step):
                return 0, fp.CLIP_EMPTY, ""
            playing = transport.isPlaying() and step == self.play_step()
            return (self.color_of(channels.getChannelColor(c)), fp.CLIP_PLAYING if playing else fp.CLIP_STOPPED,
                    str(step + 1))
        if mode == "SONG":
            # One pad per bar. Marker sections share the marker's colour; without
            # markers, 4-bar phrases alternate shades.
            bar = self.song_ofs + s * 8 + t
            if bar >= self.song_bars():
                return 0, fp.CLIP_EMPTY, ""
            state = fp.CLIP_PLAYING if bar == self.current_bar() else fp.CLIP_STOPPED
            marks = self.marker_bars()
            starts = [b for b in marks if b <= bar]
            if starts:
                idx, name = marks[max(starts)]
                color = fp.palette((idx * 7 + 3) % 70)
                return color, state, name if bar in marks else str(bar + 1)
            return (C_LIGHT if (bar // 4) % 2 == 0 else C_MID), state, str(bar + 1)
        if mode in ("KEYS", "DRUMS"):
            n = self.pad_to_note(t, s)
            if n is None:
                return 0, fp.CLIP_EMPTY, ""
            state = fp.CLIP_PLAYING if n in self.held_notes() else fp.CLIP_STOPPED
            degree = (n - self.key_base) % 12
            if mode == "DRUMS":
                quad = (1 if t >= 4 else 0) * 2 + (1 if s < 4 else 0)
                color = fp.palette((quad * 17 + 5) % 70)
            elif degree == 0:
                color = self.root_color()
            elif SCALES[self.scale][1]:
                color = KEY_WHITE              # scale layouts only contain in-scale notes
            else:
                color = KEY_WHITE if degree in (2, 4, 5, 7, 9, 11) else KEY_BLACK
            return color, state, note_name(n)
        if mode == "PLUGIN":
            # 8 vertical faders: column = parameter of the current bank, height = value
            pv = self.pv
            if not pv or t >= len(pv[1]):
                return 0, fp.CLIP_EMPTY, ""
            r = 7 - s
            lit = r == 0 or pv[2][t] >= r / 7.0 - 0.02
            name = pv[3][t] if s == 7 else (pv[4][t] if s == 0 else "")
            return (pv[5] if lit else 0), (fp.CLIP_STOPPED if lit else fp.CLIP_EMPTY), name
        # CHANNELS
        c = self.chan_ofs + s * 8 + t
        if c >= channels.channelCount():
            return 0, fp.CLIP_EMPTY, ""
        state = fp.CLIP_PLAYING if (t, s) in self.held else fp.CLIP_STOPPED
        if c == channels.selectedChannel():
            state = fp.CLIP_TRIGGERED if state != fp.CLIP_PLAYING else state
        return self.color_of(channels.getChannelColor(c)), state, channels.getChannelName(c)

    def send_cell(self, t, s, force=False):
        """State first, then colour -- the order Ableton uses. The Force can drop a
        colour sent to a slot it still thinks is empty, so a state change always
        re-sends the colour too."""
        color, state, name = self.cell(t, s)
        changed = force or self.sent.get((0x90 | fp.CH_PHYS, fp.pad_note(t, s))) != state
        self.note(fp.CH_PHYS, fp.pad_note(t, s), state, force)
        self.note(0, fp.tui_clip_note(t, s), state, force)
        self.cc(fp.CH_PHYS, fp.pad_color_cc(t, s), color, changed)
        self.cc(0, fp.tui_clip_color_cc(t, s), color, changed)
        self.text(fp.TXT_CLIP_NAME(t, s), name)

    def heal(self):
        """Re-send one pad row (and its row colour) unconditionally; the whole grid
        is refreshed every 8 * HEAL_INTERVAL seconds."""
        s = self.heal_row
        self.heal_row = (s + 1) % 8
        for t in range(8):
            self.send_cell(t, s, force=True)
        for key in ((0xB0, fp.TUI_SCENE_COLOR_CC + s), (0x90 | fp.CH_PHYS, fp.PHYS_SCENE_LAUNCH + s)):
            if key in self.sent:
                self._out(key[0], key[1], self.sent[key], force=True)

    def root_color(self):
        """Selected channel's colour for root notes, unless it's a grey (FL's default
        for uncoloured channels), which would wash out to white on the pads."""
        ch = channels.selectedChannel(True)
        if ch < 0:
            return KEY_ROOT
        r, g, b = rgb_of(channels.getChannelColor(ch))
        return self.color_of(channels.getChannelColor(ch)) if max(r, g, b) - min(r, g, b) > 40 else KEY_ROOT

    def held_notes(self):
        return {v for v in self.held.values() if isinstance(v, int)}

    def pad_to_note(self, t, s):
        r = 7 - s                          # row from the bottom
        if MODES[self.mode] == "KEYS":
            scale = SCALES[self.scale][1]
            if not scale:
                n = self.key_base + r * 5 + t          # chromatic: rows a 4th apart
            else:
                degree = r * 3 + t                     # in key: rows 3 scale degrees apart
                n = self.key_base + 12 * (degree // len(scale)) + scale[degree % len(scale)]
        else:
            quad = (1 if t >= 4 else 0) * 2 + (1 if r >= 4 else 0)
            n = self.drum_base + quad * 16 + (r % 4) * 4 + (t % 4)
        return n if 0 <= n <= 127 else None

    def refresh_grid(self):
        mode = MODES[self.mode]
        if mode == "PLUGIN":
            self.pv = self.plugin_view()
        for t in range(8):
            for s in range(8):
                self.send_cell(t, s)
        for s in range(8):
            led = 0                          # right-hand button LED
            if mode == "PERFORM" and not self.perf_on():
                label, col = ("Turn on Perf Mode" if s == 0 else ""), 0
            elif mode == "PERFORM":
                tr = self.perf_track(s)
                if tr is None:
                    label, col = "", 0
                else:
                    label, col = playlist.getTrackName(tr), self.color_of(playlist.getTrackColor(tr))
                    led = fp.COLOR_1 if playlist.isTrackMuted(tr) else col
            elif mode == "PATTERNS":
                first = self.pattern_ofs + s * 8 + 1
                label, col = "Pat %d-%d" % (first, first + 7), C_DARK
            elif mode == "STEPS":
                c = self.step_chan_ofs + s
                if c < channels.channelCount():
                    label, col = channels.getChannelName(c), self.color_of(channels.getChannelColor(c))
                    if self.is_piano_roll(c):
                        label += " (piano roll)"
                    led = fp.COLOR_ON if c == channels.selectedChannel() else col
                else:
                    label, col = "", 0
            elif mode == "KEYS":
                label = SCALES[s][0]
                col = C_WHITE if s == self.scale else C_DARK
                led = fp.COLOR_ON if s == self.scale else C_DARK
            elif mode == "DRUMS":
                n = self.pad_to_note(0, s)
                label, col = (note_name(n) if n is not None else ""), C_DARK
            elif mode == "SONG":
                first = self.song_ofs + s * 8 + 1
                label, col = ("Bars %d-%d" % (first, first + 7)) if first <= self.song_bars() else "", C_DARK
            elif mode == "PLUGIN":
                bank = (self.param_bank // 8) * 8 + s
                nbanks = (len(self.param_list) + 7) // 8 if self.pv else 0
                if bank < nbanks:
                    label = "Bank %d" % (bank + 1)
                    col = C_WHITE if bank == self.param_bank else C_DARK
                    led = fp.COLOR_ON if bank == self.param_bank else C_DARK
                else:
                    label, col = ("No plugin selected" if s == 0 and not self.pv else ""), 0
            else:
                first = self.chan_ofs + s * 8 + 1
                label, col = "Ch %d-%d" % (first, first + 7), C_DARK
            self.text(fp.TXT_SCENE_NAME(s), label)
            self.cc(0, fp.TUI_SCENE_COLOR_CC + s, col)
            self.note(fp.CH_PHYS, fp.PHYS_SCENE_LAUNCH + s, led)
        self.note(fp.CH_GLOBAL, fp.GLOBAL_BUTTONS["launch_mode"], 0)   # keep the Force on its clip-grid layout

    # -------------------------------------------------------------- transport
    def refresh_transport(self):
        b = fp.PHYS_BUTTONS
        playing = transport.isPlaying()
        self.note(fp.CH_PHYS, b["play"], fp.COLOR_ON if playing else 0)
        self.note(fp.CH_PHYS, b["stop"], 0 if playing else fp.COLOR_ON)
        self.note(fp.CH_PHYS, b["rec"], fp.COLOR_ON if transport.isRecording() else 0)
        self.note(fp.CH_PHYS, b["tap_tempo"], fp.COLOR_1)
        self.note(fp.CH_PHYS, b["undo"], fp.COLOR_ON)
        self.note(fp.CH_PHYS, b["launch"], fp.COLOR_ON)
        self.note(fp.CH_PHYS, b["copy"], fp.COLOR_1)
        self.note(fp.CH_PHYS, b["delete"], fp.COLOR_1)
        self.note(fp.CH_PHYS, b["select"], fp.COLOR_ON if self.aftertouch else 0)
        self.note(fp.CH_PHYS, b["shift"], fp.COLOR_ON if self.shift else 0)
        for k in ("up", "down", "left", "right"):
            self.note(fp.CH_PHYS, b[k], fp.COLOR_1)
        self.note(fp.CH_GLOBAL, fp.GLOBAL_BUTTONS["metronome"], 127 if ui.isMetronomeEnabled() else 0)
        self.note(fp.CH_GLOBAL, fp.GLOBAL_BUTTONS["loop"], 127 if transport.getLoopMode() == 1 else 0)
        tempo = mixer.getCurrentTempo()
        if tempo > 1000:
            tempo /= 1000.0
        self.text(fp.TXT_TEMPO, "%.2f" % tempo)
        self.text(fp.TXT_SONG_POSITION, transport.getSongPosHint())

    # ----------------------------------------------------------------- device
    def device_target(self):
        """(index, slot) of the plugin the device page controls, or None."""
        try:
            if ui.getFocused(midi.widPluginEffect):
                r = mixer.getActiveEffectIndex()
                if r and plugins.isValid(r[0], r[1]):
                    return r[0], r[1]
        except (AttributeError, TypeError):
            pass
        if self.fx_mode:
            tr = mixer.trackNumber()
            return (tr, self.fx_slot) if plugins.isValid(tr, self.fx_slot) else None
        ch = channels.selectedChannel(True)
        if ch >= 0 and plugins.isValid(ch):
            return ch, -1
        return None

    def params(self, target):
        name = plugins.getPluginName(target[0], target[1])
        key = (target, name)
        if key != self.param_cache_key:
            self.param_cache_key = key
            self.param_bank = 0
            self.preset_text = ""
            count = min(plugins.getParamCount(target[0], target[1]), MAX_PARAM_SCAN)
            names = {}
            for p in range(count):
                n = plugins.getParamName(p, target[0], target[1]).strip()
                if n and not n.startswith(PARAM_SKIP):
                    names[p] = n
            first = [p for p, n in names.items() if n.lower().startswith(PARAM_FIRST)]
            self.param_list = first + [p for p in names if p not in set(first)]
        return name

    def bank_params(self):
        return self.param_list[self.param_bank * 8:self.param_bank * 8 + 8]

    def refresh_device(self):
        flashing = self.flash_until > 0.0
        target = self.device_target()
        if target is None:
            self.text(fp.TXT_DEVICE_NAME, ("%s: empty FX slot" % mixer.getTrackName(mixer.trackNumber()))
                      if self.fx_mode else "No plugin")
            self.text(fp.TXT_DEVICE_BANK, "")
            bank = []
        else:
            name = self.params(target)
            nbanks = max(1, (len(self.param_list) + 7) // 8)
            self.param_bank = clamp(self.param_bank, 0, nbanks - 1)
            self.text(fp.TXT_DEVICE_NAME, ("FX%d %s" % (target[1] + 1, name)) if target[1] >= 0 else name)
            preset = self.preset_name(target)
            self.text(fp.TXT_DEVICE_BANK, "Bank %d/%d%s" % (self.param_bank + 1, nbanks, ("  " + preset) if preset else ""))
            bank = self.bank_params()
        if self.fx_mode:
            self.cc(fp.CH_DEVICE, fp.DEVICE_COUNT_CC, FX_SLOTS)
            self.cc(fp.CH_DEVICE, fp.DEVICE_INDEX_CC, self.fx_slot)
        else:
            self.cc(fp.CH_DEVICE, fp.DEVICE_COUNT_CC, min(channels.channelCount(), 127))
            self.cc(fp.CH_DEVICE, fp.DEVICE_INDEX_CC, clamp(channels.selectedChannel(), 0, 127))
        self.note(fp.CH_DEVICE, fp.DEVICE_BUTTONS["device_on"], 127 if target and self.target_enabled(target) else 0)
        for i in range(8):
            if i < len(bank):
                p = bank[i]
                pname = plugins.getParamName(p, target[0], target[1])
                val = plugins.getParamValue(p, target[0], target[1])
                vstr = plugins.getParamValueString(p, target[0], target[1])
                self.text(fp.TXT_PARAM_NAME(i), pname)
                self.text(fp.TXT_PARAM_VALUE(i), vstr)
                self.cc(fp.CH_DEVICE, fp.DEVICE_PARAM_CC + i, round(val * 127))
                self.note(fp.CH_DEVICE, fp.DEVICE_PARAM_ENABLE + i, 127)
                self.note(fp.CH_KNOBS, fp.OLED_STYLE_DEVICE + i, fp.OLED_UNIPOLAR)
                self.cc(fp.CH_KNOBS, fp.KNOB_DEVICE + i, round(val * 127))
                oled = vstr if self.touch_device[i] else (self.flash_text if flashing else pname)
            else:
                self.text(fp.TXT_PARAM_NAME(i), "")
                self.text(fp.TXT_PARAM_VALUE(i), "")
                self.note(fp.CH_DEVICE, fp.DEVICE_PARAM_ENABLE + i, 0)
                self.note(fp.CH_KNOBS, fp.OLED_STYLE_DEVICE + i, fp.OLED_OFF)
                oled = self.flash_text if flashing else ""
            if self.held_step:
                oled = self.step_param_text(i)
            self.text(fp.TXT_OLED_DEVICE(i), oled)

    # ------------------------------------------------------------------ input
    def on_midi(self, event):
        try:
            self._on_midi(event)
        except RuntimeError as e:
            event.handled = True          # e.g. "Operation unsafe at current time"
            self.hint("FL refused that just now (%s) - try again" % e)

    def _on_midi(self, event):
        if event.status >= 0xF0 or getattr(event, "sysex", None):
            self.on_sysex(event)          # FL routes SysEx through OnMidiMsg before OnSysEx
            return
        status = event.status
        kind, ch, d1, d2 = status & 0xF0, status & 0x0F, event.data1, event.data2
        is_on = kind == 0x90 and d2 > 0
        is_off = kind == 0x80 or (kind == 0x90 and d2 == 0)
        safe = (event.pmeFlags & midi.PME_System_Safe) != 0
        event.handled = True

        if not self.connected:
            return
        if kind in (0x80, 0x90):
            if ch == fp.CH_PHYS and fp.PHYS_PAD <= d1 < fp.PHYS_PAD + 64:
                s, t = divmod(d1 - fp.PHYS_PAD, 8)
                self.pad(event, t, s, is_on, is_off, d2, safe)
            elif ch == 0 and fp.TUI_CLIP_LAUNCH <= d1 < fp.TUI_CLIP_LAUNCH + 64:
                s, t = divmod(d1 - fp.TUI_CLIP_LAUNCH, 8)
                self.pad(event, t, s, is_on, is_off, d2, safe)
            elif ch == fp.CH_KNOBS and d1 < 16:
                touched = is_on
                if d1 < 8:
                    self.touch_mixer[d1] = touched
                else:
                    self.touch_device[d1 - 8] = touched
                self.dirty = True
            elif is_on:
                self.button(ch, d1, safe)
            elif is_off and ch == fp.CH_PHYS and d1 == fp.PHYS_BUTTONS["shift"]:
                self.shift = False
                self.dirty = True
        elif kind == 0xB0:
            self.control(ch, d1, d2)

    def pad(self, event, t, s, is_on, is_off, value, safe):
        key = (t, s)
        mode = MODES[self.mode]
        if is_on and key in self.held:
            # repeated note-on while held = pad pressure
            n = self.held[key]
            if self.aftertouch and isinstance(n, int) and mode in ("KEYS", "DRUMS"):
                event.status, event.data1, event.data2 = 0xA0, n, value
                event.handled = False
            return
        if is_on:
            self.held[key] = None          # marks the pad as down so pressure can't retrigger it
            if mode in ("KEYS", "DRUMS"):
                n = self.pad_to_note(t, s)
                if n is None:
                    return
                self.held[key] = n
                self.pass_note(event, 0x90, n, value)
            elif mode == "STEPS":
                # tap = toggle; hold + turn knobs = edit that step (like the Akai Fire)
                c, step = self.step_chan_ofs + s, self.step_ofs + t
                if c < channels.channelCount() and step < self.pattern_steps():
                    if self.shift:
                        channels.selectOneChannel(c)
                    elif self.is_piano_roll(c):
                        channels.selectOneChannel(c)
                        self.hint("%s holds piano-roll notes - edit it in the piano roll or play it in KEYS"
                                  % channels.getChannelName(c))
                    else:
                        was_on = channels.getGridBit(c, step)
                        if not was_on:
                            channels.setGridBit(c, step, True)
                        self.held[key] = ("step", c, step, was_on)
                        self.held_step = [c, step, False]
            elif mode == "SONG":
                bar = self.song_ofs + s * 8 + t
                if bar < self.song_bars():
                    self.jump_bar(bar)
            elif mode == "PLUGIN":
                pv = self.plugin_view()
                if pv and t < len(pv[1]):
                    plugins.setParamValue((7 - s) / 7.0, pv[1][t], pv[0][0], pv[0][1])
                    self.rand_snapshot = None
            elif mode == "CHANNELS":
                c = self.chan_ofs + s * 8 + t
                if c < channels.channelCount():
                    self.held[key] = ("chan", c)
                    if self.shift:
                        channels.selectOneChannel(c)
                    else:
                        channels.midiNoteOn(channels.getChannelIndex(c), 60, value)
            elif mode == "PERFORM" and not self.perf_on():
                self.flash("PERF OFF")
                self.hint("turn on Performance Mode in the playlist to launch clips")
            elif mode == "PERFORM" and safe:
                tr, block = self.perf_track(s), self.scene_ofs + t
                if tr is not None:
                    flags = midi.TLC_MuteOthers | midi.TLC_Fill
                    if self.shift:
                        flags |= midi.TLC_ColumnMode
                    playlist.triggerLiveClip(tr, block, flags)
                    self.held[key] = ("clip", tr, block, flags)
            elif mode == "PATTERNS" and safe:
                p = self.pattern_ofs + s * 8 + t + 1
                if p <= patterns.patternMax():
                    patterns.jumpToPattern(p)
                    self.held[key] = ("pattern", p)
            self.dirty = True
        elif is_off:
            h = self.held.pop(key, None)
            if isinstance(h, int):
                self.pass_note(event, 0x80, h, 0)
            elif h and h[0] == "step":
                edited = self.held_step is not None and self.held_step[2]
                if h[3] and not edited:       # tapped an active step: turn it off
                    channels.setGridBit(h[1], h[2], False)
                if self.held_step and self.held_step[:2] == [h[1], h[2]]:
                    self.held_step = None
            elif h and h[0] == "chan" and not self.shift:
                channels.midiNoteOn(channels.getChannelIndex(h[1]), 60, -127)
            elif h and h[0] == "clip" and safe:
                playlist.triggerLiveClip(h[1], h[2], h[3] | midi.TLC_Release)
            self.dirty = True

    @staticmethod
    def pass_note(event, kind, note_, velocity):
        """Let FL play/record the note on the selected channel."""
        event.status = kind
        event.data1 = note_
        event.data2 = velocity
        event.handled = False

    def button(self, ch, d1, safe):
        b = fp.PHYS_BUTTONS
        self.dirty = True
        if ch == fp.CH_PHYS:
            if d1 == b["shift"]:
                self.shift = True
            elif d1 == b["play"]:
                transport.start()
            elif d1 == b["stop"]:
                transport.stop()
            elif d1 == b["rec"]:
                transport.record()
            elif d1 == b["tap_tempo"]:
                transport.globalTransport(midi.FPT_Metronome if self.shift else midi.FPT_TapTempo, 1)
            elif d1 == b["undo"]:
                if self.shift:
                    general.undoDown()
                elif not self.undo_randomize():
                    general.undoUp()
            elif d1 == b["launch"]:
                self.set_mode(self.mode + (-1 if self.shift else 1))
            elif d1 == b["stop_all"]:
                self.stop_all(safe)
            elif d1 == b["master"]:
                mixer.setTrackNumber(0, midi.curfxScrollToMakeVisible)
            elif d1 == b["copy"]:
                if hasattr(patterns, "clonePattern"):
                    patterns.clonePattern()
                    self.hint("pattern cloned")
                else:
                    self.hint("this FL version can't clone patterns from a script")
            elif d1 == b["delete"]:
                self.delete()
            elif d1 == b["select"] and self.shift:
                self.aftertouch = not self.aftertouch
                self.flash("AT ON" if self.aftertouch else "AT OFF")
            elif d1 == b["select"]:
                self.open_editor()
            elif d1 in ASSIGN_MODES:
                self.assign = ASSIGN_MODES[d1]
                self.hint("row = " + self.assign)
            elif d1 in (b["left"], b["right"]):
                direction = 1 if d1 == b["right"] else -1
                if MODES[self.mode] == "PERFORM" and not self.shift:
                    self.scene_ofs = max(0, self.scene_ofs + direction)       # scroll blocks
                    self.show_zone()
                elif MODES[self.mode] == "PLUGIN" and not self.shift:
                    self.step_device(direction)
                elif MODES[self.mode] == "STEPS" and not self.shift:
                    last_page = max(0, self.pattern_steps() - 8)
                    self.step_ofs = clamp(self.step_ofs + direction * 8, 0, last_page)
                    self.hint("steps %d-%d" % (self.step_ofs + 1, self.step_ofs + 8))
                else:
                    step = 1 if MODES[self.mode] in ("PERFORM", "STEPS", "PLUGIN") else (8 if self.shift else 1)
                    self.track_ofs = clamp(self.track_ofs + direction * step, 0, self.max_track_ofs())
                    self.show_mixer_zone()
            elif d1 in (b["up"], b["down"]):
                self.scroll_rows(-1 if d1 == b["up"] else 1)
            elif fp.PHYS_TRACK_SELECT <= d1 < fp.PHYS_TRACK_SELECT + 8:
                self.select_track(d1 - fp.PHYS_TRACK_SELECT)
            elif fp.PHYS_TRACK_ASSIGN <= d1 < fp.PHYS_TRACK_ASSIGN + 8:
                self.assign_press(d1 - fp.PHYS_TRACK_ASSIGN, safe)
            elif fp.PHYS_SCENE_LAUNCH <= d1 < fp.PHYS_SCENE_LAUNCH + 8:
                self.scene(d1 - fp.PHYS_SCENE_LAUNCH, safe)
        elif ch == 0:
            if d1 < 8:
                self.select_track(d1)
            elif fp.TUI_TRACK_STOP <= d1 < fp.TUI_TRACK_STOP + 8:
                self.stop_track(d1 - fp.TUI_TRACK_STOP, safe)
            elif fp.TUI_SCENE_LAUNCH <= d1 < fp.TUI_SCENE_LAUNCH + 8:
                self.scene(d1 - fp.TUI_SCENE_LAUNCH, safe)
        elif 1 <= ch <= 8:
            i = self.insert(ch - 1)
            if i is None:
                return
            if d1 == fp.STRIP_MUTE_NOTE:
                mixer.muteTrack(i)
            elif d1 == fp.STRIP_SOLO_NOTE:
                mixer.soloTrack(i)
            elif d1 == fp.STRIP_ARM_NOTE:
                mixer.armTrack(i)
        elif ch == fp.CH_DEVICE:
            db = fp.DEVICE_BUTTONS
            if d1 in (db["prev_bank"], db["next_bank"]):
                direction = 1 if d1 == db["next_bank"] else -1
                if self.shift:
                    self.step_preset(direction)
                else:
                    self.param_bank = max(0, self.param_bank + direction)
            elif d1 in (db["prev_device"], db["next_device"]):
                direction = 1 if d1 == db["next_device"] else -1
                if self.shift:
                    self.fx_mode = not self.fx_mode
                    self.flash("FX CHAIN" if self.fx_mode else "CHANNEL")
                else:
                    self.step_device(direction)
            elif d1 == db["device_on"]:
                self.toggle_target()
        elif ch == fp.CH_GLOBAL:
            g = fp.GLOBAL_BUTTONS
            if d1 == g["metronome"]:
                transport.globalTransport(midi.FPT_Metronome, 1)
            elif d1 == g["loop"]:
                transport.setLoopMode()
            elif d1 == g["launch_mode"]:
                self.set_mode(self.mode + 1)
            elif d1 == g["stop_all"]:
                self.stop_all(safe)
            elif d1 == g["quantize"]:
                self.quantize()
            elif d1 == g["delete"]:
                self.delete()

    def control(self, ch, d1, d2):
        fine = FINE if self.shift else 1.0
        if ch == fp.CH_KNOBS and d1 < 16 and self.held_step:
            self.edit_step_param(d1 % 8, fp.relative(d2))
            self.dirty = True
            return
        if ch == fp.CH_KNOBS and d1 < 8:
            i = self.insert(d1)
            if i is not None:
                v = mixer.getTrackVolume(i) + fp.relative(d2) * VOLUME_STEP * fine
                mixer.setTrackVolume(i, clamp(v, 0.0, 1.0))
        elif ch == fp.CH_KNOBS and d1 < 16:
            self.nudge_param(d1 - 8, fp.relative(d2) * PARAM_STEP * fine)
        elif 1 <= ch <= 8:
            i = self.insert(ch - 1)
            if i is None:
                return
            if d1 == fp.STRIP_VOLUME_CC:
                mixer.setTrackVolume(i, d2 / 127.0)
            elif d1 == fp.STRIP_PAN_CC:
                mixer.setTrackPan(i, clamp((d2 - 63.5) / 63.5, -1.0, 1.0))
            elif fp.STRIP_SEND_CC <= d1 < fp.STRIP_SEND_CC + 4:
                self.set_send(i, d1 - fp.STRIP_SEND_CC, d2 / 127.0)
        elif ch == fp.CH_DEVICE and d1 < 8:
            self.set_param(d1, d2 / 127.0)
        elif ch == fp.CH_GLOBAL and d1 == 0:
            # on-screen song-position encoder: one beat per tick (SHIFT: one step)
            ppq = general.getRecPPQ()
            ticks = ppq // 4 if self.shift else ppq
            pos = self.song_ticks() + fp.relative(d2) * ticks
            transport.setSongPos(max(0, pos), midi.SONGLENGTH_ABSTICKS)
        self.dirty = True

    # ---------------------------------------------------------------- actions
    def set_mode(self, m):
        self.mode = m % len(MODES)       # held pads keep their release action across the switch
        self.track_ofs = clamp(self.track_ofs, 0, self.max_track_ofs())
        if MODES[self.mode] == "SONG":
            if transport.getLoopMode() == midi.SM_Pat:
                transport.setLoopMode()   # bars and markers live in the song
            self.scan_markers()
            bar = self.current_bar()
            self.song_ofs = bar - bar % 64
        if MODES[self.mode] == "PERFORM" and not self.perf_on():
            self.flash("PERF OFF")
            self.hint("Performance Mode is off - turn it on in the playlist to launch clips from the pads")
            return
        self.flash(MODES[self.mode])

    def scan_markers(self):
        """FL can name markers by absolute index but only jump to them relatively, so
        map each marker's position once (only while stopped; the playhead is put back)."""
        names = []
        while len(names) < 256:
            name = arrangement.getMarkerName(len(names))
            if not name:
                break
            names.append(name)
        known = dict(self.markers)
        self.markers = [(n, known.get(n)) for n in names]
        if not names or transport.isPlaying():
            return
        saved = self.song_ticks()
        transport.setSongPos(0, midi.SONGLENGTH_ABSTICKS)
        times, last = [], -1
        for _ in range(len(names)):
            arrangement.jumpToMarker(1, False)
            pos = self.song_ticks()
            if pos <= last:
                break
            times.append(pos)
            last = pos
        if len(times) == len(names) - 1:
            times.insert(0, 0)            # "next marker" from 0 skips a marker sitting at 0
        transport.setSongPos(saved, midi.SONGLENGTH_ABSTICKS)
        if len(times) == len(names):
            self.markers = list(zip(names, times))

    def step_fx_slot(self, direction):
        tr = mixer.trackNumber()
        slot = self.fx_slot
        for _ in range(FX_SLOTS):
            slot = (slot + direction) % FX_SLOTS
            if plugins.isValid(tr, slot):
                self.fx_slot = slot
                self.param_cache_key = None
                return
        self.hint("no effects on " + mixer.getTrackName(tr))

    def set_send(self, i, k, level):
        sends = self.send_tracks()
        if k >= len(sends) or sends[k] == i:
            return
        dest = sends[k]
        if not mixer.getRouteSendActive(i, dest):
            mixer.setRouteTo(i, dest, True)
            mixer.afterRoutingChanged()
        mixer.setRouteToLevel(i, dest, level)

    def quantize(self):
        ch = channels.selectedChannel(True)
        if ch >= 0:
            channels.quickQuantize(ch)
            self.hint("quantized " + channels.getChannelName(ch))

    def delete(self):
        """SHIFT+DELETE: STEPS clears the selected channel's steps; PLUGIN randomizes the bank."""
        ch = channels.selectedChannel(True)
        if MODES[self.mode] == "PLUGIN" and self.shift:
            self.randomize()
        elif MODES[self.mode] == "STEPS" and self.shift and ch >= 0:
            for step in range(self.pattern_steps()):
                if channels.getGridBit(ch, step):
                    channels.setGridBit(ch, step, False)
            self.hint("cleared steps of " + channels.getChannelName(ch))
        else:
            self.hint("SHIFT+DELETE in STEPS mode clears the selected channel's steps")

    def scroll_rows(self, direction):
        mode = MODES[self.mode]
        big = self.shift
        if mode == "PERFORM":
            top = max(0, playlist.trackCount() - 8)
            self.perf_track_ofs = clamp(self.perf_track_ofs + direction * (8 if big else 1), 0, top)
            self.show_zone()
        elif mode == "PATTERNS":
            self.pattern_ofs = clamp(self.pattern_ofs + direction * (64 if big else 8), 0, patterns.patternMax() - 1)
        elif mode == "STEPS":
            top = max(0, channels.channelCount() - 8)
            self.step_chan_ofs = clamp(self.step_chan_ofs + direction * (8 if big else 1), 0, top)
        elif mode == "PLUGIN":
            if big:
                self.param_bank = max(0, self.param_bank + direction)
            else:
                self.step_preset(direction)
        elif mode == "SONG":
            step = 64 if big else 8
            self.song_ofs = clamp(self.song_ofs + direction * step, 0, max(0, self.song_bars() - 8))
        elif mode == "KEYS":
            self.key_base = clamp(self.key_base - direction * (1 if big else 12), 0, 96)
            self.hint("root %s %s" % (note_name(self.key_base), SCALES[self.scale][0]))
        elif mode == "DRUMS":
            self.drum_base = clamp(self.drum_base - direction * (1 if big else 16), 0, 64)
            self.hint("bottom-left = " + note_name(self.drum_base))
        else:
            self.chan_ofs = clamp(self.chan_ofs + direction * (64 if big else 8), 0, max(0, channels.channelCount() - 1))

    def show_zone(self):
        """Outline the area the Force is showing (purely cosmetic, so never fatal)."""
        try:
            if MODES[self.mode] == "PERFORM":
                if self.perf_on():
                    first = self.perf_track_ofs + 1
                    playlist.liveDisplayZone(self.scene_ofs, first, self.scene_ofs + 8, first + 7, 1500)
            else:
                self.show_mixer_zone()
        except RuntimeError:
            pass

    def show_mixer_zone(self):
        try:
            ui.miDisplayRect(self.track_ofs + 1, self.track_ofs + 8, 1500)
        except RuntimeError:
            pass

    def select_track(self, t):
        i = self.insert(t)
        if i is not None:
            mixer.setTrackNumber(i, midi.curfxScrollToMakeVisible)

    def assign_press(self, t, safe):
        i = self.insert(t)
        if self.shift and t == 0:
            self.quantize()               # SHIFT + first row button = quantize (as on Ableton)
        elif self.assign == "stop":
            self.stop_track(t, safe)
        elif i is None:
            return
        elif self.assign == "mute":
            mixer.muteTrack(i)
        elif self.assign == "solo":
            mixer.soloTrack(i)
        elif self.assign == "arm":
            mixer.armTrack(i)

    def stop_track(self, t, safe):
        """Column button under the pads (CLIP STOP row / on-screen stop): in PERFORM,
        launch block column t across all tracks, like an Ableton scene."""
        if safe and MODES[self.mode] == "PERFORM":
            tr = self.perf_track(0)
            if tr is not None:
                playlist.triggerLiveClip(tr, self.scene_ofs + t, midi.TLC_MuteOthers | midi.TLC_Fill | midi.TLC_ColumnMode)

    def stop_all(self, safe):
        if safe and MODES[self.mode] == "PERFORM":
            for tr in range(1, playlist.trackCount() + 1):
                if playlist.getLiveStatus(tr, midi.LB_Status_Simple) == 1:
                    playlist.triggerLiveClip(tr, -1, midi.TLC_MuteOthers | midi.TLC_Fill)
        else:
            transport.stop()

    def scene(self, s, safe):
        """Right-hand button next to pad row s."""
        mode = MODES[self.mode]
        if mode == "PERFORM":
            tr = self.perf_track(s)
            if tr is None:
                return
            # plain press = stop the track's clip; SHIFT+press = mute/unmute the track
            if self.shift:
                playlist.muteTrack(tr)
                self.hint("%s %s" % (playlist.getTrackName(tr), "muted" if playlist.isTrackMuted(tr) else "unmuted"))
            elif safe:
                playlist.triggerLiveClip(tr, -1, midi.TLC_MuteOthers | midi.TLC_Fill)
                self.hint("stopped " + playlist.getTrackName(tr))
        elif mode == "STEPS":
            c = self.step_chan_ofs + s
            if c < channels.channelCount():
                channels.selectOneChannel(c)
        elif mode == "KEYS":
            self.scale = s
            self.flash("%s %s" % (note_name(self.key_base)[:-1], SCALES[s][0]))
        elif mode == "PLUGIN":
            bank = (self.param_bank // 8) * 8 + s
            if bank < (len(self.param_list) + 7) // 8:
                self.param_bank = bank

    # ----------------------------------------------------------------- plugins
    def plugin_view(self):
        target = self.device_target()
        if target is None:
            return None
        self.params(target)
        nbanks = max(1, (len(self.param_list) + 7) // 8)
        self.param_bank = clamp(self.param_bank, 0, nbanks - 1)
        bank = self.bank_params()
        i, slot = target
        color = self.color_of(channels.getChannelColor(i) if slot < 0 else mixer.getTrackColor(i))
        values = [plugins.getParamValue(p, i, slot) for p in bank]
        names = [plugins.getParamName(p, i, slot) for p in bank]
        texts = [plugins.getParamValueString(p, i, slot) for p in bank]
        return target, bank, values, names, texts, color

    def preset_name(self, target):
        try:
            name = plugins.getName(target[0], target[1], midi.FPN_Preset)
        except (AttributeError, TypeError):
            name = ""
        return name or self.preset_text

    def step_preset(self, direction):
        target = self.device_target()
        if target is None:
            self.hint("select a channel with a plugin first")
            return
        if plugins.getPresetCount(target[0], target[1]) <= 0:
            self.hint("this plugin has no presets FL can switch")
            return
        (plugins.nextPreset if direction > 0 else plugins.prevPreset)(target[0], target[1])
        self.preset_text = ""
        name = self.preset_name(target)
        self.preset_text = name or ("next preset" if direction > 0 else "previous preset")
        self.flash(self.preset_text.upper()[:12])
        self.rand_snapshot = None

    def step_device(self, direction):
        """Previous/next plugin: the next channel, or the next effect slot in FX-chain mode."""
        if self.fx_mode:
            self.step_fx_slot(direction)
        else:
            c = clamp(channels.selectedChannel() + direction, 0, channels.channelCount() - 1)
            channels.selectOneChannel(c)
            self.hint("channel: " + channels.getChannelName(c))

    def open_editor(self):
        """Show the plugin window in FL (instruments toggle open/closed)."""
        target = self.device_target()
        if target is None:
            self.hint("no plugin to open")
        elif target[1] < 0:
            channels.showEditor(target[0])
        else:
            mixer.focusEditor(target[0], target[1])

    def target_enabled(self, target):
        i, slot = target
        if slot < 0:
            return not channels.isChannelMuted(i)
        try:
            return mixer.getEventValue(mixer.getTrackPluginId(i, slot) + midi.REC_Plug_Mute) > 0
        except (AttributeError, TypeError):
            return True

    def toggle_target(self):
        """Device on/off: bypass an effect, or mute an instrument's channel."""
        target = self.device_target()
        if target is None:
            return
        i, slot = target
        on = self.target_enabled(target)
        if slot < 0:
            channels.muteChannel(i)
        else:
            general.processRECEvent(mixer.getTrackPluginId(i, slot) + midi.REC_Plug_Mute, 0 if on else SLOT_ON,
                                    midi.REC_Control | midi.REC_UpdateControl)
        self.flash("BYPASS" if on else "ON")

    def randomize(self):
        pv = self.plugin_view()
        if not pv:
            return
        (i, slot), bank = pv[0], pv[1]
        self.rand_snapshot = (pv[0], [(p, plugins.getParamValue(p, i, slot)) for p in bank])
        for p in bank:
            plugins.setParamValue(random.random(), p, i, slot)
        self.flash("RANDOM")
        self.hint("randomized 8 parameters - press UNDO to put them back")

    def undo_randomize(self):
        """UNDO right after a randomize restores those parameters (plugin moves aren't in FL's undo)."""
        if not self.rand_snapshot or MODES[self.mode] != "PLUGIN":
            return False
        (i, slot), values = self.rand_snapshot
        for p, v in values:
            plugins.setParamValue(v, p, i, slot)
        self.rand_snapshot = None
        self.flash("RESTORED")
        return True

    def nudge_param(self, i, delta):
        target = self.device_target()
        if target is None:
            return
        self.params(target)
        bank = self.bank_params()
        if i < len(bank):
            v = plugins.getParamValue(bank[i], target[0], target[1]) + delta
            plugins.setParamValue(clamp(v, 0.0, 1.0), bank[i], target[0], target[1])

    def set_param(self, i, value):
        target = self.device_target()
        if target is None:
            return
        self.params(target)
        bank = self.bank_params()
        if i < len(bank):
            plugins.setParamValue(value, bank[i], target[0], target[1])

    # ----------------------------------------------------------------- meters
    def on_meters(self):
        if not self.connected:
            return
        try:
            self._send_meters()
        except RuntimeError:
            pass                          # FL busy (project loading); next meter tick will retry

    def _send_meters(self):
        for t in range(8):
            i = self.insert(t)
            for side, cc_ in ((0, fp.STRIP_METER_L_CC), (1, fp.STRIP_METER_R_CC)):
                peak = mixer.getTrackPeaks(i, side) if i is not None else 0.0
                # -60 dB .. 0 dB -> 0..127
                v = 0 if peak <= 0.001 else clamp(int(127 * (1 + 20 * math.log10(peak) / 60)), 0, 127)
                self.cc(t + 1, cc_, v)


force = Force()


def OnInit():
    force.on_init()


def OnDeInit():
    force.on_deinit()


def OnIdle():
    force.on_idle()


def OnMidiMsg(event):
    force.on_midi(event)


def OnSysEx(event):
    force.on_sysex(event)


def OnRefresh(flags):
    force.on_refresh(flags)


def OnUpdateLiveMode(last_track):
    force.dirty = True


def OnUpdateMeters():
    force.on_meters()
