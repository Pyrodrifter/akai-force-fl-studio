"""
force_probe.py - talk to an Akai Force in Live Control mode without Ableton.

  python force_probe.py            # handshake + log everything the Force sends
  python force_probe.py --demo     # also push a fake 8x8 session to the Force

Needs: pip install mido python-rtmidi
Close Ableton and FL Studio first (or at least make sure neither has the
"Akai Network - DAW Control" port open).
"""
import argparse
import json
import math
import sys
import time

import mido

import force_protocol as fp


def find_port(names, needle):
    for n in names:
        if needle.lower() in n.lower():
            return n
    sys.exit("No MIDI port containing %r. Available: %s" % (needle, names))


class Probe:
    def __init__(self, inp, out, demo, log_path):
        self.inp, self.out, self.demo = inp, out, demo
        self.log = open(log_path, "a", encoding="utf-8") if log_path else None
        self.t0 = time.time()
        self.connected = False
        self.last_ping = 0.0
        self.last_pong = 0.0
        self.volume = [100] * 8
        self.clip_state = {}
        self.playing = False

    # ---- output helpers -------------------------------------------------
    def note(self, ch, n, v):
        self.out.send(mido.Message("note_on", channel=ch, note=n, velocity=v))

    def cc(self, ch, n, v):
        self.out.send(mido.Message("control_change", channel=ch, control=n, value=v))

    def text(self, slot, s):
        self.out.send(mido.Message("sysex", data=fp.sysex_text(slot, s)[1:-1]))

    def ping(self):
        self.out.send(mido.Message("sysex", data=fp.sysex_ping()[1:-1]))
        self.last_ping = time.time()

    # ---- demo layout ----------------------------------------------------
    def push_demo(self):
        self.cc(fp.NUM_SENDS_CH, fp.NUM_SENDS_CC, 2)
        for t in range(8):
            col = fp.palette(t * 9)
            self.note(0, fp.TUI_TRACK_TYPE + t, fp.TRACK_MELODIC)
            self.text(fp.TXT_TRACK_NAME(t), "FL Track %d" % (t + 1))
            self.text(fp.TXT_OLED_MIXER(t), "FL Track %d" % (t + 1))
            self.note(fp.CH_KNOBS, fp.OLED_STYLE_MIXER + t, fp.OLED_UNIPOLAR)
            self.cc(0, fp.TUI_TRACK_COLOR_CC + t, col)
            self.cc(fp.CH_PHYS, fp.PHYS_TRACK_SELECT_COLOR + t, col)
            self.cc(fp.CH_PHYS, fp.PHYS_TRACK_ASSIGN_COLOR + t, fp.COLOR_1)
            self.set_volume(t, self.volume[t])
            self.cc(t + 1, fp.STRIP_PAN_CC, 64)
            self.text(fp.TXT_PAN(t), "C")
            for s in range(8):
                c = fp.palette(t * 9 + s)
                self.cc(0, fp.tui_clip_color_cc(t, s), c)
                self.cc(fp.CH_PHYS, fp.pad_color_cc(t, s), c)
                self.set_clip(t, s, fp.CLIP_STOPPED)
                self.text(fp.TXT_CLIP_NAME(t, s), "Pat %d-%d" % (t + 1, s + 1))
        for s in range(8):
            self.text(fp.TXT_SCENE_NAME(s), "Scene %d" % (s + 1))
            self.cc(0, fp.TUI_SCENE_COLOR_CC + s, fp.palette(40 + s))
        self.text(fp.TXT_TEMPO, "140.00")
        self.text(fp.TXT_SONG_POSITION, "1:1:1")
        self.text(fp.TXT_DEVICE_NAME, "FL Studio")
        self.text(fp.TXT_DEVICE_BANK, "Demo bank")
        for i in range(8):
            self.text(fp.TXT_PARAM_NAME(i), "Param %d" % (i + 1))
            self.text(fp.TXT_PARAM_VALUE(i), "%d%%" % (i * 12))
            self.cc(fp.CH_DEVICE, fp.DEVICE_PARAM_CC + i, i * 16)
        self.note(fp.CH_PHYS, fp.PHYS_BUTTONS["play"], 0)
        self.say("demo layout pushed")

    def set_volume(self, t, v):
        self.volume[t] = max(0, min(127, v))
        self.cc(t + 1, fp.STRIP_VOLUME_CC, self.volume[t])
        self.text(fp.TXT_VOLUME(t), "%d" % self.volume[t])

    def set_clip(self, t, s, state):
        self.clip_state[(t, s)] = state
        self.note(0, fp.tui_clip_note(t, s), state)
        self.note(fp.CH_PHYS, fp.pad_note(t, s), state)

    def animate(self):
        now = time.time() - self.t0
        for t in range(8):
            level = int(63 + 63 * math.sin(now * 2.0 + t * 0.7)) if self.playing else 0
            self.cc(t + 1, fp.STRIP_METER_L_CC, level)
            self.cc(t + 1, fp.STRIP_METER_R_CC, max(0, level - 6))

    # ---- input ----------------------------------------------------------
    def say(self, s):
        print("%8.2fs  %s" % (time.time() - self.t0, s), flush=True)

    def record(self, entry):
        if self.log:
            entry["t"] = round(time.time() - self.t0, 3)
            self.log.write(json.dumps(entry) + "\n")
            self.log.flush()

    def handle(self, msg):
        if msg.type == "sysex":
            data = [0xF0] + list(msg.data) + [0xF7]
            parsed = fp.parse_sysex(data)
            if parsed[0] == "pong":
                self.last_pong = time.time()
                if not self.connected:
                    self.connected = True
                    self.say("<- PONG from product 0x%02X (%s) - connected" % (
                        parsed[1], "Force" if parsed[1] == fp.FORCE else "MPC"))
                    if self.demo:
                        self.push_demo()
                return
            if parsed[0] == "text":
                self.say("<- text slot %s: %r" % (parsed[1], parsed[2]))
                self.record({"kind": "text", "slot": list(parsed[1]), "text": parsed[2]})
                if tuple(parsed[1]) == fp.TXT_TEMPO and self.demo:
                    self.text(fp.TXT_TEMPO, parsed[2])
                return
            self.say("<- sysex " + " ".join("%02X" % b for b in data))
            self.record({"kind": "sysex", "hex": msg.hex()})
            return

        raw = msg.bytes()
        if len(raw) < 3:
            self.say("<- %s" % msg)
            return
        status, d1, d2 = raw[0], raw[1], raw[2]
        name = fp.describe(status, d1)
        kind = {0x80: "off", 0x90: "on", 0xB0: "cc"}.get(status & 0xF0, "?")
        if kind == "on" and d2 == 0:
            kind = "off"
        extra = ""
        if name.startswith("knob_"):
            extra = "  delta=%+d" % fp.relative(d2)
        self.say("<- %-22s %-3s %3d   [%02X %02X %02X]%s" % (name, kind, d2, status, d1, d2, extra))
        self.record({"kind": kind, "name": name, "status": status, "d1": d1, "d2": d2})
        if self.demo:
            self.react(status & 0x0F, kind, d1, d2, name)

    def react(self, ch, kind, d1, d2, name):
        """Minimal two-way behaviour so the demo feels alive."""
        if kind == "on" and name.startswith(("pad_t", "tui_clip_t")):
            t, s = (int(x) - 1 for x in name.split("_t")[1].split("_s"))
            new = fp.CLIP_STOPPED if self.clip_state.get((t, s)) == fp.CLIP_PLAYING else fp.CLIP_PLAYING
            self.set_clip(t, s, new)
        elif kind == "on" and name == "play":
            self.playing = True
            self.note(fp.CH_PHYS, fp.PHYS_BUTTONS["play"], fp.COLOR_ON)
        elif kind == "on" and name == "stop":
            self.playing = False
            self.note(fp.CH_PHYS, fp.PHYS_BUTTONS["play"], 0)
        elif kind == "cc" and name.startswith("knob_mixer_"):
            t = int(name.rsplit("_", 1)[1]) - 1
            self.set_volume(t, self.volume[t] + fp.relative(d2))
        elif kind == "cc" and name.startswith("tui_volume_"):
            t = int(name.rsplit("_", 1)[1]) - 1
            self.set_volume(t, d2)

    # ---- main loop ------------------------------------------------------
    def run(self, seconds):
        self.say("pinging... (Ctrl+C to quit)")
        last_anim = 0.0
        while seconds <= 0 or time.time() - self.t0 < seconds:
            now = time.time()
            if now - self.last_ping > 1.5:
                if self.connected and now - self.last_pong > fp.PING_PERIOD + 1.5:
                    self.connected = False
                    self.say("!! pong timeout - Force disconnected")
                self.ping()
            for msg in self.inp.iter_pending():
                self.handle(msg)
            if self.demo and self.connected and now - last_anim > 0.08:
                self.animate()
                last_anim = now
            time.sleep(0.002)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true", help="push a demo session layout and react to input")
    ap.add_argument("--port", default="DAW Control", help="substring of the MIDI port name")
    ap.add_argument("--seconds", type=float, default=0, help="stop after N seconds (0 = run forever)")
    ap.add_argument("--log", default="force_log.jsonl", help="JSONL log of everything received ('' to disable)")
    a = ap.parse_args()
    in_name = find_port(mido.get_input_names(), a.port)
    out_name = find_port(mido.get_output_names(), a.port)
    print("in : %s\nout: %s" % (in_name, out_name))
    with mido.open_input(in_name) as inp, mido.open_output(out_name) as out:
        try:
            Probe(inp, out, a.demo, a.log or None).run(a.seconds)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
