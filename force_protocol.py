"""
Akai Force "Live Control" protocol.

Reconstructed from Ableton's own Akai_Force_MPC remote script (Live 12) so that
any host -- a desktop bridge or an FL Studio MIDI script -- can drive the Force
exactly the way Ableton does.

Pure Python, no imports, so FL Studio's embedded interpreter can use it as-is.

Channels below are 0-based (the low nibble of the MIDI status byte).
The Force talks on the "Akai Network - DAW Control" port.

Two families of controls:
  * PHYSICAL  -- hardware buttons / pads / knobs.   Channels 12 (buttons, pad
                 notes, LED colours) and 13 (knobs, knob touch, OLED styles).
  * TUI       -- the Force's own touchscreen UI.     Channels 0-10.  The host
                 never draws pixels; it just sends names, colours and values
                 and the Force renders its built-in "Ableton" screens.
"""

# --------------------------------------------------------------------------
# SysEx framing:  F0 47 00 <product> <type> [id0 id1] [payload] F7
# --------------------------------------------------------------------------
AKAI = 0x47
FORCE = 0x40
MPC_X = 0x3A
MPC_LIVE = 0x3B
BROADCAST = 0x7F

MSG_PING = 0x00   # host -> device, sent to BROADCAST every ~3 s
MSG_PONG = 0x01   # device -> host, carries the product id
MSG_TEXT = 0x10   # text for a display slot (both directions: Force sends tempo edits)
MSG_COLOR = 0x11  # defined by Ableton's script but unused by it

PING_PERIOD = 3.0         # seconds; Ableton disconnects if a pong is missed
TEXT_MAX_CHARS = 64

# Colour values sent on "color" CCs.  0-7 are state colours, 8+ is Live's
# 70-entry clip/track palette (see PALETTE_RGB).
COLOR_OFF = 0
COLOR_1 = 1        # mute / tap tempo / "enabled" accent
COLOR_2 = 2        # solo / clip stopped / scene on
COLOR_3 = 3        # arm (Force) / clip triggered
COLOR_4 = 4        # clip playing
COLOR_6 = 6        # clip triggered to record / metronome on
COLOR_7 = 7        # clip recording
COLOR_ON = 127     # white / selected
PALETTE_OFFSET = 8

# Clip-slot state, sent as the *velocity* of the clip-launch note.
CLIP_EMPTY = 0
CLIP_EMPTY_WITH_STOP = 1
CLIP_STOPPED = 2
CLIP_TRIGGERED = 3
CLIP_PLAYING = 4
CLIP_TRIGGERED_REC = 6
CLIP_RECORDING = 7

# Track type, sent as the velocity of TUI note (ch0, 8+track).
TRACK_NONE = 0
TRACK_EMPTY_MIDI = 1
TRACK_DRUM = 2
TRACK_MELODIC = 4
TRACK_AUDIO = 6
TRACK_GROUP = 7
TRACK_RETURN = 8
TRACK_MASTER = 9

OLED_OFF = 0
OLED_UNIPOLAR = 1

# 7-bit RGB of Live's colour palette; index i is sent as PALETTE_OFFSET + i.
PALETTE_RGB = (
    (127, 74, 83), (127, 82, 20), (102, 76, 19), (123, 122, 62), (95, 125, 0),
    (13, 127, 23), (18, 127, 84), (46, 127, 116), (69, 98, 127), (42, 64, 114),
    (73, 83, 127), (108, 54, 114), (114, 41, 80), (127, 127, 127), (127, 27, 27),
    (123, 54, 1), (76, 57, 37), (127, 120, 26), (67, 127, 51), (30, 97, 0),
    (0, 95, 87), (12, 116, 127), (8, 82, 119), (0, 62, 96), (68, 54, 114),
    (91, 59, 99), (127, 28, 106), (104, 104, 104), (113, 51, 45), (127, 81, 58),
    (105, 86, 56), (118, 127, 87), (105, 114, 76), (93, 104, 58), (77, 98, 70),
    (106, 126, 112), (102, 120, 124), (92, 96, 113), (102, 93, 114), (87, 76, 114),
    (114, 110, 112), (84, 84, 84), (99, 73, 69), (91, 65, 43), (76, 65, 53),
    (95, 93, 52), (83, 95, 0), (62, 88, 38), (68, 97, 93), (77, 89, 98),
    (66, 82, 97), (65, 73, 102), (82, 74, 90), (95, 79, 95), (94, 56, 75),
    (61, 61, 61), (87, 25, 25), (84, 40, 24), (57, 39, 32), (109, 97, 0),
    (66, 75, 15), (41, 79, 24), (5, 78, 71), (17, 49, 66), (13, 23, 75),
    (23, 41, 81), (49, 37, 86), (81, 37, 86), (102, 23, 55), (30, 30, 30),
)

# --------------------------------------------------------------------------
# Physical controls  (channel 12 unless noted)
# --------------------------------------------------------------------------
CH_PHYS = 12
CH_KNOBS = 13

# Buttons (note on/off).  Name -> note number.
PHYS_BUTTONS = {
    "master": 88, "stop_all": 89, "launch": 91, "select": 94,
    "copy": 96, "delete": 97, "tap_tempo": 99,
    "mute": 100, "solo": 101, "rec_arm": 102, "clip_stop": 103,
    "play": 104, "stop": 105, "rec": 106, "undo": 107,
    "shift": 114, "up": 115, "down": 116, "left": 117, "right": 118,
    "assign_a": 119, "assign_b": 120,
}
PHYS_TRACK_SELECT = 0      # notes 0-7   (row of 8 above the pads)
PHYS_TRACK_ASSIGN = 8      # notes 8-15  (row of 8 below the pads)
PHYS_PAD = 16              # notes 16-79 : 16 + scene*8 + track   (row-major)
PHYS_SCENE_LAUNCH = 80     # notes 80-87 (right-hand column)

# LED colour CCs on channel 12
PHYS_TRACK_SELECT_COLOR = 24   # CC 24-31
PHYS_TRACK_ASSIGN_COLOR = 32   # CC 32-39
PHYS_PAD_COLOR = 40            # CC 40-103 : 40 + scene*8 + track   (row-major, like the notes;
                               #  verified on hardware -- Ableton's source reads column-major but isn't)

# Knobs on channel 13: relative two's-complement CCs, touch as notes.
KNOB_MIXER = 0         # CC 0-7   (knobs in mixer mode)   touch notes 0-7
KNOB_DEVICE = 8        # CC 8-15  (knobs in device mode)  touch notes 8-15
CROSSFADER_CC = 16     # CC 16, absolute
OLED_STYLE_MIXER = 16  # notes 16-23 on ch13 -> OLED_OFF / OLED_UNIPOLAR
OLED_STYLE_DEVICE = 24  # notes 24-31 on ch13

# --------------------------------------------------------------------------
# Touchscreen (TUI) controls
# --------------------------------------------------------------------------
# Per-track mixer strip lives on channel (track + 1):
STRIP_VOLUME_CC = 0        # absolute 0-127, both directions
STRIP_PAN_CC = 1
STRIP_SEND_CC = 3          # CC 3-6 = sends A-D
STRIP_METER_L_CC = 124     # host -> Force, 0-127
STRIP_METER_R_CC = 125
STRIP_SOLO_NOTE = 0
STRIP_MUTE_NOTE = 1
STRIP_MUTED_BY_SOLO_NOTE = 2
STRIP_XFADE_NOTE = 4
STRIP_ARM_NOTE = 5

# Session / track row on channel 0
TUI_TRACK_SELECT = 0       # notes 0-7
TUI_TRACK_TYPE = 8         # notes 8-15, velocity = TRACK_*
TUI_TRACK_STOP = 16        # notes 16-23
TUI_CLIP_LAUNCH = 24       # notes 24-87 : 24 + scene*8 + track (row-major)
TUI_SCENE_LAUNCH = 88      # notes 88-95
TUI_SCENE_SELECT = 96      # notes 96-103
TUI_PLAY_POSITION_CC = 0   # CC 0-7, per-track clip play position
TUI_TRACK_COLOR_CC = 16    # CC 16-23
TUI_CLIP_COLOR_CC = 24     # CC 24-87 : 24 + scene*8 + track (row-major, verified on hardware)
TUI_SCENE_COLOR_CC = 88    # CC 88-95
NUM_SENDS_CH, NUM_SENDS_CC = 1, 2

# Device page on channel 9
CH_DEVICE = 9
DEVICE_PARAM_CC = 0        # CC 0-7 absolute (touch faders on screen)
DEVICE_PARAM_ENABLE = 112  # notes 112-119
DEVICE_BUTTONS = {"device_on": 0, "prev_device": 1, "next_device": 2, "prev_bank": 3, "next_bank": 4}
DEVICE_COUNT_CC, DEVICE_INDEX_CC = 16, 17

# Transport / global on channel 10
CH_GLOBAL = 10
GLOBAL_BUTTONS = {
    "metronome": 0, "overdub": 3, "automation_arm": 4, "loop": 5,
    "launch_quantize": 6, "follow": 8, "device_lock": 10,
    "nudge_down": 12, "nudge_up": 13, "delete": 14, "quantize_value": 15,
    "quantize": 16, "stop_all": 20, "insert_scene": 21,
    "arrangement_record": 22, "launch_mode": 23,
}
GLOBAL_ENCODERS = {0: "song_position", 1: "loop_start", 2: "loop_length"}  # relative

# Text display slots:  (id0, id1)
def TXT_TRACK_NAME(t): return (0, t)
def TXT_CLIP_NAME(t, s): return (0, 16 + s * 8 + t)   # row-major, verified on hardware
def TXT_SCENE_NAME(s): return (0, 80 + s)
def TXT_VOLUME(t): return (1, t)
def TXT_PAN(t): return (1, 16 + t)
def TXT_SEND(t, send): return (1, 24 + t + send * 8)
TXT_DEVICE_BANK = (2, 0)
TXT_DEVICE_NAME = (2, 1)
def TXT_PARAM_NAME(i): return (2, 16 + i)
def TXT_PARAM_VALUE(i): return (2, 32 + i)
TXT_TEMPO = (3, 0)
TXT_SONG_POSITION = (3, 16)
TXT_LOOP_START = (3, 17)
TXT_LOOP_LENGTH = (3, 18)
def TXT_OLED_MIXER(t): return (18, 16 + t)   # small screen above each knob
def TXT_OLED_DEVICE(i): return (18, 24 + i)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def pad_note(track, scene): return PHYS_PAD + scene * 8 + track
def pad_color_cc(track, scene): return PHYS_PAD_COLOR + scene * 8 + track
def tui_clip_note(track, scene): return TUI_CLIP_LAUNCH + scene * 8 + track
def tui_clip_color_cc(track, scene): return TUI_CLIP_COLOR_CC + scene * 8 + track
def palette(index): return PALETTE_OFFSET + (index % len(PALETTE_RGB))


def relative(value):
    """Decode a two's-complement relative encoder value to a signed delta."""
    return value - 128 if value > 64 else value


def nearest_palette_index(r, g, b):
    """Map an 8-bit RGB colour to the closest palette index (for FL colours)."""
    r, g, b = r >> 1, g >> 1, b >> 1
    best, best_d = 0, 1 << 30
    for i, (pr, pg, pb) in enumerate(PALETTE_RGB):
        d = (pr - r) ** 2 + (pg - g) ** 2 + (pb - b) ** 2
        if d < best_d:
            best, best_d = i, d
    return best


def sysex_ping():
    return [0xF0, AKAI, 0x00, BROADCAST, MSG_PING, 0xF7]


def sysex_text(slot, text, product=FORCE):
    chars = [c if 32 <= c < 127 else ord("?") for c in (ord(ch) for ch in str(text).strip()[:TEXT_MAX_CHARS])]
    n = len(chars)
    return [0xF0, AKAI, 0x00, product, MSG_TEXT, slot[0], slot[1], min(n // 128, 127), n % 128] + chars + [0xF7]


def parse_sysex(data):
    """Parse a full sysex message (F0 ... F7, as a list of ints).
    Returns ('pong', product) | ('text', (id0, id1), str) | ('unknown', data)."""
    if len(data) < 6 or data[1] != AKAI or data[2] != 0x00:
        return ("unknown", data)
    product, kind = data[3], data[4]
    if kind == MSG_PONG:
        return ("pong", product)
    if kind == MSG_TEXT and len(data) >= 10:
        slot = (data[5], data[6])
        body = data[9:-1]
        return ("text", slot, "".join(chr(c) for c in body))
    return ("unknown", data)


# --------------------------------------------------------------------------
# Reverse lookup for logging / debugging:  describe(status, d1) -> name
# --------------------------------------------------------------------------
def _build_names():
    notes, ccs = {}, {}
    for name, n in PHYS_BUTTONS.items():
        notes[(CH_PHYS, n)] = name
    for i in range(8):
        notes[(CH_PHYS, PHYS_TRACK_SELECT + i)] = "track_select_%d" % (i + 1)
        notes[(CH_PHYS, PHYS_TRACK_ASSIGN + i)] = "track_assign_%d" % (i + 1)
        notes[(CH_PHYS, PHYS_SCENE_LAUNCH + i)] = "scene_launch_%d" % (i + 1)
        notes[(CH_KNOBS, KNOB_MIXER + i)] = "knob_touch_mixer_%d" % (i + 1)
        notes[(CH_KNOBS, KNOB_DEVICE + i)] = "knob_touch_device_%d" % (i + 1)
        ccs[(CH_KNOBS, KNOB_MIXER + i)] = "knob_mixer_%d" % (i + 1)
        ccs[(CH_KNOBS, KNOB_DEVICE + i)] = "knob_device_%d" % (i + 1)
        ch = i + 1
        ccs[(ch, STRIP_VOLUME_CC)] = "tui_volume_%d" % (i + 1)
        ccs[(ch, STRIP_PAN_CC)] = "tui_pan_%d" % (i + 1)
        for s in range(4):
            ccs[(ch, STRIP_SEND_CC + s)] = "tui_send_%s_%d" % ("ABCD"[s], i + 1)
        notes[(ch, STRIP_SOLO_NOTE)] = "tui_solo_%d" % (i + 1)
        notes[(ch, STRIP_MUTE_NOTE)] = "tui_mute_%d" % (i + 1)
        notes[(ch, STRIP_XFADE_NOTE)] = "tui_xfade_assign_%d" % (i + 1)
        notes[(ch, STRIP_ARM_NOTE)] = "tui_arm_%d" % (i + 1)
        notes[(0, TUI_TRACK_SELECT + i)] = "tui_track_select_%d" % (i + 1)
        notes[(0, TUI_TRACK_STOP + i)] = "tui_track_stop_%d" % (i + 1)
        notes[(0, TUI_SCENE_LAUNCH + i)] = "tui_scene_launch_%d" % (i + 1)
        notes[(0, TUI_SCENE_SELECT + i)] = "tui_scene_select_%d" % (i + 1)
        ccs[(CH_DEVICE, DEVICE_PARAM_CC + i)] = "tui_param_%d" % (i + 1)
        notes[(CH_DEVICE, DEVICE_PARAM_ENABLE + i)] = "tui_param_enable_%d" % (i + 1)
        for s in range(8):
            notes[(CH_PHYS, pad_note(i, s))] = "pad_t%d_s%d" % (i + 1, s + 1)
            notes[(0, tui_clip_note(i, s))] = "tui_clip_t%d_s%d" % (i + 1, s + 1)
    for name, n in DEVICE_BUTTONS.items():
        notes[(CH_DEVICE, n)] = "tui_" + name
    for name, n in GLOBAL_BUTTONS.items():
        notes[(CH_GLOBAL, n)] = "tui_" + name
    for n, name in GLOBAL_ENCODERS.items():
        ccs[(CH_GLOBAL, n)] = "tui_" + name
    ccs[(CH_KNOBS, CROSSFADER_CC)] = "crossfader"
    return notes, ccs


NOTE_NAMES, CC_NAMES = _build_names()


def describe(status, d1):
    kind, ch = status & 0xF0, status & 0x0F
    if kind in (0x80, 0x90):
        return NOTE_NAMES.get((ch, d1), "note ch%d n%d" % (ch, d1))
    if kind == 0xB0:
        return CC_NAMES.get((ch, d1), "cc ch%d cc%d" % (ch, d1))
    return "status %02X" % status
