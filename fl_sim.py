"""
fl_sim.py - run device_AkaiForce.py outside FL Studio against a fake FL project.

  python fl_sim.py            # automated checks (no hardware needed)
  python fl_sim.py --live     # connect the script to the real Force over the network port

The fake modules implement just enough of FL's scripting API for the script.
FL's real midi.py (constants only) is loaded from the FL install, or, without FL
(e.g. on Linux / CI), from the fl-studio-api-stubs package: pip install fl-studio-api-stubs
"""
import importlib.util
import math
import os
import random
import sys
import time
import types

FL_MIDI = os.environ.get("FL_MIDI", r"C:\Program Files\Image-Line\FL Studio 2026\Shared\Python\Lib\midi.py")
HERE = os.path.dirname(os.path.abspath(__file__))


def load_midi():
    if not os.path.exists(FL_MIDI):
        import midi as stub          # fl-studio-api-stubs
        if not hasattr(stub, "REC_Plug_Mute"):   # missing from the stubs; any offset works in the sim
            stub.REC_Plug_Mute = stub.REC_PlugReserved + 8
        return stub
    spec = importlib.util.spec_from_file_location("midi", FL_MIDI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules["midi"] = mod
    return mod


midi = load_midi()
calls = []          # (module.func, args) log of state-changing API calls
out_msgs = []       # (status, d1, d2) sent to the Force
out_sysex = []      # bytes sent to the Force
live_out = None     # mido output when --live


def rec(name, *args):
    calls.append((name, args))


def module(name, **fns):
    m = types.ModuleType(name)
    for k, v in fns.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


# ---------------------------------------------------------------- fake project
COLORS = [0xE0533D, 0xF2A33A, 0xE8D44D, 0x6CC04A, 0x3FB6A8, 0x3D7FE0, 0x8E5AE0, 0xE05AB8]
S = types.SimpleNamespace(
    tracks=[dict(name="Insert %d" % i, color=COLORS[i % 8], vol=0.8, pan=0.0, mute=False, solo=False, arm=False)
            for i in range(127)],
    assigned=True, sel_track=1, playing=False, recording=False, loop_mode=0, metronome=False, tempo=140.0,
    pl_tracks=["Drums", "Bass", "Chords", "Lead", "FX", "Vox", "Perc", "Pad"] + ["Track %d" % i for i in range(9, 21)],
    blocks={}, pattern=1, pattern_count=6, sel_chan=0,
    chans=["Kick", "Snare", "Hat", "Clap", "Bass", "Keys", "Lead", "Pad", "FX", "Vox"],
    params=["Cutoff", "Resonance", "Attack", "Decay", "Sustain", "Release", "Drive", "Mix", "LFO Rate", "LFO Amt"],
    param_vals={},
)
S.tracks[0]["name"] = "Master"
for tr in range(1, 9):
    for b in range(0, 4 if tr % 2 else 6):
        S.blocks[(tr, b)] = 0      # 0 = stopped, 2 = queued, 4 = playing


def trigger_live_clip(tr, block, flags, velocity=-1):
    rec("playlist.triggerLiveClip", tr, block, flags)
    if flags & midi.TLC_Release:
        return
    for (t, b) in S.blocks:
        if t == tr:
            S.blocks[(t, b)] = 0
    if block >= 0 and (tr, block) in S.blocks:
        S.blocks[(tr, block)] = 4


def block_status(tr, block, mode=0):
    if (tr, block) not in S.blocks:
        return 0
    return 1 | S.blocks[(tr, block)]


def dev_out(msg):
    if not S.assigned:
        raise RuntimeError("Linked device not assigned")     # what real FL does
    status, d1, d2 = msg & 0xFF, (msg >> 8) & 0xFF, (msg >> 16) & 0xFF
    out_msgs.append((status, d1, d2))
    if live_out:
        import mido
        live_out.send(mido.Message.from_bytes([status, d1, d2]))


def dev_sysex(data):
    out_sysex.append(bytes(data))
    if live_out:
        import mido
        live_out.send(mido.Message("sysex", data=list(data)[1:-1]))


module("device", midiOutMsg=dev_out, midiOutSysex=dev_sysex, isAssigned=lambda: S.assigned,
       setHasMeters=lambda: None)
module("general", processRECEvent=lambda e, v, f: (rec("general.processRECEvent", e, v, f),
                                                   setattr(S, "tempo", v / 1000) if e == midi.REC_Tempo else None)[0],
       undoUp=lambda: rec("general.undoUp"), undoDown=lambda: rec("general.undoDown"), getVersion=lambda: 40)
module("mixer",
       trackCount=lambda: 127,
       getTrackName=lambda i: S.tracks[i]["name"],
       getTrackColor=lambda i: S.tracks[i]["color"],
       getTrackVolume=lambda i, mode=0: (20 * math.log10(S.tracks[i]["vol"] / 0.8) if S.tracks[i]["vol"] > 0 else -math.inf) if mode else S.tracks[i]["vol"],
       setTrackVolume=lambda i, v, pickup=0: (rec("mixer.setTrackVolume", i, round(v, 4)), S.tracks[i].__setitem__("vol", v))[0],
       getTrackPan=lambda i: S.tracks[i]["pan"],
       setTrackPan=lambda i, v, pickup=0: (rec("mixer.setTrackPan", i, round(v, 3)), S.tracks[i].__setitem__("pan", v))[0],
       isTrackMuted=lambda i: S.tracks[i]["mute"], isTrackSolo=lambda i: S.tracks[i]["solo"],
       isTrackArmed=lambda i: S.tracks[i]["arm"],
       muteTrack=lambda i, v=-1: (rec("mixer.muteTrack", i), S.tracks[i].__setitem__("mute", not S.tracks[i]["mute"]))[0],
       soloTrack=lambda i, v=-1, m=-1: (rec("mixer.soloTrack", i), S.tracks[i].__setitem__("solo", not S.tracks[i]["solo"]))[0],
       armTrack=lambda i: (rec("mixer.armTrack", i), S.tracks[i].__setitem__("arm", not S.tracks[i]["arm"]))[0],
       trackNumber=lambda: S.sel_track,
       setTrackNumber=lambda i, f=0: (rec("mixer.setTrackNumber", i), setattr(S, "sel_track", i))[0],
       getTrackPeaks=lambda i, m: (random.random() * 0.9 if S.playing else 0.0),
       getCurrentTempo=lambda asInt=False: int(S.tempo * 1000),
       getActiveEffectIndex=lambda: None)
module("playlist",
       trackCount=lambda: len(S.pl_tracks),
       getTrackName=lambda i: S.pl_tracks[i - 1],
       getTrackColor=lambda i: COLORS[i % 8],
       getLiveBlockStatus=block_status,
       getLiveBlockColor=lambda tr, b: COLORS[(tr + b) % 8],
       getLiveStatus=lambda tr, mode=0: int(any(v == 4 for (t, b), v in S.blocks.items() if t == tr)),
       triggerLiveClip=trigger_live_clip,
       liveDisplayZone=lambda *a: rec("playlist.liveDisplayZone", *a))
module("patterns",
       patternNumber=lambda: S.pattern, patternCount=lambda: S.pattern_count, patternMax=lambda: 999,
       getPatternName=lambda p: "Pattern %d" % p, getPatternColor=lambda p: COLORS[p % 8],
       jumpToPattern=lambda p: (rec("patterns.jumpToPattern", p), setattr(S, "pattern", p),
                                setattr(S, "pattern_count", max(S.pattern_count, p)))[0])
module("channels",
       channelCount=lambda g=False: len(S.chans),
       selectedChannel=lambda canBeNone=False, offset=0, indexGlobal=False: S.sel_chan,
       getChannelName=lambda i, g=False: S.chans[i], getChannelColor=lambda i, g=False: COLORS[i % 8],
       getChannelIndex=lambda i: i,
       selectOneChannel=lambda i, g=False: (rec("channels.selectOneChannel", i), setattr(S, "sel_chan", i))[0],
       midiNoteOn=lambda i, n, v, c=-1: rec("channels.midiNoteOn", i, n, v))
module("plugins",
       isValid=lambda i, slot=-1, g=False: 0 <= i < len(S.chans),
       getPluginName=lambda i, slot=-1, u=False, g=False: "Synth for " + S.chans[i],
       getParamCount=lambda i, slot=-1, g=False: 40,
       getParamName=lambda p, i, slot=-1, g=False: S.params[p] if p < len(S.params) else "",
       getParamValue=lambda p, i, slot=-1, g=False: S.param_vals.get((i, p), 0.5),
       setParamValue=lambda v, p, i, slot=-1, pk=0, g=False: (rec("plugins.setParamValue", round(v, 3), p, i),
                                                           S.param_vals.__setitem__((i, p), v))[0],
       getParamValueString=lambda p, i, slot=-1, pk=0, g=False: "%d%%" % round(S.param_vals.get((i, p), 0.5) * 100))
module("transport",
       start=lambda: (rec("transport.start"), setattr(S, "playing", not S.playing))[0],
       stop=lambda: (rec("transport.stop"), setattr(S, "playing", False))[0],
       record=lambda: (rec("transport.record"), setattr(S, "recording", not S.recording))[0],
       isPlaying=lambda: S.playing, isRecording=lambda: S.recording,
       getLoopMode=lambda: S.loop_mode, setLoopMode=lambda: setattr(S, "loop_mode", 1 - S.loop_mode),
       getSongPosHint=lambda: "1:01:000",
       globalTransport=lambda cmd, val, pme=0, flags=0: rec("transport.globalTransport", cmd, val))
module("ui",
       setHintMsg=lambda m: rec("ui.setHintMsg", m),
       isMetronomeEnabled=lambda: S.metronome, getFocused=lambda w: False,
       miDisplayRect=lambda *a: rec("ui.miDisplayRect", *a))

# --- step sequencer, markers, song position, sends, effect slots -----------------
S.grid = {}                                   # (channel, step) -> bool
S.pos = 0                                     # song position, ticks (PPQ 96)
S.markers = [("Intro", 0), ("Verse", 1536), ("Drop", 3072)]
S.routes = {}                                 # (src, dest) -> send level
S.fx = {(1, 0): "Fruity Reverb 2", (1, 2): "Fruity Delay 3"}
S.pl_mute, S.pl_solo = set(), set()
S.tracks[20]["name"] = "Reverb Bus"
S.tracks[21]["name"] = "Delay"
_m = sys.modules
_m["channels"].getGridBit = lambda c, st, g=False: S.grid.get((c, st), False)
_m["channels"].setGridBit = lambda c, st, v, g=False: (rec("channels.setGridBit", c, st, bool(v)),
                                                        S.grid.__setitem__((c, st), bool(v)))[0]
_m["channels"].quickQuantize = lambda c, startOnly=1, g=False: rec("channels.quickQuantize", c)
_m["patterns"].getPatternLength = lambda p: 16          # FL 2026 reports steps (docs say beats)
S.sp = {}                                                   # (channel, step, param) -> value
S.types = {4: 2, 6: 2}                                      # Bass and Lead are generator plugins
STEP_DEFAULTS = [60, 100, 64, 120, 64, 128, 128, 0, 0]      # what FL returned for a plain step


def get_step_param(step, param, offset, start_pos, pads_stride=16, g=False):
    pos = start_pos + step
    if not S.grid.get((offset, pos)):
        return -1
    return S.sp.get((offset, pos, param), STEP_DEFAULTS[param])


_m["channels"].getChannelType = lambda c, g=False: S.types.get(c, 0)
_m["channels"].getStepParam = get_step_param
_m["channels"].setStepParameterByIndex = lambda i, pat, st, prm, v, g=False: (
    rec("channels.setStepParameterByIndex", i, pat, st, prm, v, g), S.sp.__setitem__((i, st, prm), v))[0]
_m["channels"].getChannelColor = lambda i, g=False: 0x5C656A if i == 9 else COLORS[i % 8]   # FL default grey
S.perf = True
_m["playlist"].getPerformanceModeState = lambda: S.perf

# a VST-like parameter list: real params, gaps, a Macro further down, and FL's MIDI CC junk at the end
S.params = S.params + ["", "", "Macro 1"] + [""] * 7 + ["MIDI CC #%d" % n for n in range(10)]
S.presets, S.preset_idx = ["Init", "Bass 1", "Lead 2"], 0
S.ch_mute, S.ev = set(), {}
_m["plugins"].getPresetCount = lambda i, slot=-1, g=False: len(S.presets)
_m["plugins"].nextPreset = lambda i, slot=-1, g=False: (rec("plugins.nextPreset", i, slot),
                                                        setattr(S, "preset_idx", (S.preset_idx + 1) % len(S.presets)))[0]
_m["plugins"].prevPreset = lambda i, slot=-1, g=False: (rec("plugins.prevPreset", i, slot),
                                                        setattr(S, "preset_idx", (S.preset_idx - 1) % len(S.presets)))[0]
_m["plugins"].getName = lambda i, slot=-1, flag=0, pi=0, g=False: S.presets[S.preset_idx] if flag == midi.FPN_Preset else ""
_m["plugins"].getParamCount = lambda i, slot=-1, g=False: len(S.params)
_m["channels"].isChannelMuted = lambda i, g=False: i in S.ch_mute
_m["channels"].muteChannel = lambda i, v=-1, g=False: (rec("channels.muteChannel", i), S.ch_mute.symmetric_difference_update({i}))[0]
_m["channels"].showEditor = lambda i, v=-1, g=False: rec("channels.showEditor", i)
_m["mixer"].focusEditor = lambda i, slot: rec("mixer.focusEditor", i, slot)
_m["mixer"].getTrackPluginId = lambda i, slot: ((i << 6) + slot) << 16
_m["mixer"].getEventValue = lambda ev, v=0, st=1: S.ev.get(ev, 1 << 30)
_real_rec = _m["general"].processRECEvent


def process_rec(ev, v, flags):
    if ev != midi.REC_Tempo:
        rec("general.processRECEvent", ev, v, flags)
        S.ev[ev] = v
        return 0
    return _real_rec(ev, v, flags)


_m["general"].processRECEvent = process_rec
S.song_bars = 16
_m["transport"].getSongLength = lambda mode: S.song_bars
_m["general"].getRecPPB = lambda: 384
_m["patterns"].clonePattern = lambda p=None: rec("patterns.clonePattern")
_m["mixer"].getSongStepPos = lambda: 5
_m["mixer"].getRouteSendActive = lambda a, b: (a, b) in S.routes
_m["mixer"].getRouteToLevel = lambda a, b: S.routes.get((a, b), 0.0)
_m["mixer"].setRouteTo = lambda a, b, v, u=False: (rec("mixer.setRouteTo", a, b, v), S.routes.setdefault((a, b), 0.8))[0]
_m["mixer"].setRouteToLevel = lambda a, b, lv: (rec("mixer.setRouteToLevel", a, b, round(lv, 3)),
                                                S.routes.__setitem__((a, b), lv))[0]
_m["mixer"].afterRoutingChanged = lambda: rec("mixer.afterRoutingChanged")
_m["transport"].getSongPos = lambda mode=-1: S.pos
_m["transport"].setSongPos = lambda p, mode=-1: (rec("transport.setSongPos", int(p), mode), setattr(S, "pos", int(p)))[0]
_m["general"].getRecPPQ = lambda: 96
_m["plugins"].isValid = lambda i, slot=-1, g=False: (i, slot) in S.fx if slot >= 0 else 0 <= i < len(S.chans)
_m["plugins"].getPluginName = lambda i, slot=-1, u=False, g=False: S.fx[(i, slot)] if slot >= 0 else "Synth for " + S.chans[i]
_m["playlist"].isTrackMuted = lambda i: i in S.pl_mute
_m["playlist"].isTrackSolo = lambda i: i in S.pl_solo
_m["playlist"].muteTrack = lambda i, v=-1: (rec("playlist.muteTrack", i), S.pl_mute.symmetric_difference_update({i}))[0]
_m["playlist"].soloTrack = lambda i, v=-1, g=False: (rec("playlist.soloTrack", i), S.pl_solo.symmetric_difference_update({i}))[0]


def jump_to_marker(delta, select):
    """FL semantics: relative jump to the next/previous marker strictly after/before the playhead."""
    rec("arrangement.jumpToMarker", delta)
    after = [t for _, t in S.markers if t > S.pos]
    if 0 < delta <= len(after):
        S.pos = after[delta - 1]


module("arrangement", getMarkerName=lambda i: S.markers[i][0] if i < len(S.markers) else "",
       jumpToMarker=jump_to_marker,
       addAutoTimeMarker=lambda t, name: (rec("arrangement.addAutoTimeMarker", t, name),
                                          S.markers.append((name, t)), S.markers.sort(key=lambda m: m[1]))[0])

# --- window, snap, recording options, channel loops (1.2 features) -----------------
S.focused, S.visible = None, set()
S.opts = dict(precount=False, loop_rec=False, step_edit=False, overdub=False)
S.snap = 8                                    # Snap_Step
S.chan_loops = {}                             # (pattern, channel) -> loop point


def global_transport(cmd, val, pme=0, flags=0):
    rec("transport.globalTransport", cmd, val)
    for fpt, opt in ((midi.FPT_CountDown, "precount"), (midi.FPT_LoopRecord, "loop_rec"), (midi.FPT_Overdub, "overdub")):
        if cmd == fpt:
            S.opts[opt] = not S.opts[opt]
    if cmd == midi.FPT_Metronome:
        S.metronome = not S.metronome


def find_empty_pattern(flags, x=-1, y=-1):
    rec("patterns.findFirstNextEmptyPat", flags)
    S.pattern = S.pattern_count = S.pattern_count + 1


_m["transport"].globalTransport = global_transport
_m["ui"].isPrecountEnabled = lambda: S.opts["precount"]
_m["ui"].isLoopRecEnabled = lambda: S.opts["loop_rec"]
_m["ui"].getStepEditMode = lambda: S.opts["step_edit"]
_m["ui"].setStepEditMode = lambda v: S.opts.__setitem__("step_edit", bool(v))
_m["ui"].getSnapMode = lambda: S.snap
_m["ui"].setSnapMode = lambda v: (rec("ui.setSnapMode", v), setattr(S, "snap", v))[0]
_m["ui"].showWindow = lambda w: (rec("ui.showWindow", w), S.visible.add(w))[0]
_m["ui"].hideWindow = lambda w: (rec("ui.hideWindow", w), S.visible.discard(w))[0]
_m["ui"].setFocused = lambda w: setattr(S, "focused", w)
_m["ui"].getVisible = lambda w: w in S.visible
_m["ui"].getFocused = lambda w: w == S.focused
_m["patterns"].findFirstNextEmptyPat = find_empty_pattern
_m["patterns"].getChannelLoopStyle = lambda pat, c: S.chan_loops.get((pat, c), 0)
_m["patterns"].setChannelLoop = lambda c, n: (rec("patterns.setChannelLoop", c, n),
                                               S.chan_loops.__setitem__((S.pattern, c), n))[0]


class Event:
    def __init__(self, status=0, d1=0, d2=0, sysex=None):
        self.status, self.data1, self.data2 = status, d1, d2
        self.sysex = sysex
        self.handled = False
        self.pmeFlags = midi.PME_System | midi.PME_System_Safe


sys.path.insert(0, HERE)
script = importlib.import_module("device_AkaiForce")
fp = importlib.import_module("force_protocol")
F = script.force


def dispatch(e):
    """Deliver an event the way FL does: OnMidiIn -> OnMidiMsg -> OnSysEx (sysex only)."""
    for cb in ("OnMidiIn", "OnMidiMsg"):
        if hasattr(script, cb) and not e.handled:
            getattr(script, cb)(e)
    if e.sysex and not e.handled and hasattr(script, "OnSysEx"):
        script.OnSysEx(e)
    return e


def send(status, d1, d2):
    return dispatch(Event(status, d1, d2))


def idle(n=3):
    for _ in range(n):
        F.last_refresh = 0
        script.OnIdle()


def pong():
    dispatch(Event(0xF0, sysex=bytes([0xF0, 0x47, 0x00, 0x40, 0x01, 0xF7])))


def texts():
    return {tuple(b[5:7]): b[9:-1].decode() for b in out_sysex if len(b) > 9 and b[4] == fp.MSG_TEXT}


# -------------------------------------------------------------------- checks
def run_checks():
    ok = 0

    def check(cond, what):
        nonlocal ok
        if not cond:
            raise AssertionError(what)
        ok += 1
        print("  ok  " + what)

    # Hard-coded from hardware photos (not derived from force_protocol, so a wrong helper can't hide):
    # a pad's note, colour CC and name slot all run row-major -- pad 2 of the top row is note 17,
    # colour CC 41 (screen: CC 25) and name slot (0, 17).
    check((fp.pad_note(1, 0), fp.pad_color_cc(1, 0), fp.tui_clip_color_cc(1, 0), fp.TXT_CLIP_NAME(1, 0))
          == (17, 41, 25, (0, 17)), "grid notes, colours and names share one row-major layout (hardware-verified)")

    # output port not linked yet: the Force's own pong broadcasts must not count as a connection
    S.assigned = False
    script.OnInit(); pong(); idle(); script.OnDeInit()
    check(not F.connected and not out_msgs, "no output port linked: stays disconnected, sends nothing, no errors")
    S.assigned = True
    script.OnInit()
    check(any(b == bytes(fp.sysex_ping()) for b in out_sysex), "OnInit sends a ping")
    pong(); idle()
    t = texts()
    check(F.connected, "pong from product 0x40 connects")
    check(t.get(fp.TXT_TRACK_NAME(0)) == "Insert 1", "track 1 name = mixer insert 1")
    check(t.get(fp.TXT_OLED_MIXER(0)) in ("PERFORM", "Insert 1"), "knob OLED 1 gets text")
    check((0x9D, fp.OLED_STYLE_MIXER, fp.OLED_UNIPOLAR) in out_msgs, "knob OLED style sent")
    check((0xBD, 0, round(0.8 * 127)) in out_msgs, "knob value feedback sent for OLED bar")
    check(t.get(fp.TXT_CLIP_NAME(0, 0)) == "Drums", "perform grid: clip name = playlist track")
    check(t.get(fp.TXT_TEMPO) == "140.00", "tempo shown")

    F.flash_until = time.time() - 1; idle()      # let the connect flash expire
    check(texts()[fp.TXT_OLED_MIXER(0)] == "Insert 1", "after the flash, knob OLED 1 shows the track name")

    # knob touch swaps OLED to dB
    send(0x9D, 0, 127); idle()
    check(texts()[fp.TXT_OLED_MIXER(0)] == "0.0 dB", "touching knob 1 shows volume in dB")
    send(0xBD, 0, 127); idle()          # one tick down
    check(calls[-1][0] == "mixer.setTrackVolume" and calls[-1][1][1] < 0.8, "knob 1 turn lowers insert 1 volume")
    send(0x9D, 0, 0); idle()
    check(texts()[fp.TXT_OLED_MIXER(0)] == "Insert 1", "releasing knob 1 restores the name")

    # perform: pad press with pressure stream triggers once, release sends TLC_Release
    calls.clear()
    for v in (40, 127, 90, 30):
        send(0x9C, fp.pad_note(1, 0), v)          # column 2, top row
    send(0x9C, fp.pad_note(1, 0), 0)
    trig = [c for c in calls if c[0] == "playlist.triggerLiveClip"]
    check(len(trig) == 2 and trig[0][1][:2] == (1, 1), "perform pad: one trigger despite pressure repeats")
    check(trig[1][1][2] & midi.TLC_Release, "perform pad release sends TLC_Release")
    idle()
    check(F.sent.get((0x9C, fp.pad_note(1, 0))) == fp.CLIP_PLAYING, "triggered clip shows as playing")

    # colour ordering + healing
    i_state = max(i for i, m in enumerate(out_msgs) if m[:2] == (0x9C, fp.pad_note(1, 0)))
    i_color = max(i for i, m in enumerate(out_msgs) if m[:2] == (0xBC, fp.pad_color_cc(1, 0)))
    check(i_color > i_state, "state change sends state first, then re-sends the colour")
    before = len(out_msgs)
    F.last_heal = 0; F.dirty = False; script.OnIdle()
    healed = out_msgs[before:]
    check(len(healed) >= 32 and any(m[0] == 0xBC for m in healed), "idle heal re-sends a full pad row (state + colour)")

    # perform layout matches FL's playlist: rows = playlist tracks, columns = blocks
    check(texts()[fp.TXT_SCENE_NAME(1)] == "Bass", "perform: row 2 is labelled with playlist track 2")
    calls.clear()
    send(0x9C, fp.pad_note(2, 3), 90); send(0x9C, fp.pad_note(2, 3), 0)
    check(calls[0] == ("playlist.triggerLiveClip", (4, 2, midi.TLC_MuteOthers | midi.TLC_Fill)),
          "perform: pad in column 3, row 4 launches block 3 of playlist track 4")
    send(0x9C, fp.PHYS_BUTTONS["solo"], 127)          # the row selector must not affect the right-hand buttons
    send(0x9C, fp.PHYS_SCENE_LAUNCH + 3, 127)
    check(("playlist.triggerLiveClip", (4, -1, midi.TLC_MuteOthers | midi.TLC_Fill)) in calls
          and not any(c[0] in ("playlist.soloTrack", "playlist.muteTrack") for c in calls),
          "perform: right-hand button 4 stops playlist track 4 (never mutes/solos)")
    send(0x9C, fp.PHYS_BUTTONS["shift"], 127); send(0x9C, fp.PHYS_SCENE_LAUNCH + 3, 127); send(0x9C, fp.PHYS_BUTTONS["shift"], 0)
    idle()
    check(("playlist.muteTrack", (4,)) in calls and F.sent[(0x9C, fp.PHYS_SCENE_LAUNCH + 3)] == fp.COLOR_1,
          "perform: SHIFT + right-hand button mutes the track and its button turns red")
    send(0x9C, fp.PHYS_BUTTONS["shift"], 127); send(0x9C, fp.PHYS_SCENE_LAUNCH + 3, 127); send(0x9C, fp.PHYS_BUTTONS["shift"], 0)
    send(0x9C, fp.PHYS_BUTTONS["clip_stop"], 127)
    send(0x9C, fp.PHYS_TRACK_ASSIGN + 2, 127)
    check(calls[-1][1][:2] == (1, 2) and calls[-1][1][2] & midi.TLC_ColumnMode,
          "perform: CLIP STOP row button 3 launches block column 3")
    send(0x9C, fp.PHYS_BUTTONS["mute"], 127)
    send(0x9C, fp.PHYS_BUTTONS["right"], 127)
    check(F.scene_ofs == 1 and F.track_ofs == 0, "perform: RIGHT scrolls blocks, not the mixer")
    send(0x9C, fp.PHYS_BUTTONS["down"], 127)
    check(F.perf_track_ofs == 1, "perform: DOWN scrolls playlist tracks")
    send(0x9C, fp.PHYS_BUTTONS["shift"], 127); send(0x9C, fp.PHYS_BUTTONS["right"], 127); send(0x9C, fp.PHYS_BUTTONS["shift"], 0)
    check(F.track_ofs == 1, "perform: SHIFT+RIGHT banks the mixer")
    send(0x9C, fp.PHYS_BUTTONS["shift"], 127); send(0x9C, fp.PHYS_BUTTONS["left"], 127); send(0x9C, fp.PHYS_BUTTONS["shift"], 0)
    send(0x9C, fp.PHYS_BUTTONS["left"], 127); send(0x9C, fp.PHYS_BUTTONS["up"], 127)

    S.perf = False
    calls.clear()
    send(0x9C, fp.pad_note(0, 0), 90); send(0x9C, fp.pad_note(0, 0), 0); idle()
    check(not any(c[0] == "playlist.triggerLiveClip" for c in calls) and texts()[fp.TXT_SCENE_NAME(0)] == "Turn on Perf Mode",
          "PERFORM with FL's Performance Mode off: no clip calls, the screen says so")
    S.perf = True
    idle()

    # mode switching
    send(0x9C, fp.PHYS_BUTTONS["launch"], 127); send(0x9C, fp.PHYS_BUTTONS["launch"], 0); idle()
    check(script.MODES[F.mode] == "PATTERNS", "LAUNCH cycles to PATTERNS")
    check(texts()[fp.TXT_OLED_MIXER(3)] == "PATTERNS", "mode name flashes on the knob OLEDs")
    send(0x9C, fp.pad_note(2, 0), 60); send(0x9C, fp.pad_note(2, 0), 0)
    check(("patterns.jumpToPattern", (3,)) in calls, "pattern pad 3 selects pattern 3")

    # STEPS: rows = channels, columns = steps; pads mirror the channel rack exactly
    S.grid.update({(6, 0): True, (6, 8): True})          # 'Lead' holds piano-roll notes...
    S.sp.update({(6, 0, 0): 72, (6, 8, 0): 65})           # ...at different pitches
    send(0x9C, fp.PHYS_BUTTONS["launch"], 127); idle()
    check(script.MODES[F.mode] == "STEPS", "LAUNCH cycles to STEPS")
    check(texts()[fp.TXT_SCENE_NAME(1)] == "Snare", "STEPS: row 2 is labelled with channel 2")
    check(texts()[fp.TXT_SCENE_NAME(6)] == "Lead (piano roll)" and F.sent[(0x9C, fp.pad_note(0, 6))] == fp.CLIP_EMPTY,
          "STEPS: a piano-roll channel's notes are not shown as steps (FL shows none either)")
    check(F.sent[(0x9C, fp.pad_note(4, 0))] == fp.CLIP_EMPTY and F.sent[(0xBC, fp.pad_color_cc(4, 0))] == 0,
          "STEPS: an off step stays dark, even on a beat")
    send(0x9C, fp.pad_note(2, 1), 100); send(0x9C, fp.pad_note(2, 1), 0); idle()
    check(S.grid.get((1, 2)) is True, "STEPS: tapping an off step turns it on")
    check(F.sent[(0xBC, fp.pad_color_cc(2, 1))] == F.color_of(COLORS[1]), "STEPS: an active step shows the channel colour")
    send(0x9C, fp.pad_note(2, 1), 100); send(0x9C, fp.pad_note(2, 1), 0)
    check(S.grid.get((1, 2)) is False, "STEPS: tapping an active step turns it off")
    send(0x9C, fp.pad_note(3, 1), 100); idle()
    check(texts()[fp.TXT_OLED_MIXER(0)] == "Pitch C5" and texts()[fp.TXT_OLED_MIXER(1)] == "Vel 100",
          "STEPS: holding a step shows its parameters on the knob OLEDs")
    send(0xBD, 1, 5)
    check(calls[-1] == ("channels.setStepParameterByIndex", (1, S.pattern, 3, 1, 105, True)),
          "STEPS: hold a step + turn knob 2 = that step's velocity")
    send(0x9C, fp.pad_note(3, 1), 0); idle()
    check(S.grid.get((1, 3)) is True and F.held_step is None and texts()[fp.TXT_OLED_MIXER(0)] != "Pitch C5",
          "STEPS: releasing keeps the step; the OLEDs go back to normal")
    send(0x9C, fp.pad_note(3, 1), 100); send(0xBD, 0, 2); send(0x9C, fp.pad_note(3, 1), 0)
    check(S.grid.get((1, 3)) is True and S.sp[(1, 3, 0)] == 62,
          "STEPS: editing an already-active step doesn't switch it off on release")
    send(0x9C, fp.PHYS_BUTTONS["right"], 127); idle()
    check(F.step_ofs == 8, "STEPS: RIGHT pages to steps 9-16")
    send(0x9C, fp.PHYS_BUTTONS["right"], 127)
    check(F.step_ofs == 8, "STEPS: paging stops at the pattern's real length (16 steps)")
    send(0x9C, fp.PHYS_BUTTONS["left"], 127)
    send(0x9C, fp.PHYS_SCENE_LAUNCH + 2, 127)
    check(S.sel_chan == 2, "STEPS: right-hand button 3 selects channel 3")
    send(0x9C, fp.pad_note(0, 2), 100); send(0x9C, fp.pad_note(0, 2), 0)
    send(0x9C, fp.PHYS_BUTTONS["shift"], 127); send(0x9C, fp.PHYS_BUTTONS["delete"], 127); send(0x9C, fp.PHYS_BUTTONS["shift"], 0)
    check(not any(v for (c, _), v in S.grid.items() if c == 2), "STEPS: SHIFT+DELETE clears the selected channel's steps")
    S.playing = True; idle()
    check(F.sent[(0xBC, fp.PHYS_TRACK_ASSIGN_COLOR + 5)] == fp.COLOR_ON and F.sent[(0xBC, fp.PHYS_TRACK_ASSIGN_COLOR + 4)] == 0,
          "STEPS: the playhead runs along the button row under the pads")
    S.playing = False
    send(0x9C, fp.PHYS_BUTTONS["copy"], 127)
    check(calls[-2] == ("patterns.clonePattern", ()), "COPY clones the current pattern")
    send(0x9A, fp.GLOBAL_BUTTONS["quantize"], 127)
    check(("channels.quickQuantize", (2,)) in calls, "on-screen QUANTIZE quantizes the selected channel")

    send(0x9C, fp.PHYS_BUTTONS["launch"], 127); idle()
    check(script.MODES[F.mode] == "KEYS", "LAUNCH cycles to KEYS")
    check(texts()[fp.TXT_SCENE_NAME(2)] == "Minor", "KEYS: right-hand column lists the scales")
    e = send(0x9C, fp.pad_note(0, 7), 77)        # bottom-left pad
    check(not e.handled and e.status == 0x90 and e.data1 == 36 and e.data2 == 77, "KEYS bottom-left pad plays C3 (36) with pad velocity")
    e2 = send(0x9C, fp.pad_note(0, 7), 127)
    check(e2.handled, "KEYS pressure repeat does not retrigger the note")
    send(0x9C, fp.pad_note(0, 7), 0)
    send(0x9C, fp.PHYS_SCENE_LAUNCH + 2, 127)    # Minor
    e = send(0x9C, fp.pad_note(1, 7), 90); send(0x9C, fp.pad_note(1, 7), 0)
    e2 = send(0x9C, fp.pad_note(0, 6), 90); send(0x9C, fp.pad_note(0, 6), 0)
    check(e.data1 == 38 and e2.data1 == 41, "KEYS in C minor: next pad = D, row above = F (3 scale degrees = a 4th)")
    send(0x9C, fp.PHYS_BUTTONS["shift"], 127); send(0x9C, fp.PHYS_BUTTONS["select"], 127); send(0x9C, fp.PHYS_BUTTONS["shift"], 0)
    send(0x9C, fp.pad_note(0, 7), 80)
    e2 = send(0x9C, fp.pad_note(0, 7), 110)
    check(F.aftertouch and not e2.handled and e2.status == 0xA0 and e2.data1 == 36 and e2.data2 == 110,
          "SHIFT+SELECT turns on pad pressure -> poly aftertouch")
    send(0x9C, fp.pad_note(0, 7), 0)
    send(0x9C, fp.PHYS_BUTTONS["shift"], 127); send(0x9C, fp.PHYS_BUTTONS["select"], 127); send(0x9C, fp.PHYS_BUTTONS["shift"], 0)
    send(0x9C, fp.PHYS_SCENE_LAUNCH + 0, 127)    # back to chromatic
    send(0x9C, fp.pad_note(0, 7), 77)
    send(0x9C, fp.PHYS_BUTTONS["launch"], 127)    # switch mode while holding
    e3 = send(0x9C, fp.pad_note(0, 7), 0)
    check(not e3.handled and e3.status == 0x80 and e3.data1 == 36, "note-off still sent after a mode switch (no stuck notes)")
    check(script.MODES[F.mode] == "DRUMS", "LAUNCH cycles to DRUMS")
    e = send(0x9C, fp.pad_note(4, 7), 100)
    check(e.data1 == 36 + 32, "DRUMS bottom-right quadrant starts at C3+32")
    send(0x9C, fp.pad_note(4, 7), 0)

    send(0x9C, fp.PHYS_BUTTONS["launch"], 127); idle()
    check(script.MODES[F.mode] == "CHANNELS", "LAUNCH cycles to CHANNELS")
    send(0x9C, fp.pad_note(1, 0), 90)
    check(calls[-1] == ("channels.midiNoteOn", (1, 60, 90)), "CHANNELS pad 2 triggers channel 2")
    send(0x9C, fp.pad_note(1, 0), 0)
    check(calls[-1] == ("channels.midiNoteOn", (1, 60, -127)), "CHANNELS release sends note-off")
    grey = F.sent[(0xBC, fp.pad_color_cc(1, 1))]          # channel 10 uses FL's default grey
    check(grey not in (0, script.C_DARK) and max(fp.PALETTE_RGB[grey - 8]) > 70,
          "CHANNELS: FL's default grey channel colour is brightened instead of looking unlit")

    # PLUGIN: 8 vertical faders for the selected channel's plugin
    S.sel_chan = 0
    send(0x9C, fp.PHYS_BUTTONS["launch"], 127); F.flash_until = time.time() - 1; idle()
    check(script.MODES[F.mode] == "PLUGIN", "LAUNCH cycles to PLUGIN")
    check(texts()[fp.TXT_CLIP_NAME(0, 7)] == "Macro 1" and texts()[fp.TXT_CLIP_NAME(1, 7)] == "Cutoff"
          and not any(F.param_list.count(p) for p in range(20, 30)),
          "PLUGIN: parameter names along the bottom, macros first, FL's MIDI CC slots skipped")
    send(0x9C, fp.pad_note(1, 0), 100); send(0x9C, fp.pad_note(1, 0), 0); idle()
    check(calls[-1] == ("plugins.setParamValue", (1.0, 0, 0)), "PLUGIN: top pad of column 2 sets parameter 2 to maximum")
    check(all(F.sent[(0x9C, fp.pad_note(1, r))] == fp.CLIP_STOPPED for r in range(8)), "PLUGIN: the whole column lights at maximum")
    send(0x9C, fp.pad_note(1, 5), 100); send(0x9C, fp.pad_note(1, 5), 0); idle()
    check(abs(S.param_vals[(0, 0)] - 2 / 7) < 1e-6 and F.sent[(0x9C, fp.pad_note(1, 4))] == fp.CLIP_EMPTY
          and F.sent[(0x9C, fp.pad_note(1, 5))] == fp.CLIP_STOPPED, "PLUGIN: a lower pad sets a lower value; the column lights up to it")
    send(0x9C, fp.PHYS_BUTTONS["down"], 127); idle()
    check(("plugins.nextPreset", (0, -1)) in calls and texts()[fp.TXT_OLED_MIXER(0)] == "BASS 1",
          "PLUGIN: DOWN loads the next preset and flashes its name")
    send(0x9C, fp.PHYS_BUTTONS["up"], 127)
    check(calls[-2] == ("plugins.prevPreset", (0, -1)) or ("plugins.prevPreset", (0, -1)) in calls, "PLUGIN: UP goes back a preset")
    send(0x9C, fp.PHYS_BUTTONS["select"], 127)
    check(("channels.showEditor", (0,)) in calls, "SELECT opens the plugin's window in FL")
    send(0x99, fp.DEVICE_BUTTONS["device_on"], 127)
    check(0 in S.ch_mute, "device on/off on an instrument mutes its channel")
    send(0x99, fp.DEVICE_BUTTONS["device_on"], 127)
    before = dict(S.param_vals)
    send(0x9C, fp.PHYS_BUTTONS["shift"], 127); send(0x9C, fp.PHYS_BUTTONS["delete"], 127); send(0x9C, fp.PHYS_BUTTONS["shift"], 0)
    changed = [k for k in S.param_vals if S.param_vals[k] != before.get(k, 0.5)]
    check(len(changed) >= 6, "PLUGIN: SHIFT+DELETE randomizes the 8 parameters")
    calls.clear()
    send(0x9C, fp.PHYS_BUTTONS["undo"], 127)
    check(all(S.param_vals[k] == before.get(k, 0.5) for k in changed) and ("general.undoUp", ()) not in calls,
          "PLUGIN: UNDO right after puts them back")
    send(0x9C, fp.PHYS_SCENE_LAUNCH + 1, 127); idle()
    check(F.param_bank == 1 and texts()[fp.TXT_CLIP_NAME(0, 7)] == "Mix", "PLUGIN: right-hand button 2 shows bank 2")
    send(0x9C, fp.PHYS_SCENE_LAUNCH + 0, 127)

    # SONG: one pad per bar; markers name and colour their sections
    S.pos = 500
    send(0x9C, fp.PHYS_BUTTONS["launch"], 127); idle()
    check(script.MODES[F.mode] == "SONG" and S.loop_mode == 1, "LAUNCH cycles to SONG (switches FL to song mode)")
    check(F.markers == [("Intro", 0), ("Verse", 1536), ("Drop", 3072)] and S.pos == 500,
          "SONG: marker positions mapped (incl. one at bar 1), playhead put back")
    check(texts()[fp.TXT_CLIP_NAME(0, 0)] == "Intro" and texts()[fp.TXT_CLIP_NAME(4, 0)] == "Verse"
          and texts()[fp.TXT_CLIP_NAME(5, 0)] == "6", "SONG: every bar is a pad; marker bars carry the marker name")
    check(F.sent[(0x9C, fp.pad_note(1, 0))] == fp.CLIP_PLAYING, "SONG: the current bar lights")
    check(F.sent[(0x9C, fp.pad_note(0, 2))] == fp.CLIP_EMPTY, "SONG: bars past the end of the song are dark")
    send(0x9C, fp.pad_note(0, 1), 90); send(0x9C, fp.pad_note(0, 1), 0); idle()
    check(S.pos == 3072 and F.sent[(0x9C, fp.pad_note(0, 1))] == fp.CLIP_PLAYING, "SONG: pad for bar 9 jumps there ('Drop') and lights")
    send(0xBA, 0, 126)                            # on-screen position encoder, two ticks back
    check(S.pos == 3072 - 2 * 96, "song-position encoder moves the playhead a beat per tick")
    saved_markers = S.markers
    S.markers = []
    send(0x9C, fp.PHYS_BUTTONS["launch"], 127); send(0x9C, fp.PHYS_BUTTONS["shift"], 127)
    send(0x9C, fp.PHYS_BUTTONS["launch"], 127); send(0x9C, fp.PHYS_BUTTONS["shift"], 0); idle()
    check(script.MODES[F.mode] == "SONG" and texts()[fp.TXT_CLIP_NAME(0, 0)] == "1"
          and F.sent[(0x9C, fp.pad_note(7, 1))] == fp.CLIP_STOPPED, "SONG works without any markers (bars only)")
    S.markers = saved_markers
    S.song_bars, S.playing, S.pos = 200, True, 100 * 384
    idle()
    check(F.song_ofs == 96, "SONG: the page follows the playhead during playback")
    S.song_bars, S.playing = 16, False

    send(0x9C, fp.PHYS_BUTTONS["shift"], 127); send(0x9C, fp.PHYS_BUTTONS["launch"], 127); send(0x9C, fp.PHYS_BUTTONS["shift"], 0)
    check(script.MODES[F.mode] == "PLUGIN", "SHIFT+LAUNCH goes back a mode")
    send(0x9C, fp.PHYS_BUTTONS["shift"], 127); send(0x9C, fp.PHYS_BUTTONS["launch"], 127); send(0x9C, fp.PHYS_BUTTONS["shift"], 0)

    # transport / buttons / touchscreen
    real_start = _m["transport"].start

    def unsafe_start():
        raise RuntimeError("Operation unsafe at current time")
    _m["transport"].start = unsafe_start
    e = send(0x9C, fp.PHYS_BUTTONS["play"], 127)
    check(e.handled and calls[-1][0] == "ui.setHintMsg", "an FL 'unsafe' error from a button is caught and shown as a hint")
    _m["transport"].start = real_start
    calls.clear()
    send(0x9C, fp.PHYS_BUTTONS["play"], 127); idle()
    check(("transport.start", ()) in calls and F.sent[(0x9C, fp.PHYS_BUTTONS["play"])] == 127, "PLAY starts and lights")
    send(0x9C, fp.PHYS_BUTTONS["undo"], 127)
    check(calls[-1][0] == "general.undoUp", "UNDO -> undo")
    send(0x9C, fp.PHYS_BUTTONS["solo"], 127); send(0x9C, fp.PHYS_TRACK_ASSIGN + 2, 127)
    check(("mixer.soloTrack", (3,)) in calls, "SOLO row mode: assign button 3 solos insert 3")
    send(0xB3, fp.STRIP_VOLUME_CC, 64)
    check(calls[-1] == ("mixer.setTrackVolume", (3, round(64 / 127, 4))), "on-screen fader 3 sets insert 3 volume")
    idle()
    check(F.sent[(0xB1, fp.NUM_SENDS_CC)] == 2, "sends: 'Reverb Bus' and 'Delay' inserts found as sends A and B")
    send(0xB1, fp.STRIP_SEND_CC + 0, 64); idle()
    check(("mixer.setRouteTo", (1, 20, True)) in calls and calls[-1][0] != "x" and S.routes[(1, 20)] == 64 / 127,
          "send A on strip 1 routes insert 1 to the reverb bus at that level")
    check(texts()[fp.TXT_SEND(0, 0)] == "63%" and texts()[fp.TXT_SEND(0, 1)] == "off", "send levels shown on screen")
    send(0x9C, fp.PHYS_BUTTONS["right"], 127); idle()
    check(texts()[fp.TXT_TRACK_NAME(0)] == "Insert 2", "RIGHT banks the mixer by one track")
    dispatch(Event(0xF0, sysex=bytes(fp.sysex_text(fp.TXT_TEMPO, "128.5"))))
    check(("general.processRECEvent", (midi.REC_Tempo, 128500, midi.REC_Control | midi.REC_UpdateControl)) in calls,
          "tempo typed on the Force sets FL tempo")

    # device page
    S.sel_chan = 0
    send(0xBD, fp.KNOB_DEVICE + 0, 5); idle()
    check(calls[-1][0] == "plugins.setParamValue" and calls[-1][1][1] == 12,
          "device knob 1 moves the plugin's Macro 1 (macros come first)")
    check(texts()[fp.TXT_DEVICE_NAME] == "Synth for Kick", "device name shown")
    F.flash_until = time.time() - 1; idle()
    check(texts()[fp.TXT_OLED_DEVICE(0)] == "Macro 1" and texts()[fp.TXT_OLED_DEVICE(1)] == "Cutoff",
          "device OLEDs show parameter names after the flash")
    S.sel_track = 1
    send(0x9C, fp.PHYS_BUTTONS["shift"], 127); send(0x99, fp.DEVICE_BUTTONS["next_device"], 127)
    send(0x9C, fp.PHYS_BUTTONS["shift"], 0); idle()
    check(F.fx_mode and texts()[fp.TXT_DEVICE_NAME] == "FX1 Fruity Reverb 2", "SHIFT+next device: device page follows the insert's FX chain")
    send(0x99, fp.DEVICE_BUTTONS["next_device"], 127); idle()
    check(texts()[fp.TXT_DEVICE_NAME] == "FX3 Fruity Delay 3", "next device skips empty FX slots")
    send(0xBD, fp.KNOB_DEVICE + 1, 3)
    check(calls[-1][0] == "plugins.setParamValue" and calls[-1][1][1:] == (0, 1), "device knob 2 moves param 2 of the FX plugin")
    send(0x99, fp.DEVICE_BUTTONS["device_on"], 127)
    pid = ((1 << 6) + 2) << 16
    check(S.ev.get(pid + midi.REC_Plug_Mute) == 0, "device on/off bypasses the effect")
    send(0x99, fp.DEVICE_BUTTONS["device_on"], 127)
    check(S.ev.get(pid + midi.REC_Plug_Mute) == 1 << 30, "pressing it again turns the effect back on")
    send(0x9C, fp.PHYS_BUTTONS["shift"], 127); send(0x99, fp.DEVICE_BUTTONS["prev_device"], 127)
    send(0x9C, fp.PHYS_BUTTONS["shift"], 0); idle()
    check(not F.fx_mode and texts()[fp.TXT_DEVICE_NAME].startswith("Synth for"), "SHIFT+prev device: back to the channel's plugin")

    # FL sometimes refuses calls ("Operation unsafe at current time"), e.g. while loading a project
    real = _m["plugins"].getPluginName
    def unsafe(*a, **k):
        raise RuntimeError("Operation unsafe at current time")
    _m["plugins"].getPluginName = unsafe
    F.dirty = True; F.last_refresh = 0; script.OnIdle()          # must not raise
    check(F.dirty, "refresh during an 'unsafe' moment is retried instead of erroring")
    _m["plugins"].getPluginName = real
    F.last_refresh = 0; F.dirty = True; idle()
    check(not F.dirty, "the retry succeeds once FL allows it again")

    # FL re-initialises the same script instance when MIDI settings change
    script.OnDeInit(); script.OnInit()
    check(not F.connected, "re-init drops the old connection")
    before = len(out_sysex)
    pong(); idle()
    check(F.connected and texts()[fp.TXT_TRACK_NAME(0)] == "Insert 2" and len(out_sysex) - before > 50,
          "re-init reconnects and resends the full screen state")

    # --- 1.2: ASSIGN A / B, on-screen transport buttons and their lights --------------------------
    B, G = fp.PHYS_BUTTONS, fp.GLOBAL_BUTTONS

    def press(ch, note_, shift=False):
        if shift:
            send(0x9C, B["shift"], 127)
        e = send(0x90 | ch, note_, 127)
        send(0x90 | ch, note_, 0)
        if shift:
            send(0x9C, B["shift"], 0)
        return e

    press(12, B["assign_a"])
    check(S.focused == midi.widMixer, "ASSIGN A (windows): first press opens the mixer")
    press(12, B["assign_a"])
    check(S.focused == midi.widChannelRack, "ASSIGN A: next press goes on to the channel rack")
    press(12, B["assign_a"], shift=True)
    check(S.focused == midi.widMixer, "SHIFT+ASSIGN A goes back a window")
    S.loop_mode = midi.SM_Pat
    press(12, B["assign_b"]); idle()
    check(S.loop_mode == midi.SM_Song and F.sent[(0x9C, B["assign_b"])] == fp.COLOR_ON,
          "ASSIGN B (song mode): switches to song mode and lights")
    press(12, B["assign_b"]); idle()
    check(S.loop_mode == midi.SM_Pat and F.sent[(0x9C, B["assign_b"])] == fp.COLOR_1, "ASSIGN B again: back to pattern mode, dim")

    press(10, G["overdub"])
    check(calls[-2] == ("transport.globalTransport", (midi.FPT_Overdub, 1)), "on-screen overdub toggles FL's overdub recording")
    press(10, G["overdub"], shift=True); idle()
    check(S.opts["loop_rec"], "SHIFT+overdub toggles loop recording")
    press(10, G["automation_arm"]); idle()
    check(S.opts["precount"] and F.sent[(0x9A, G["automation_arm"])] == 127, "automation arm = count-in, and it lights")
    press(10, G["follow"]); idle()
    check(not F.follow and F.sent[(0x9A, G["follow"])] == 0, "follow turns off and goes dark")
    press(10, G["follow"])
    S.tempo = 140.0
    press(10, G["nudge_up"])
    check(S.tempo == 141.0, "nudge + raises the tempo 1 BPM")
    press(10, G["nudge_down"], shift=True)
    check(abs(S.tempo - 140.9) < 1e-6, "SHIFT+nudge - lowers it 0.1 BPM")
    S.snap = midi.Snap_Step
    press(10, G["quantize_value"]); idle()
    check(S.snap == midi.Snap_HalfBeat and texts()[fp.TXT_OLED_MIXER(0)] == "SNAP 1/2 BEAT",
          "quantize value steps FL's snap (step -> 1/2 beat) and shows it")
    n_pat = S.pattern_count
    press(10, G["insert_scene"])
    check(S.pattern == n_pat + 1 and calls[-2][0] == "patterns.findFirstNextEmptyPat", "insert scene makes a new empty pattern")
    S.pos, n_markers = 3 * 384, len(S.markers)
    press(10, G["insert_scene"], shift=True)
    check(len(S.markers) == n_markers + 1 and ("Bar 4", 3 * 384) in S.markers, "SHIFT+insert scene adds a marker at the playhead")
    S.markers.remove(("Bar 4", 3 * 384))
    S.playing = S.recording = False
    press(10, G["arrangement_record"]); idle()
    check(S.recording and S.playing and S.loop_mode == midi.SM_Song and F.sent[(0x9A, G["arrangement_record"])] == 127,
          "arrangement record: song mode, recording, playing, lit")
    press(10, G["arrangement_record"])
    check(not S.recording, "arrangement record again stops recording")
    S.pos = 0; F.last_refresh = 0; script.OnIdle()
    check(F.sent[(0x9C, B["tap_tempo"])] == fp.COLOR_ON, "TAP TEMPO lights on the beat while playing")
    S.pos = 50; script.OnIdle()
    check(F.sent[(0x9C, B["tap_tempo"])] == fp.COLOR_1, "...and dims between beats")
    S.playing = False
    F.set_mode(script.MODES.index("PLUGIN"))

    # --- device lock ---
    S.sel_chan, F.fx_mode = 0, False
    press(10, G["device_lock"])
    S.sel_chan = 3; idle()
    check(texts()[fp.TXT_DEVICE_NAME] == "Synth for Kick" and F.sent[(0x9A, G["device_lock"])] == 127,
          "device lock: the device page stays on the locked plugin when another channel is selected")
    press(10, G["device_lock"]); idle()
    check(texts()[fp.TXT_DEVICE_NAME] == "Synth for Clap", "unlocking follows the selected channel again")

    # --- your own parameter pages (force_plugin_maps.py) ---
    script.PLUGIN_MAPS = {"synth for clap": [("Filter", ["cutoff", "Resonance", "No such knob", 6])]}
    F.param_cache_key = None; F.flash_until = time.time() - 1; idle()
    t = texts()
    check(t[fp.TXT_DEVICE_BANK].startswith("Filter 1/") and t[fp.TXT_OLED_DEVICE(0)] == "Cutoff"
          and t[fp.TXT_OLED_DEVICE(3)] == "Drive" and t[fp.TXT_OLED_DEVICE(2)] == "",
          "plugin map: your page first, parameters by name or index, a missing one leaves its knob empty")
    check(t[fp.TXT_CLIP_NAME(0, 7)] == "Cutoff" and t[fp.TXT_SCENE_NAME(0)] == "Filter" and t[fp.TXT_SCENE_NAME(1)] == "Bank 2",
          "plugin map: PLUGIN mode shows the page name; automatic banks follow it")
    calls.clear()
    send(0xBD, fp.KNOB_DEVICE + 2, 5)
    check(not calls, "plugin map: an empty knob does nothing")
    send(0xBD, fp.KNOB_DEVICE + 3, 5)
    check(calls[-1][0] == "plugins.setParamValue" and calls[-1][1][1] == 6, "plugin map: knob 4 moves parameter index 6")
    printed = []
    script.print = lambda *a: printed.append(" ".join(map(str, a)))
    press(12, B["copy"], shift=True)
    del script.print
    check(printed and printed[0].startswith("    'Synth for Clap': [") and "'Macro 1'" in printed[0],
          "PLUGIN: SHIFT+COPY prints the parameter list to paste into force_plugin_maps.py")
    script.PLUGIN_MAPS = {}
    F.param_cache_key = None

    # --- STEPS extras ---
    F.set_mode(script.MODES.index("STEPS")); F.step_ofs = F.step_chan_ofs = 0
    for k in list(S.grid):
        if k[0] in (0, 1):
            del S.grid[k]
    send(0x9C, fp.pad_note(1, 0), 120); send(0x9C, fp.pad_note(1, 0), 0)
    check(S.grid.get((0, 1)) and S.sp[(0, 1, midi.pVelocity)] == 120, "STEPS: a new step takes the pad's velocity (accent)")
    send(0x9C, fp.pad_note(3, 0), 90); send(0x9C, fp.pad_note(6, 0), 80); send(0x9C, fp.pad_note(6, 0), 0)
    send(0x9C, fp.pad_note(3, 0), 0)
    check(all(S.grid.get((0, st)) for st in range(3, 7)), "STEPS: hold a step + tap another in the row fills the steps between")
    S.sp[(0, 3, midi.pPitch)] = 67
    send(0x9C, fp.PHYS_SCENE_LAUNCH + 0, 127); send(0x9C, fp.PHYS_SCENE_LAUNCH + 1, 127)
    send(0x9C, fp.PHYS_SCENE_LAUNCH + 1, 0); send(0x9C, fp.PHYS_SCENE_LAUNCH + 0, 0)
    check(all(bool(S.grid.get((1, st))) == bool(S.grid.get((0, st))) for st in range(16)) and S.sp[(1, 3, midi.pPitch)] == 67,
          "STEPS: hold channel button 1 + press button 2 copies the steps (with pitch etc.)")
    check(F.held_chan is None and S.sel_chan == 0, "STEPS: releasing the buttons ends the copy; the first one selected its channel")
    calls.clear()
    send(0x9C, fp.PHYS_SCENE_LAUNCH + 2, 127); send(0x9C, fp.pad_note(3, 2), 100); send(0x9C, fp.pad_note(3, 2), 0)
    send(0x9C, fp.PHYS_SCENE_LAUNCH + 2, 0)
    check(not any(c[0] == "patterns.setChannelLoop" for c in calls) and S.grid.get((2, 3)),
          "STEPS: channel loops are off by default (the pad just toggles its step)")
    script.STEPS_CHANNEL_LOOP = True
    send(0x9C, fp.PHYS_SCENE_LAUNCH + 2, 127); send(0x9C, fp.pad_note(3, 2), 100); send(0x9C, fp.pad_note(3, 2), 0)
    loops = [c for c in calls if c[0] == "patterns.setChannelLoop"]
    check(loops == [("patterns.setChannelLoop", (2, 4))], "STEPS_CHANNEL_LOOP: hold a channel button + tap step 4 = loop it at 4 steps")
    send(0x9C, fp.pad_note(3, 2), 100); send(0x9C, fp.pad_note(3, 2), 0); send(0x9C, fp.PHYS_SCENE_LAUNCH + 2, 0)
    check([c for c in calls if c[0] == "patterns.setChannelLoop"][-1] == ("patterns.setChannelLoop", (2, 0)), "...the same step again removes the loop")
    script.STEPS_CHANNEL_LOOP = False
    S.playing = True
    _m["mixer"].getSongStepPos = lambda: 12
    idle()
    check(F.step_ofs == 8, "STEPS + follow: the step page follows the playhead")
    _m["mixer"].getSongStepPos = lambda: 5
    S.playing = False

    # --- PATTERNS: queue the next pattern for the next bar ---
    F.set_mode(script.MODES.index("PATTERNS")); F.pattern_ofs = 0
    S.pattern, S.playing, S.loop_mode, S.pos = 1, True, midi.SM_Pat, 100
    send(0x9C, fp.pad_note(4, 0), 100); send(0x9C, fp.pad_note(4, 0), 0); idle()
    check(S.pattern == 1 and F.sent[(0x9C, fp.pad_note(4, 0))] == fp.CLIP_TRIGGERED,
          "PATTERNS while playing: the pad queues pattern 5 (blinking) instead of switching mid-bar")
    S.pos = 300; idle()
    check(S.pattern == 1, "...still waiting in the same bar")
    S.pos = 384 + 5; idle()
    check(S.pattern == 5 and F.sent[(0x9C, fp.pad_note(4, 0))] == fp.CLIP_PLAYING, "...switches at the next bar")
    send(0x9C, fp.pad_note(1, 0), 100); send(0x9C, fp.pad_note(1, 0), 0)
    S.pos = 10; idle()
    check(S.pattern == 2, "...or when the pattern loops back to its start")
    send(0x9C, fp.PHYS_BUTTONS["shift"], 127); send(0x9C, fp.pad_note(2, 0), 100); send(0x9C, fp.pad_note(2, 0), 0)
    send(0x9C, fp.PHYS_BUTTONS["shift"], 0)
    check(S.pattern == 3 and F.queued is None, "SHIFT+pad switches right away")
    S.playing = False
    send(0x9C, fp.pad_note(3, 0), 100); send(0x9C, fp.pad_note(3, 0), 0)
    check(S.pattern == 4, "stopped: the pad switches right away")

    # meters + disconnect
    script.OnUpdateMeters()
    check(any(s == 0xB1 and d1 == fp.STRIP_METER_L_CC for s, d1, _ in out_msgs), "meters sent while playing")
    F.last_pong -= 10; F.last_ping = 0; script.OnIdle()
    check(not F.connected, "missing pongs -> disconnected")
    print("\n%d checks passed" % ok)


def run_live(seconds):
    global live_out
    import mido
    name_in = next(n for n in mido.get_input_names() if "DAW Control" in n)
    name_out = next(n for n in mido.get_output_names() if "DAW Control" in n)
    with mido.open_input(name_in) as inp, mido.open_output(name_out) as live_out_:
        live_out = live_out_
        script.OnInit()
        t0 = last_meter = time.time()
        print("running the FL script against the real Force (fake FL project). Ctrl+C to stop.")
        n_hints = 0
        while seconds <= 0 or time.time() - t0 < seconds:
            for m in inp.iter_pending():
                if m.type == "sysex":
                    dispatch(Event(0xF0, sysex=bytes(m.bytes())))
                else:
                    b = m.bytes()
                    if len(b) == 3:
                        e = dispatch(Event(b[0], b[1], b[2]))
                        if not e.handled:
                            print("  -> FL would play: %02X %d %d" % (e.status, e.data1, e.data2), flush=True)
            script.OnIdle()
            if time.time() - last_meter > 0.05:
                script.OnUpdateMeters()
                last_meter = time.time()
            hints = [c for c in calls if c[0] != "ui.setHintMsg" or True]
            for c in hints[n_hints:]:
                print("  FL:", c[0], *c[1], flush=True)
            n_hints = len(hints)
            time.sleep(0.005)


if __name__ == "__main__":
    if "--live" in sys.argv:
        secs = float(sys.argv[sys.argv.index("--live") + 1]) if len(sys.argv) > sys.argv.index("--live") + 1 else 0
        try:
            run_live(secs)
        except KeyboardInterrupt:
            pass
    else:
        run_checks()
