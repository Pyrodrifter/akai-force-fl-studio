"""
Builds the user manual:  docs/manual.html  ->  docs/Akai-Force-FL-Studio-Manual.pdf

    python docs/build_manual.py

Needs Google Chrome or Microsoft Edge (used headless to print the PDF).
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

VERSION = re.search(r'^VERSION = "(.+)"', open(os.path.join(ROOT, "device_AkaiForce.py"), encoding="utf-8").read(), re.M).group(1)
REPO = "github.com/Pyrodrifter/akai-force-fl-studio"
OUT_HTML = os.path.join(HERE, "manual.html")
OUT_PDF = os.path.join(HERE, "Akai-Force-FL-Studio-Manual.pdf")

# Colours roughly as the Force shows them (Live palette, doubled to 8-bit)
RED, ORANGE, YELLOW, MAGENTA, AMBER = "#fe3636", "#fea428", "#fef034", "#fe38d4", "#f66c02"
CYAN, PURPLE, GREEN, TEAL, BLUE = "#18e8fe", "#d86ce4", "#1afe2e", "#24fea8", "#10a4ee"
GREY, DARK, OFF, WHITE = "#7a7a7a", "#3c3c3c", "#1b1d21", "#f2f2f2"


# --------------------------------------------------------------------------- grid diagrams
def grid(cells, right=None, bottom=None, caption="", row_labels=None, col_labels=None, playing=()):
    """cells[s][t] = (bg, text). right/bottom = lists of (bg, text)."""
    h = ['<figure class="pads"><table class="grid">']
    if col_labels:
        h.append("<tr>" + ("<th></th>" if row_labels else "") +
                 "".join('<th class="cl">%s</th>' % c for c in col_labels) + ("<th></th>" if right else "") + "</tr>")
    for s, row in enumerate(cells):
        h.append("<tr>")
        if row_labels:
            h.append('<th class="rl">%s</th>' % row_labels[s])
        for t, (bg, txt) in enumerate(row):
            cls = "pad play" if (t, s) in playing else "pad"
            fg = "#111" if bg not in (OFF, DARK) else "#aaa"
            h.append('<td class="%s" style="background:%s;color:%s">%s</td>' % (cls, bg, fg, txt))
        if right:
            bg, txt = right[s]
            h.append('<td class="side" style="border-color:%s">%s</td>' % (bg, txt))
        h.append("</tr>")
    if bottom:
        h.append("<tr>" + ("<th></th>" if row_labels else "") +
                 "".join('<td class="under" style="border-color:%s">%s</td>' % b for b in bottom) + "</tr>")
    h.append("</table><figcaption>%s</figcaption></figure>" % caption)
    return "".join(h)


def note_name(n):
    return ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")[n % 12] + str(n // 12)


def diagrams():
    d = {}
    # PERFORM
    trk = [("Drums", RED), ("Bass", PURPLE), ("Chords", BLUE), ("Lead", CYAN),
           ("FX", TEAL), ("Vox", MAGENTA), ("Perc", ORANGE), ("Pad", GREEN)]
    clips = {0: (0, 1, 2, 3, 4, 5, 6, 7), 1: (0, 1, 2, 3, 6, 7), 2: (2, 3, 4, 5), 3: (4, 5, 6, 7),
             4: (3, 7), 5: (4, 5), 6: (0, 1, 4, 5), 7: (2, 3, 4, 5, 6, 7)}
    cells = [[(trk[s][1], "") if t in clips[s] else (OFF, "") for t in range(8)] for s in range(8)]
    d["perform"] = grid(cells, right=[(c, n) for n, c in trk], bottom=[(DARK, "&#9654;")] * 8,
                        col_labels=["Blk %d" % (i + 1) for i in range(8)], playing={(2, 0), (2, 1), (2, 2)},
                        caption="PERFORM: rows are playlist tracks, columns are Performance-Mode blocks. Pulsing = playing.")
    # PATTERNS
    pcols = [RED, ORANGE, YELLOW, GREEN, TEAL, CYAN, BLUE, PURPLE, MAGENTA, AMBER, GREY, GREEN]
    cells = [[((pcols[(s * 8 + t) % len(pcols)], str(s * 8 + t + 1)) if s * 8 + t < 12 else (OFF, str(s * 8 + t + 1)))
              for t in range(8)] for s in range(8)]
    d["patterns"] = grid(cells, right=[(DARK, "Pat %d-%d" % (s * 8 + 1, s * 8 + 8)) for s in range(8)],
                         playing={(3, 0)}, caption="PATTERNS: one pad per pattern. The current pattern pulses.")
    # STEPS
    chans = [("Kick", RED, "10001000"), ("Clap", ORANGE, "00001000"), ("Hat", YELLOW, "10101010"),
             ("Snare", MAGENTA, "00000010"), ("808", AMBER, "10000100"), ("Keys", CYAN, "00000000"),
             ("Sub", PURPLE, "10010010"), ("poly keys", GREEN, "--------")]
    cells = []
    for name, col, bits in chans:
        cells.append([(col, "") if b == "1" else (OFF, "") for b in bits])
    d["steps"] = grid(cells, right=[(c, n + (" (piano roll)" if b[0] == "-" else "")) for n, c, b in chans],
                      bottom=[(WHITE if i == 4 else DARK, "&#9679;" if i == 4 else "") for i in range(8)],
                      col_labels=[str(i + 1) for i in range(8)],
                      caption="STEPS: rows are channels, columns are steps. Lit = step on. "
                              "The button row under the pads shows the playhead.")
    # KEYS (chromatic, C3 bottom-left)
    cells = []
    for s in range(8):
        row = []
        for t in range(8):
            n = 36 + (7 - s) * 5 + t
            deg = n % 12
            bg = BLUE if deg == 0 else (GREY if deg in (0, 2, 4, 5, 7, 9, 11) else DARK)
            row.append((bg, note_name(n)))
        cells.append(row)
    scales = ["Chromatic", "Major", "Minor", "Dorian", "Mixolydian", "Harm minor", "Maj pent", "Min pent"]
    d["keys"] = grid(cells, right=[(WHITE if i == 0 else DARK, n) for i, n in enumerate(scales)],
                     caption="KEYS (Chromatic): rows are a 4th apart, bottom-left is C3. Root notes in blue. "
                             "The right-hand buttons choose the scale.")
    # DRUMS
    qcols = [ORANGE, TEAL, MAGENTA, CYAN]
    cells = []
    for s in range(8):
        r = 7 - s
        row = []
        for t in range(8):
            quad = (1 if t >= 4 else 0) * 2 + (1 if r >= 4 else 0)
            n = 36 + quad * 16 + (r % 4) * 4 + (t % 4)
            row.append((qcols[quad], note_name(n)))
        cells.append(row)
    d["drums"] = grid(cells, caption="DRUMS: four 4x4 banks of 16 notes. Bottom-left bank starts at C3 (MIDI 36), "
                                     "the standard FPC layout.")
    # CHANNELS
    names = ["Kick", "Clap", "Hat", "Snare", "808", "Keys", "Sub", "Poly", "Pig 2", "Space", "Base", "Sub 2", "Pig 4", "Pig 5"]
    cc = [RED, ORANGE, YELLOW, MAGENTA, AMBER, CYAN, PURPLE, GREEN, TEAL, BLUE, "#92a6fe", "#8872e4", "#befa00", "#86fe66"]
    cells = [[(cc[s * 8 + t], names[s * 8 + t]) if s * 8 + t < len(names) else (OFF, "") for t in range(8)]
             for s in range(8)]
    d["channels"] = grid(cells, playing={(0, 0)},
                         caption="CHANNELS: one pad per channel-rack channel. Tap to play, SHIFT+tap to select.")
    # SONG
    sections = [(0, "Intro", TEAL), (8, "Verse", BLUE), (24, "Drop", RED), (40, "Break", PURPLE), (48, "Drop 2", ORANGE)]
    cells = []
    for s in range(8):
        row = []
        for t in range(8):
            bar = s * 8 + t
            if bar >= 56:
                row.append((OFF, ""))
                continue
            sec = [x for x in sections if x[0] <= bar][-1]
            row.append((sec[2], sec[1] if sec[0] == bar else str(bar + 1)))
        cells.append(row)
    # PLUGIN: 8 vertical faders
    levels = [8, 5, 3, 6, 2, 7, 4, 1]
    pnames = ["Macro 1", "Macro 2", "Cutoff", "Reso", "Attack", "Release", "Drive", "Mix"]
    pvals = ["100%", "57%", "29%", "71%", "14%", "86%", "43%", "0%"]
    cells = []
    for s in range(8):
        r = 7 - s
        row = []
        for t in range(8):
            lit = r < levels[t]
            txt = pnames[t] if s == 7 else (pvals[t] if s == 0 else "")
            row.append((PURPLE if lit else OFF, txt))
        cells.append(row)
    d["plugin"] = grid(cells, right=[(WHITE if i == 0 else DARK, "Bank %d" % (i + 1)) for i in range(8)],
                       caption="PLUGIN: each column is one parameter of the current bank; the lit height is its value. "
                               "Names along the bottom, values along the top.")
    d["song"] = grid(cells, right=[(DARK, "Bars %d-%d" % (s * 8 + 1, s * 8 + 8)) for s in range(8)], playing={(3, 3)},
                     caption="SONG: one pad per bar. Marker sections take the marker's colour; the current bar pulses.")
    return d


# --------------------------------------------------------------------------- force control map (schematic)
FORCE_SVG = """
<svg viewBox="0 0 760 520" class="map" xmlns="http://www.w3.org/2000/svg" font-family="Segoe UI, Arial" font-size="12">
  <rect x="0" y="0" width="760" height="520" rx="16" fill="#15171b"/>
  <rect x="200" y="20" width="360" height="130" rx="6" fill="#2b3a4a" stroke="#6aa" />
  <text x="380" y="80" fill="#cde" text-anchor="middle" font-size="14">Touchscreen</text>
  <text x="380" y="100" fill="#9ab" text-anchor="middle">clip grid &#183; mixer &#183; device pages</text>
  <g fill="#ddd">%OLEDS%</g>
  <text x="380" y="222" fill="#9ab" text-anchor="middle">8 knobs with OLED screens (mixer volume / device params / step edit)</text>
  <g>%TOPROW%</g>
  <text x="380" y="252" fill="#9ab" text-anchor="middle" font-size="11">track select row</text>
  <g>%PADS%</g>
  <g>%SCENES%</g>
  <text x="648" y="300" fill="#9ab" font-size="11" transform="rotate(90 648 300)">row buttons</text>
  <g>%BOTTOM%</g>
  <text x="380" y="512" fill="#9ab" text-anchor="middle" font-size="11">lower row (MUTE / SOLO / REC ARM / CLIP STOP functions)</text>
  <g font-size="11" fill="#f0a030">
    <text x="20" y="40">MENU</text>
    <text x="20" y="70" fill="#3c3">PLAY</text><text x="70" y="70">STOP</text><text x="120" y="70" fill="#f55">REC</text>
    <text x="20" y="100">UNDO</text><text x="70" y="100">TAP TEMPO</text>
    <text x="20" y="130">SHIFT</text><text x="70" y="130">LAUNCH</text>
    <text x="20" y="160">COPY</text><text x="70" y="160">DELETE</text><text x="130" y="160">SELECT</text>
    <text x="20" y="190">MUTE SOLO REC ARM CLIP STOP</text>
    <text x="20" y="220">MASTER</text><text x="80" y="220">STOP ALL</text>
    <text x="60" y="300" font-size="18">&#9650;</text><text x="30" y="325" font-size="18">&#9664;</text>
    <text x="90" y="325" font-size="18">&#9654;</text><text x="60" y="350" font-size="18">&#9660;</text>
  </g>
  <text x="20" y="380" fill="#9ab" font-size="11">schematic, not to scale</text>
  <g font-size="12" font-weight="700" text-anchor="middle">%BADGES%</g>
</svg>"""


def force_svg():
    oleds = "".join('<rect x="%d" y="165" width="40" height="14" rx="2"/><circle cx="%d" cy="198" r="10" fill="#333" stroke="#777"/>'
                    % (205 + i * 45, 225 + i * 45) for i in range(8))
    top = "".join('<rect x="%d" y="232" width="40" height="8" rx="2" fill="#555"/>' % (205 + i * 45) for i in range(8))
    pads = "".join('<rect x="%d" y="%d" width="40" height="26" rx="3" fill="#8a8a8a"/>' % (205 + t * 45, 262 + s * 30)
                   for s in range(8) for t in range(8))
    scenes = "".join('<rect x="570" y="%d" width="40" height="26" rx="3" fill="#555"/>' % (262 + s * 30) for s in range(8))
    bottom = "".join('<rect x="%d" y="%d" width="40" height="10" rx="2" fill="#555"/>' % (205 + i * 45, 505 - 14) for i in range(8))
    spots = [(1, 575, 35), (2, 190, 172), (3, 190, 198), (4, 190, 236), (5, 190, 330), (6, 632, 262),
             (7, 190, 496), (8, 170, 62), (9, 125, 322), (10, 160, 122), (11, 165, 187)]
    badges = "".join('<circle cx="%d" cy="%d" r="10" fill="#f0a030"/><text x="%d" y="%d" fill="#111">%d</text>'
                     % (x, y, x, y + 4, n) for n, x, y in spots)
    return (FORCE_SVG.replace("%BADGES%", badges).replace("%OLEDS%", oleds).replace("%TOPROW%", top).replace("%PADS%", pads)
            .replace("%SCENES%", scenes).replace("%BOTTOM%", bottom))


# --------------------------------------------------------------------------- page
CSS = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm;
        @bottom-center { content: counter(page); font: 9pt 'Segoe UI', Arial; color: #888; } }
@page :first { margin: 0; @bottom-center { content: none; } }
* { box-sizing: border-box; }
body { font: 10.3pt/1.5 'Segoe UI', Arial, sans-serif; color: #1c1e22; margin: 0; }
h1 { font-size: 21pt; margin: 0 0 6pt; color: #0d1b2a; border-bottom: 3px solid #f0a030; padding-bottom: 4pt;
     break-before: page; }
h2 { font-size: 13.5pt; margin: 16pt 0 4pt; color: #1b3a57; break-after: avoid; }
h3 { font-size: 11pt; margin: 12pt 0 3pt; color: #1b3a57; break-after: avoid; }
p { margin: 4pt 0 6pt; }
code, kbd { font-family: Consolas, monospace; font-size: 9.2pt; background: #eef1f5; padding: 0 3px; border-radius: 3px; }
kbd { border: 1px solid #b8c0cc; background: #f7f8fa; font-weight: 600; }
pre { font: 8.8pt/1.4 Consolas, monospace; background: #0f1720; color: #d7e3ee; padding: 8pt 10pt; border-radius: 6px;
      white-space: pre-wrap; break-inside: avoid; }
table.t { width: 100%; border-collapse: collapse; margin: 6pt 0 10pt; font-size: 9.4pt; break-inside: auto; }
table.t th { background: #1b3a57; color: #fff; text-align: left; padding: 4pt 6pt; }
table.t td { border-bottom: 1px solid #dde2e8; padding: 4pt 6pt; vertical-align: top; }
table.t tr { break-inside: avoid; }
table.keep { break-inside: avoid; }
table.t td:first-child { white-space: nowrap; font-weight: 600; }
.note, .tip, .warn { border-left: 4px solid #3a86ff; background: #eef4ff; padding: 6pt 9pt; margin: 8pt 0; border-radius: 0 6px 6px 0;
                     break-inside: avoid; }
.tip { border-color: #2cb67d; background: #eaf8f1; }
.warn { border-color: #f0a030; background: #fff5e6; }
ol, ul { margin: 3pt 0 6pt 18pt; padding: 0; } li { margin: 2pt 0; }
figure.pads { margin: 8pt auto 12pt; text-align: center; break-inside: avoid; }
table.grid { border-collapse: separate; border-spacing: 3px; margin: 0 auto; background: #101216; padding: 6px; border-radius: 8px; }
table.grid td.pad { width: 44px; height: 26px; border-radius: 4px; font: 600 7.4pt Consolas, monospace; text-align: center; }
table.grid td.play { outline: 3px solid #3cff5a; outline-offset: -3px; }
table.grid td.side { min-width: 70px; border-left: 4px solid; background: #22262d; color: #e8e8e8; font-size: 7.6pt;
                     padding: 0 5px; text-align: left; white-space: nowrap; }
table.grid td.under { height: 9px; border-top: 4px solid; background: #22262d; color: #fff; font-size: 7pt; text-align: center; }
table.grid th { color: #aab; font: 7.2pt 'Segoe UI'; padding: 0 3px; }
figcaption { font-size: 8.8pt; color: #555; margin-top: 4pt; font-style: italic; }
svg.map { width: 100%; max-width: 640px; display: block; margin: 8pt auto; }
.cover { height: 297mm; background: linear-gradient(160deg, #0d1b2a 0%, #1b3a57 55%, #f0a030 160%); color: #fff;
         padding: 55mm 22mm 0; position: relative; }
.cover h1 { border: 0; color: #fff; font-size: 38pt; line-height: 1.1; break-before: avoid; }
.cover .sub { font-size: 16pt; color: #f0c070; margin-top: 8pt; }
.cover .meta { position: absolute; bottom: 30mm; left: 22mm; font-size: 11pt; color: #cfd8e3; line-height: 1.7; }
.cover .pads-deco { margin-top: 26mm; display: grid; grid-template-columns: repeat(8, 16mm); gap: 3mm; }
.cover .pads-deco span { height: 10mm; border-radius: 2mm; opacity: .92; }
.toc { columns: 2; column-gap: 12mm; font-size: 10.5pt; } .toc a { color: #1b3a57; text-decoration: none; }
.toc div { margin: 2pt 0; break-inside: avoid; } .toc .l2 { margin-left: 12pt; color: #555; font-size: 9.5pt; }
.flow { display: flex; align-items: center; justify-content: center; gap: 6pt; margin: 10pt 0; font-size: 9.5pt; }
.flow div { background: #1b3a57; color: #fff; padding: 7pt 10pt; border-radius: 6px; text-align: center; }
.flow span { color: #f0a030; font-size: 14pt; }
"""


def table(headers, rows):
    cls = "t keep" if len(rows) <= 6 else "t"      # short tables never split across pages
    h = ['<table class="%s"><tr>' % cls + "".join("<th>%s</th>" % x for x in headers) + "</tr>"]
    for r in rows:
        h.append("<tr>" + "".join("<td>%s</td>" % x for x in r) + "</tr>")
    h.append("</table>")
    return "".join(h)


def build():
    d = diagrams()
    deco = "".join('<span style="background:%s"></span>' % c for c in
                   [RED, ORANGE, YELLOW, GREEN, TEAL, CYAN, BLUE, PURPLE] * 2 + [OFF] * 3 +
                   [MAGENTA, OFF, AMBER, OFF, CYAN])

    sections = []   # (id, title, level)

    def H1(i, t):
        sections.append((i, t, 1))
        return '<h1 id="%s">%s</h1>' % (i, t)

    def H2(i, t):
        sections.append((i, t, 2))
        return '<h2 id="%s">%s</h2>' % (i, t)

    body = []
    B = body.append

    # ------------------------------------------------------------------ 1 overview
    B(H1("overview", "1. Overview"))
    B("""<p>This script turns an <b>Akai Force</b> into a full controller for <b>FL Studio</b>, the same way the
    Force works with Ableton Live: its touchscreen shows your tracks, clips and plugin parameters, the 8&times;8 pads
    launch clips, sequence steps and play notes, and the knob screens show names and values.</p>""")
    B(H2("how", "How it works"))
    B("""<p>The Force has a <b>Live Control</b> mode made for Ableton Live. In that mode it talks plain MIDI over the
    network through Akai's <b>Network MIDI driver</b>, on a port called <code>Akai Network - DAW Control</code>. This
    project re-implements the other side of that conversation as an FL Studio <b>MIDI controller script</b>, so FL
    Studio takes Ableton's place. Nothing else runs in the background: no server, no VST, no bridge app.</p>
    <div class="flow"><div>Akai Force<br><small>Live Control mode</small></div><span>&#8646;</span>
    <div>Wi-Fi / Ethernet</div><span>&#8646;</span><div>Akai Network<br>MIDI driver</div><span>&#8646;</span>
    <div>FL Studio<br><small>device_AkaiForce.py</small></div></div>
    <p>The Force draws its own screens. The script only sends names, colours and values, and reacts to your pads,
    knobs, buttons and touches.</p>""")
    B(H2("features", "What you get"))
    B("""<ul>
    <li><b>Eight pad modes:</b> PERFORM (clip launching), PATTERNS, STEPS (step sequencer with per-step editing),
        KEYS (with scales), DRUMS, CHANNELS, PLUGIN (play with any plugin's parameters and presets) and SONG
        (jump to any bar).</li>
    <li><b>Mixer on the Force:</b> 8 mixer inserts at a time with names, colours, volume, pan, mute, solo, arm,
        meters and up to 4 sends. Knobs control volume, and the knob screens show the name or the dB value.</li>
    <li><b>Plugins from the Force:</b> 8 parameters at a time (macros first), preset browsing, open the plugin window,
        bypass, and randomize-with-undo, for the selected instrument or any mixer effect.</li>
    <li><b>Transport:</b> play, stop, record, song record, overdub, loop record, count-in, tap tempo (it flashes on the
        beat), metronome, undo/redo, tempo entry and nudge, snap, song position, new pattern and markers.</li>
    <li><b>Your own plugin pages:</b> choose and name the 8 knobs per plugin in <code>force_plugin_maps.py</code>.</li>
    </ul>""")

    # ------------------------------------------------------------------ 2 requirements
    B(H1("requirements", "2. Requirements"))
    B(table(["What", "Details"], [
        ["Akai Force", "With Live Control mode (the Ableton controller mode), connected to your network by "
                       "Wi-Fi or a USB-to-Ethernet adapter."],
        ["Akai Network Driver", "Free, from the inMusic Software Center (<i>My Hardware</i> tab) or akaipro.com. "
                                "Available for <b>Windows</b> and <b>Intel Macs</b> only."],
        ["FL Studio", "With Python MIDI scripting (FL Studio 20.7 or newer). Developed and tested on FL Studio 2026 (v26.1)."],
        ["Computer", "Windows 10/11 (tested). macOS on Intel should work but hasn't been tested. "
                     "Apple Silicon Macs can't run Akai's network driver."],
        ["Python", "<b>Not needed</b> for the script (FL Studio has its own). Only the optional developer tools use it."],
    ]))
    B("""<div class="warn"><b>One device at a time.</b> If several Forces or MPCs are on the network, only one can be
    in Live Control with the computer at once. Close Ableton Live too, so it doesn't compete for the port.</div>""")

    # ------------------------------------------------------------------ 3 installation
    B(H1("install", "3. Installation"))
    B(H2("driver", "Step 1: Akai Network Driver and pairing"))
    B("""<ol>
    <li>Install <b>Akai Network Driver</b> (inMusic Software Center &rarr; My Hardware, or akaipro.com). Restart the computer.</li>
    <li>On the Force, press <kbd>MENU</kbd>, tap the <b>gear</b> icon (Preferences), open <b>Wi-Fi</b> and join the
        same network as the computer. Or use a USB-to-Ethernet adapter and enable <b>Ethernet</b> in Preferences.</li>
    <li>Open the <b>Akai Network Driver</b> app and select your Force (IP address and serial number) under
        <b>Configured Remote Device</b>. If it isn't listed, use <b>Add a Device</b> and type its IP address.
        On the Force, hold <kbd>SHIFT</kbd> and tap <b>Info</b> in the Wi-Fi menu to see it.</li>
    </ol>
    <p>After this, Windows has two new MIDI ports: <code>Akai Network - DAW Control</code> (used by this script) and
    <code>Akai Network - MIDI</code>.</p>""")
    B(H2("script", "Step 2: Install the script"))
    B("""<p>Pick whichever is easiest:</p>
    <h3>A. Release download (recommended)</h3>
    <ol><li>Download <b>AkaiForceLive-v%s.zip</b> from the <i>Releases</i> page: <code>%s/releases</code></li>
    <li>Unzip it and double-click <b>install.bat</b>.</li></ol>
    <h3>B. One line in PowerShell</h3>
    <pre>irm https://raw.githubusercontent.com/Pyrodrifter/akai-force-fl-studio/main/install.ps1 | iex</pre>
    <h3>C. macOS (Intel, untested)</h3>
    <pre>curl -fsSL https://raw.githubusercontent.com/Pyrodrifter/akai-force-fl-studio/main/install.sh | sh</pre>
    <p>The installer copies the script files into FL Studio's user <i>Hardware</i> folder (it reads FL's own user-data
    location, normally <code>Documents\\Image-Line\\FL Studio\\Settings\\Hardware\\Akai Force Live</code>), then checks
    that FL Studio and the Akai Network driver are present and prints the next steps.</p>
    <div class="note"><b>Manual install:</b> create the folder above and copy <code>device_AkaiForce.py</code>,
    <code>force_protocol.py</code> and <code>force_plugin_maps.py</code> into it. That's all the installer does. It
    only copies <code>force_plugin_maps.py</code> the first time, so your own plugin pages survive updates.</div>""" % (VERSION, REPO))
    B(H2("flsetup", "Step 3: Set up FL Studio"))
    B("""<ol><li>Open <b>Options &rarr; MIDI Settings</b>. If FL was already running, click <b>Update MIDI scripts</b>.</li>
    <li>Under <b>Input</b>, select <code>Akai Network - DAW Control</code>, then set:</li></ol>""")
    B(table(["Setting", "Value"], [
        ["Enable", "On"],
        ["Controller type", "<b>Akai Force (Live Control)</b>"],
        ["Port", "Any free number, e.g. <b>1</b>"],
    ]))
    B("""<ol start="3"><li>Under <b>Output</b>, select <code>Akai Network - DAW Control</code> and give it the
    <b>same Port number</b>. This links the script's messages back to the Force; without it the Force stays on
    <i>waiting for communication</i>.</li>
    <li>Leave <code>Akai Network - MIDI</code> alone; this script doesn't use it.</li></ol>""")
    B(H2("connect", "Step 4: Connect the Force"))
    B("""<p>On the Force press <kbd>MENU</kbd> and tap <b>LIVE CONTROL</b>. Within a second or two the screen shows
    your mixer tracks and the knob screens flash <b>PERFORM</b>. You're connected.</p>
    <div class="tip"><b>Check it:</b> in FL, <b>View &rarr; Script output</b>, tab <i>Akai Network - DAW Control</i>,
    should read <code>Akai Force script v%s loaded</code> followed by <code>Akai Force connected</code>.</div>""" % VERSION)
    B(H2("update", "Updating and uninstalling"))
    B("""<p><b>Update:</b> run the installer again, then in FL click <b>Reload script</b> in Script output (or restart FL).
    <b>Uninstall:</b> <code>install.bat -Uninstall</code> (or <code>./install.sh --uninstall</code>), then set the
    <code>Akai Network - DAW Control</code> input back to <i>(generic controller)</i>.</p>""")

    # ------------------------------------------------------------------ 4 quick start
    B(H1("quick", "4. Your first session"))
    B("""<p>New to this script? Start here. This chapter walks through the Force the way an FL Studio user thinks
    about it: what each part controls in FL, how to move around, and how to tell where you are.</p>""")
    B(H2("tour", "A tour of the Force, in FL Studio terms"))
    B(force_svg())
    B(table(["#", "Part of the Force", "What it does in FL Studio"], [
        ["1", "Touchscreen", "Shows FL's mixer tracks, the current pad grid with names, and the plugin page. Touch works: "
                             "faders, buttons and grid cells all control FL."],
        ["2", "Knob screens (OLEDs)", "Tell you what each knob controls right now. They also flash the pad mode's name "
                                     "whenever you change modes (see below)."],
        ["3", "8 knobs", "Mixer volume of 8 FL mixer tracks, or 8 parameters of a plugin, depending on the knob page."],
        ["4", "Track select row", "Selects that FL mixer track (like clicking it in FL's mixer). The selected one lights white."],
        ["5", "8&times;8 pads", "Depends on the <b>pad mode</b>: clips, patterns, steps, notes, drums, channels, plugin faders or song bars."],
        ["6", "Row buttons (right of the pads)", "An extra action for each pad row, different per mode (scales in KEYS, "
                                                  "banks in PLUGIN, stop a track in PERFORM&hellip;)."],
        ["7", "Lower button row", "Mute / solo / arm the FL mixer track above it (choose with MUTE, SOLO, REC ARM, CLIP STOP)."],
        ["8", "PLAY / STOP / REC", "FL's transport, exactly like the buttons at the top of FL."],
        ["9", "Arrow buttons", "Move around: which 8 mixer tracks you see (&#9664;&#9654;) and the rows of the current mode (&#9650;&#9660;)."],
        ["10", "SHIFT / LAUNCH", "LAUNCH changes the pad mode. SHIFT unlocks second functions (shown as SHIFT+&hellip; in this manual)."],
        ["11", "MUTE / SOLO / REC ARM / CLIP STOP, COPY, DELETE, SELECT, UNDO&hellip;", "Editing helpers: see chapter 5."],
    ]))
    B(H2("screens", "Getting to each screen"))
    B("""<p>The Force draws three main pages. Switch between them with the <b>icons along the left edge of the
    touchscreen</b>:</p>""")
    B(table(["Icon", "Page", "What you see"], [
        ["Grid of dots (top)", "Clip grid", "The current pad mode on screen: every pad with its name and colour. Tap cells like pads."],
        ["Vertical bars (middle)", "Mixer", "8 FL mixer tracks: faders, pan, meters, mute/solo/arm and sends."],
        ["Rectangle (bottom)", "Device", "The current plugin: its name, preset, bank and 8 parameter faders."],
    ]))
    B("""<p>The <b>knobs</b> have pages too: on the mixer page they set mixer volume, on the device page they set plugin
    parameters. Use the Force's <kbd>KNOBS</kbd> button (or its screen) to switch. The knob screens always show which
    you're on: track names mean mixer, parameter names mean plugin.</p>""")
    B(H2("which-mode", "Which pad mode am I in?"))
    B("""<p>Press <kbd>LAUNCH</kbd> to go to the next pad mode and <kbd>SHIFT</kbd>+<kbd>LAUNCH</kbd> to go back. The order is
    <b>PERFORM &rarr; PATTERNS &rarr; STEPS &rarr; KEYS &rarr; DRUMS &rarr; CHANNELS &rarr; PLUGIN &rarr; SONG</b>, then round again.
    Every time you change mode, <b>all 8 knob screens flash the mode's name for about a second</b>. After that, the
    labels in the right-hand column of the clip grid tell you where you are:</p>""")
    B(table(["Mode", "Knob screens flash", "Right-hand column shows", "Pads show"], [
        ["PERFORM", "PERFORM", "Playlist track names", "Performance-Mode clips (or <i>Turn on Perf Mode</i>)"],
        ["PATTERNS", "PATTERNS", "Pat 1-8, Pat 9-16&hellip;", "One pad per pattern"],
        ["STEPS", "STEPS", "Channel names", "Steps of the current pattern"],
        ["KEYS", "KEYS", "Scale names (Chromatic, Major&hellip;)", "Note names (C3, D3&hellip;)"],
        ["DRUMS", "DRUMS", "Note names", "Four coloured 4&times;4 drum banks"],
        ["CHANNELS", "CHANNELS", "Ch 1-8, Ch 9-16&hellip;", "Channel names"],
        ["PLUGIN", "PLUGIN", "Bank 1, Bank 2&hellip;", "8 vertical faders with parameter names"],
        ["SONG", "SONG", "Bars 1-8, Bars 9-16&hellip;", "Bar numbers / marker names"],
    ]))
    B(H2("oleds", "What the knob screens tell you"))
    B(table(["When", "Knob screens show"], [
        ["Normally (mixer knobs)", "The name of the FL mixer track each knob controls, with a volume bar."],
        ["Touching a knob", "That track's volume in dB (e.g. <i>-3.2 dB</i>), until you let go."],
        ["Device page", "Plugin parameter names; the value while you touch the knob."],
        ["Changing pad mode", "The new mode's name on all 8 screens (PERFORM, STEPS&hellip;)."],
        ["Holding a step (STEPS)", "That step's settings: Pitch, Vel, Release, Fine, Pan, Mod X, Mod Y."],
        ["Changing preset (PLUGIN)", "The preset name, or NEXT PRESET if the plugin doesn't report names."],
        ["Other short messages", "AT ON/OFF (pad pressure), BYPASS/ON (plugin), RANDOM/RESTORED, FX CHAIN/CHANNEL, PERF OFF, "
                                 "window names (ASSIGN A), SNAP&hellip;, tempo after a nudge, LOCKED/UNLOCKED, FOLLOW ON/OFF, "
                                 "COPIED, LOOP n (STEPS)."],
    ]))
    B("""<div class="tip">FL Studio's <b>hint bar</b> (top-left of FL's window) also says what just happened, for example
    <i>Force: row = solo</i> or <i>Force: randomized 8 parameters</i>.</div>""")
    B(H2("first-beat", "Your first five minutes"))
    B("""<ol>
    <li><b>Mixer:</b> turn knob 1. FL mixer track 1's fader moves. Touch the knob to read the dB value. Press &#9654; to see
        the next 8 tracks.</li>
    <li><b>Beat:</b> press <kbd>LAUNCH</kbd> until the screens say <b>STEPS</b>. Row 1 is your first channel (e.g. a kick):
        tap pads 1 and 5 to add steps, then press <kbd>PLAY</kbd>. The lower button row shows the playhead moving.</li>
    <li><b>Tweak a step:</b> hold one of those pads and turn knob 2 to change its velocity; knob 1 changes its pitch.</li>
    <li><b>Play notes:</b> <kbd>LAUNCH</kbd> to <b>KEYS</b>, pick a channel with a synth in FL (or with SHIFT+pad in
        CHANNELS), choose <b>Minor</b> with the second row button, and play. Every pad is now in key.</li>
    <li><b>Sound design:</b> <kbd>LAUNCH</kbd> to <b>PLUGIN</b>. Each column is a synth parameter: tap high or low to set it.
        &#9660; tries the next preset; <kbd>SELECT</kbd> opens the synth's window in FL; SHIFT+DELETE randomizes, UNDO takes it back.</li>
    <li><b>Arrange:</b> <kbd>LAUNCH</kbd> to <b>SONG</b>, press <kbd>PLAY</kbd>, and tap any bar to jump there.</li>
    </ol>""")
    B(H2("cheat", "FL Studio &rarr; Force cheat sheet"))
    B(table(["I want to&hellip; (in FL)", "On the Force"], [
        ["Play / stop / record", "PLAY / STOP / REC"],
        ["Undo / redo", "UNDO / SHIFT+UNDO"],
        ["Change the tempo", "Tap TAP TEMPO, or type the value on the touchscreen"],
        ["Turn the metronome on", "SHIFT+TAP TEMPO"],
        ["Show the mixer / channel rack / playlist / piano roll", "ASSIGN A (steps through them; SHIFT goes back)"],
        ["Switch pattern / song mode", "ASSIGN B"],
        ["Record into the song", "Arrangement record on screen"],
        ["Change the snap", "Quantize value on screen"],
        ["Make a new pattern / add a marker", "Insert scene on screen / SHIFT + insert scene"],
        ["Select a mixer track", "Track select row (above the pads)"],
        ["Move a mixer fader", "Knob on the mixer page, or the fader on the touchscreen mixer"],
        ["Mute / solo a mixer track", "MUTE or SOLO, then the lower button under that track"],
        ["Select a channel in the channel rack", "CHANNELS mode: SHIFT+pad. STEPS: right-hand row button. Device page: prev/next device"],
        ["Program steps", "STEPS mode"],
        ["Play the selected channel", "KEYS or DRUMS mode"],
        ["Switch pattern", "PATTERNS mode (while playing, it switches at the next bar)"],
        ["Clone a pattern", "COPY"],
        ["Quantize", "SHIFT + first lower-row button, or Quantize on screen"],
        ["Tweak a plugin", "PLUGIN mode, or the knobs on the device page"],
        ["Change a plugin's preset", "PLUGIN mode &#9650;&#9660;, or SHIFT + prev/next bank on the device page"],
        ["Open a plugin's window", "SELECT"],
        ["Bypass a mixer effect", "Device page on/off button (in FX-chain mode)"],
        ["Launch clips live", "PERFORM mode (turn on Performance Mode first)"],
        ["Jump around the song", "SONG mode, or the position control on screen"],
    ]))

    # ------------------------------------------------------------------ 5 controls
    B(H1("controls", "5. Controls"))
    B(H2("hw", "Hardware buttons"))
    B(table(["Control", "Action"], [
        ["LAUNCH", "Next pad mode (the mode name flashes on the knob screens). SHIFT+LAUNCH: previous mode."],
        ["PLAY / STOP / REC", "FL transport. PLAY lights while playing."],
        ["TAP TEMPO", "Tap tempo. SHIFT+TAP TEMPO: metronome on/off. Flashes on every beat while playing."],
        ["ASSIGN A", "Show the next FL window: mixer &rarr; channel rack &rarr; playlist &rarr; piano roll (SHIFT: back). "
                     "Change it with <code>ASSIGN_A</code> (see Settings)."],
        ["ASSIGN B", "Pattern / song mode (lit in song mode). Change it with <code>ASSIGN_B</code>."],
        ["UNDO", "Undo. SHIFT+UNDO: redo."],
        ["&#9664; &#9654;", "Move the 8-track mixer window by one insert (SHIFT: by 8). In PERFORM they scroll blocks and in "
                            "STEPS they page the steps. There, SHIFT+&#9664;&#9654; moves the mixer."],
        ["&#9650; &#9660;", "Scroll the pad rows of the current mode (playlist tracks, pattern pages, channels, octaves, "
                            "drum banks, song pages). SHIFT scrolls further, or by a semitone in KEYS."],
        ["Track select row", "Selects that mixer insert in FL (the selected one is lit white)."],
        ["MUTE / SOLO / REC ARM / CLIP STOP", "Choose what the lower button row does for the 8 visible inserts. "
                                              "In PERFORM they also choose what the row buttons on the right do."],
        ["SHIFT + first lower button", "Quantize the selected channel."],
        ["COPY", "Clone the current pattern. SHIFT+COPY in PLUGIN: print the plugin's parameters for "
                 "<code>force_plugin_maps.py</code> (chapter 8)."],
        ["SHIFT+DELETE", "In STEPS: clear the selected channel's steps in this pattern. In PLUGIN: randomize the 8 parameters."],
        ["SELECT", "Open the current plugin's window in FL (press again to close an instrument's window)."],
        ["SHIFT+SELECT", "Pad pressure &rarr; aftertouch on/off (SELECT lights when on). For KEYS and DRUMS."],
        ["MASTER", "Select the master track (lit while it's selected)."],
        ["STOP ALL", "PERFORM: stop all clips. Other modes: stop the transport."],
    ]))
    B(H2("touch", "Touchscreen"))
    B("""<p>Use the icons on the left of the Force's screen to switch between its <b>clip grid</b>, <b>mixer</b> and
    <b>device</b> pages. The script fills them all:</p>""")
    B(table(["Screen element", "In FL Studio"], [
        ["Clip grid", "Mirrors the pads of the current mode, with names. Tapping a cell = pressing that pad."],
        ["Track headers", "Mixer insert names and colours."],
        ["Faders, pan, mute, solo, arm", "The 8 visible mixer inserts."],
        ["Sends A-D", "Send levels to your send/FX inserts (see Mixer)."],
        ["Tempo", "Shows FL's tempo; type a new value to change it."],
        ["Position encoder", "Moves the song position a beat per tick (SHIFT: one step)."],
        ["Metronome / loop buttons", "Metronome on/off; loop button switches pattern/song mode (lit in song mode)."],
        ["Quantize / Delete", "Same as the hardware functions above."],
        ["Overdub", "FL's overdub recording on/off. SHIFT: loop recording. (FL can't tell scripts whether overdub is on, "
                    "so this button doesn't light.)"],
        ["Automation arm", "FL's count-in before recording, on/off (lit when on). FL has no script control of automation recording."],
        ["Arrangement record", "Record into the song: switches FL to song mode, arms recording and starts playback. Again: stop recording."],
        ["Follow", "The STEPS, PATTERNS and SONG pages follow the playhead (lit when on)."],
        ["Device lock", "Keep the device page and PLUGIN mode on the current plugin, whatever you select next (lit when locked)."],
        ["Nudge &minus; / +", "Tempo down / up 1 BPM (SHIFT: 0.1 BPM)."],
        ["Quantize value", "Step FL's snap: none, 1/4 step, 1/2 step, step, 1/2 beat, beat, bar (SHIFT: back)."],
        ["Insert scene", "New empty pattern. SHIFT: add a playlist marker at the playhead."],
        ["Device page", "8 plugin parameters with names and values, bank and device buttons."],
    ]))

    # ------------------------------------------------------------------ 6 pad modes
    B(H1("modes", "6. Pad modes"))
    B("""<p>The mode applies to the 8&times;8 pads, the clip grid on screen, and the row buttons to the right of the pads.
    The mixer, knobs and transport work the same in every mode.</p>""")
    B(H2("m-perform", "PERFORM: clip launching"))
    B(d["perform"])
    B(table(["Control", "Action"], [
        ["Pad", "Launch that block's clip on that playlist track (other clips on the track stop). Release follows FL's trigger mode."],
        ["SHIFT + pad", "Launch the whole column (every track's clip in that block), like an Ableton scene."],
        ["Row buttons (right)", "Mute, solo or stop that playlist track, depending on the MUTE / SOLO / CLIP STOP button."],
        ["Lower row, CLIP STOP mode", "Launch the block column above the button."],
        ["&#9650;&#9660; / &#9664;&#9654;", "Scroll playlist tracks / blocks. FL outlines the visible area in the playlist."],
    ]))
    B("""<div class="warn">PERFORM needs FL's <b>Performance Mode</b> switched on (Playlist &rarr; Performance mode).
    If it's off, the screen says <i>Turn on Perf Mode</i> and the pads do nothing.</div>""")
    B(H2("m-patterns", "PATTERNS"))
    B(d["patterns"])
    B("<p>Tap a pad to select that pattern (an empty slot creates it). &#9650;&#9660; pages through 8 patterns at a time "
      "(SHIFT: 64).</p>"
      "<p><b>While playing in pattern mode</b>, a pad <b>queues</b> its pattern: it blinks, and FL switches to it at the "
      "start of the next bar, so you stay in time. Press it again or use SHIFT+pad to switch right away. Turn this off with "
      "<code>PATTERN_QUEUE = False</code>.</p>")
    B(H2("m-steps", "STEPS: step sequencer"))
    B(d["steps"])
    B(table(["Control", "Action"], [
        ["Tap a pad", "Toggle that step. Lit = on, dark = off, exactly as in FL's channel rack."],
        ["Hold a pad + turn knobs", "Edit that step: knob 1 pitch, 2 velocity, 3 release, 4 fine pitch, 5 pan, 6 Mod X, 7 Mod Y. "
                                    "The knob screens show the values while you hold. Editing never switches the step off."],
        ["Tap hard / soft", "A new step takes the pad's velocity: hit harder for an accent (<code>STEP_PAD_VELOCITY</code>)."],
        ["Hold a pad + tap another in the row", "Fill every step between the two."],
        ["Hold a row button + press another", "Copy the first channel's steps (with pitch, velocity etc.) to the second."],
        ["Hold a row button + tap a pad", "Loop that channel after that step; the same step again removes the loop. Off by "
                                           "default: set <code>STEPS_CHANNEL_LOOP = True</code> (it uses an undocumented FL function)."],
        ["SHIFT + pad / row button", "Select that channel."],
        ["&#9664;&#9654;", "Page through the pattern 8 steps at a time (up to its real length). With Follow on, the page "
                           "follows the playhead while playing."],
        ["&#9650;&#9660;", "Scroll channels (SHIFT: 8 at a time)."],
        ["SHIFT+DELETE", "Clear the selected channel's steps."],
    ]))
    B("""<div class="note">Channels whose notes were written in the <b>piano roll</b> are labelled <i>(piano roll)</i>
    and show no steps, just like FL's channel rack. The script treats a synth plugin whose notes use more than one pitch
    as piano roll. If that hides a real step pattern, set <code>STEPS_HIDE_PIANO_ROLL = False</code>
    (see Settings).</div>""")
    B(H2("m-keys", "KEYS: melodic playing"))
    B(d["keys"])
    B("""<p>Plays the <b>selected channel</b>, and records like any MIDI keyboard. The pads are velocity sensitive.</p>""")
    B(table(["Control", "Action"], [
        ["Row buttons (right)", "Pick the scale: Chromatic, Major, Minor, Dorian, Mixolydian, Harmonic minor, Major pentatonic, "
                                "Minor pentatonic. In a scale, every pad is in key and rows are 3 scale degrees (a 4th) apart."],
        ["&#9650;&#9660;", "Octave up / down. SHIFT+&#9650;&#9660; moves the root by a semitone (the bottom-left pad is the root)."],
        ["Colours", "Root notes use the channel's colour (deep blue if it has none), naturals are grey and sharps darker."],
    ]))
    B(H2("m-drums", "DRUMS"))
    B(d["drums"])
    B("<p>For FPC, Slicex and drum plugins on the selected channel. &#9650;&#9660; moves by a bank of 16 notes.</p>")
    B(H2("m-channels", "CHANNELS"))
    B(d["channels"])
    B("<p>Each pad triggers one channel-rack channel. Perfect for kits built from separate samples. SHIFT+pad "
      "selects the channel (the selected one blinks). &#9650;&#9660; pages by 8.</p>")
    B(H2("m-plugin", "PLUGIN: play with any plugin"))
    B(d["plugin"])
    B("""<p>PLUGIN turns the pads into 8 faders for the plugin you're working on: the <b>selected channel's instrument</b>,
    or, in FX-chain mode, an <b>effect on the selected mixer track</b>. The most useful parameters come first: macros
    and master controls.</p>""")
    B(table(["Control", "Action"], [
        ["Pad", "Set that column's parameter to that height (bottom = minimum, top = maximum)."],
        ["Knobs (device page)", "Fine control of the same 8 parameters."],
        ["Row buttons (right)", "Choose parameter bank 1-8. SHIFT+&#9650;&#9660; steps through banks beyond 8."],
        ["&#9650; &#9660;", "Previous / next <b>preset</b>. The knob screens flash its name."],
        ["&#9664; &#9654;", "Previous / next plugin (the next channel, or the next effect slot in FX-chain mode)."],
        ["SELECT", "Open the plugin's window in FL so you can see what you're changing."],
        ["SHIFT+DELETE", "Randomize the 8 parameters on screen. Press <kbd>UNDO</kbd> straight after to put them back."],
    ]))
    B("""<div class="note">FL's own undo doesn't record plugin knob moves, so the script keeps a copy of the values before a
    randomize. Only the <b>last</b> randomize can be undone, and only until you touch another parameter.</div>""")
    B(H2("m-song", "SONG"))
    B(d["song"])
    B("""<p>Each pad is one bar of the song. Tap to jump there. The current bar pulses and the page follows playback.
    Entering SONG switches FL to song mode. With <b>playlist markers</b>, each marker's bar shows its name and the
    section takes its colour. Without markers, 4-bar phrases alternate shades. &#9650;&#9660; pages by a row (SHIFT: 64 bars).</p>
    <div class="note">FL can't tell scripts where markers are, so the script finds them when you enter SONG mode (only
    while stopped), briefly moving the playhead and putting it back.</div>""")

    # ------------------------------------------------------------------ 7 mixer & knobs
    B(H1("mixer", "7. Mixer, knobs and screens"))
    B(table(["Feature", "Details"], [
        ["Mixer window", "8 consecutive mixer inserts, moved with &#9664;&#9654; (SHIFT: 8). FL outlines them in the mixer."],
        ["Knobs (mixer)", "Volume of the 8 inserts. Hold SHIFT for fine control. The Force chooses whether knobs are on the "
                          "mixer or device page (its KNOBS button / screen pages)."],
        ["Knob screens", "Show the insert name, the dB value while you touch the knob, and a volume bar."],
        ["Meters", "Left/right peak meters for each strip on the mixer page."],
        ["Mute / solo / arm", "On screen, or with the lower button row in MUTE / SOLO / REC ARM mode."],
        ["Sends A-D", "Route each strip to up to 4 send inserts. By default these are the first inserts whose names contain "
                      "<i>send, reverb, verb, delay, bus</i> or <i>fx</i>. Or list them in <code>SEND_TRACKS</code>. "
                      "Turning a send on an unrouted strip creates the route."],
    ]))

    # ------------------------------------------------------------------ 8 device page
    B(H1("device", "8. Device page (plugins)"))
    B(table(["Control", "Action"], [
        ["Knobs (device)", "8 parameters of the current plugin. The knob screens show names, or values while touched."],
        ["Prev / next bank", "Next 8 parameters (the bank number shows as <i>Bank 2/12</i>, plus the preset name when the plugin reports one)."],
        ["SHIFT + prev/next bank", "Previous / next preset."],
        ["Prev / next device", "Select the previous/next channel, or the previous/next effect slot in FX-chain mode."],
        ["SHIFT + prev/next device", "Switch between the selected channel's plugin and the selected mixer insert's effect chain "
                                     "(the knob screens flash FX CHAIN or CHANNEL)."],
        ["Device on/off button", "Bypass the effect, or mute the instrument's channel. Press again to turn it back on."],
        ["SELECT (hardware)", "Open the plugin's window in FL."],
        ["Device lock (screen)", "Stay on this plugin while you select other channels or inserts. Press again to unlock."],
        ["Focused effect window", "If an effect's window is focused in FL, the page follows it automatically."],
    ]))
    B("""<p>Only real parameters are listed: empty slots and FL's generic <i>MIDI CC</i> / <i>MIDI Channel</i> entries
    (thousands of them on VSTs) are skipped, and parameters named <i>Macro&hellip;</i> or <i>Master&hellip;</i> come first,
    so bank 1 of most synths starts with its macros.</p>""")
    B(H2("maps", "Your own knob pages"))
    B("""<p>For the plugins you use most, you can choose the 8 knobs yourself, in named pages, in
    <code>force_plugin_maps.py</code> (next to the script in FL's Hardware folder):</p>
    <pre>PLUGIN_MAPS = {
    "Sytrus": [
        ("Filter", ["Cutoff", "Resonance", "Env", "", "", "", "Drive", "Mix"]),
        ("Amp", ["Attack", "Decay", "Sustain", "Release"]),
    ],
}</pre>
    <ol><li>Select the plugin, go to PLUGIN mode and press <kbd>SHIFT</kbd>+<kbd>COPY</kbd>. The script prints an entry with
    every parameter in <b>View &rarr; Script output</b>.</li>
    <li>Paste it into <code>force_plugin_maps.py</code>, keep and reorder the parameters you want (up to 8 per page), and
    name the pages.</li>
    <li>In FL, click <b>Reload script</b> in Script output.</li></ol>
    <p>Your pages come first, with their names on the screen and on the PLUGIN row buttons; the automatic banks follow
    (<code>APPEND_ALL_PARAMS</code>). Parameters are matched by name (not case-sensitive) or by number, and a name that
    isn't found is reported in Script output. The installer never overwrites this file.</p>""")

    # ------------------------------------------------------------------ 9 colours
    B(H1("colours", "9. Colours"))
    B("""<p>Everything on the Force takes its colour from FL: channel colours (STEPS, CHANNELS, KEYS roots), mixer insert
    colours (track headers, track buttons), playlist block and track colours (PERFORM) and pattern colours (PATTERNS).
    The Force has a fixed 70-colour palette, so each FL colour is matched to the nearest one.</p>
    <div class="tip"><b>Give your channels real colours.</b> FL's default channel grey can only become a pale grey-white
    on the pads. Bright, saturated colours (red, orange, cyan, green, purple&hellip;) look best. Colour each mixer
    insert like the channel that feeds it and a sound keeps its colour across every mode.</div>
    <p>Dark colours are brightened automatically so pads never look unlit (<code>MIN_BRIGHTNESS</code>).</p>""")

    # ------------------------------------------------------------------ 10 settings
    B(H1("settings", "10. Settings reference"))
    B("<p>Advanced options live at the top of <code>device_AkaiForce.py</code> in FL's Hardware folder. Edit them in any "
      "text editor, then click <b>Reload script</b> in View &rarr; Script output. Re-running the installer overwrites them.</p>")
    B(table(["Setting", "Default", "What it does"], [
        ["PAD_AFTERTOUCH", "False", "Start with pad pressure &rarr; aftertouch on (also toggled live with SHIFT+SELECT)."],
        ["PARAM_FIRST", "macro, master", "Parameters whose names start with these come first on the device page and in PLUGIN."],
        ["PARAM_SKIP", "MIDI CC, MIDI Channel", "Parameter names that are never shown."],
        ["SEND_TRACKS", "()", "Mixer inserts for send knobs A-D, e.g. <code>(20, 21)</code>. Empty = find them by name."],
        ["SEND_KEYWORDS", "send, reverb, &hellip;", "Words that mark an insert as a send when auto-detecting."],
        ["STEPS_HIDE_PIANO_ROLL", "True", "Hide piano-roll channels' notes in STEPS."],
        ["STEP_PAD_VELOCITY", "True", "New steps take the pad's velocity."],
        ["STEPS_CHANNEL_LOOP", "False", "Hold a STEPS row button + tap a pad to loop that channel (undocumented FL function)."],
        ["ASSIGN_A / ASSIGN_B", "windows / song_mode", "What ASSIGN A and B do: <i>windows, song_mode, mixer, channel_rack, "
                                                      "playlist, piano_roll, browser, metronome, loop_record, step_edit, none</i>."],
        ["FOLLOW", "True", "Start with Follow on."],
        ["PATTERN_QUEUE", "True", "PATTERNS pads switch at the next bar while playing."],
        ["NUDGE_BPM", "1.0", "Tempo change per nudge press."],
        ["MIN_BRIGHTNESS", "200", "Colours darker than this (0-255) are brightened."],
        ["SCALES", "8 scales", "The scales offered in KEYS (name + semitones)."],
        ["VOLUME_STEP / PARAM_STEP", "0.004 / 0.008", "How far a knob tick moves volume / plugin parameters."],
        ["FINE", "0.2", "SHIFT multiplier for knobs."],
        ["FLASH_TIME", "1.2 s", "How long the mode name stays on the knob screens."],
        ["PING_INTERVAL / PONG_TIMEOUT", "1 s / 8 s", "Connection keep-alive and how long before it counts as lost."],
        ["HEAL_INTERVAL", "0.25 s", "Background refresh of one pad row, repairing any dropped network message."],
        ["FX_SLOTS / MAX_PARAM_SCAN", "10 / 4096", "Effect slots per insert / plugin parameters scanned for names."],
    ]))

    # ------------------------------------------------------------------ 11 troubleshooting
    B(H1("trouble", "11. Troubleshooting"))
    B(table(["Symptom", "Fix"], [
        ["Force says <i>waiting for communication</i>", "Check MIDI Settings: the DAW Control <b>input</b> uses the Akai Force script "
            "and is enabled, and the DAW Control <b>output</b> has the <b>same Port number</b>. Make sure Ableton isn't open and "
            "the Force is paired in the Akai Network Driver app."],
        ["Script isn't in the Controller type list", "Click <b>Update MIDI scripts</b> in MIDI Settings or restart FL. Check that "
            "<code>Settings\\Hardware\\Akai Force Live</code> contains both .py files."],
        ["Script output: <i>Output port not linked</i>", "Give the DAW Control output the same Port number as the input."],
        ["No <i>Akai Network</i> ports in FL", "Install the Akai Network Driver, restart, pair the Force, and check both are on the same network."],
        ["PERFORM pads do nothing", "Turn on Performance Mode in the playlist (the screen says <i>Turn on Perf Mode</i>)."],
        ["Pads look white or pale", "Those channels/tracks have FL's default grey. Give them colours (chapter 9)."],
        ["A channel shows <i>(piano roll)</i> in STEPS", "Its notes come from the piano roll. Play it in KEYS, or set "
            "<code>STEPS_HIDE_PIANO_ROLL = False</code>."],
        ["Hint bar: <i>FL refused that just now</i>", "FL was busy (e.g. loading a project). Press again."],
        ["Brief disconnect while loading big projects", "Normal. It reconnects by itself within a few seconds."],
        ["Two Forces/MPCs on the network", "Only one can use Live Control with the computer at a time."],
        ["Preset name shows NEXT PRESET", "That plugin doesn't tell FL its preset names (many VSTs don't). The preset still changes."],
        ["PLUGIN says <i>No plugin selected</i>", "The selected channel is a plain sampler or empty. Select a channel with an "
            "instrument plugin, or switch to FX-chain mode (SHIFT + next device) for mixer effects."],
        ["Apple Silicon Mac", "Not supported: Akai's network driver is Windows / Intel-Mac only."],
    ]))

    # ------------------------------------------------------------------ 12 developers
    B(H1("dev", "12. For developers"))
    B(table(["File", "Purpose"], [
        ["device_AkaiForce.py", "The FL Studio controller script."],
        ["force_protocol.py", "The Force's Live Control protocol: constants, message builders and the full control map. No dependencies."],
        ["force_plugin_maps.py", "Your own knob pages per plugin (chapter 8)."],
        ["fl_sim.py", "Runs the script outside FL against a fake project. <code>python fl_sim.py</code> runs the automated checks "
                      "(without FL installed: <code>pip install fl-studio-api-stubs</code>). "
                      "<code>--live</code> drives a real Force. Needs <code>pip install mido python-rtmidi</code>."],
        ["force_probe.py", "Talks to the Force with no DAW: handshake, message decoder, demo layout."],
        ["install.ps1 / install.bat / install.sh", "Installers."],
        ["docs/build_manual.py", "Builds this manual (HTML &rarr; PDF with Chrome or Edge)."],
    ]))
    B(H2("protocol", "Protocol summary"))
    B("""<p>The protocol was worked out from Ableton Live's own <i>Akai_Force_MPC</i> remote script and verified on hardware.
    All SysEx is <code>F0 47 00 &lt;product&gt; &lt;type&gt; &hellip; F7</code> (Force product id <code>0x40</code>).</p>""")
    B(table(["Message", "Format"], [
        ["Ping (host)", "<code>F0 47 00 7F 00 F7</code>, about every 1-3 s"],
        ["Pong (Force)", "<code>F0 47 00 40 01 F7</code>. The Force also sends it on its own while waiting."],
        ["Text", "<code>F0 47 00 40 10 id0 id1 lenHi lenLo ascii&hellip; F7</code>, e.g. track name <code>(0, t)</code>, "
                 "clip name <code>(0, 16+row*8+col)</code>, knob screen <code>(18, 16+k)</code>, tempo <code>(3, 0)</code>"],
        ["Pads", "Channel 13 notes 16-79 (<code>16+row*8+col</code>); colour CC 40-103 on the same layout; the note velocity "
                 "sets the clip state (0 empty, 2 stopped, 3 queued, 4 playing, 7 recording)"],
        ["Pad pressure", "Repeated note-ons while held: the first is the velocity, later ones are pressure, 0 = release"],
        ["Knobs", "Channel 14 CC 0-7 (mixer page) / 8-15 (device page), relative two's complement; touch = notes 0-15"],
        ["Screen mixer", "Channel 2-9 (one per strip): CC 0 volume, 1 pan, 3-6 sends, 124/125 meters; notes 0 solo, 1 mute, 5 arm"],
        ["Colours", "Values 8-77 = Live's 70-colour palette; 0-7 and 127 are state colours"],
    ]))
    B("<p>The complete map is in <code>force_protocol.py</code>.</p>")

    # ------------------------------------------------------------------ 13 legal
    B(H1("legal", "13. License and credits"))
    B("""<p>Released under the <b>MIT License</b>. See <code>LICENSE</code> in the repository.</p>
    <p>Akai, Akai Professional, Force and MPC are trademarks of inMusic Brands. FL Studio is a trademark of Image-Line.
    Ableton and Live are trademarks of Ableton AG. This project is independent and not affiliated with or endorsed by any of them.</p>
    <p>Source, issues and updates: <code>%s</code></p>""" % REPO)

    # ------------------------------------------------------------------ assemble
    toc = ['<div class="toc">']
    for i, t, lvl in sections:
        toc.append('<div class="l%d"><a href="#%s">%s</a></div>' % (lvl, i, t))
    toc.append("</div>")
    cover = """<section class="cover"><h1>Akai Force<br>&times; FL Studio</h1>
      <div class="sub">Live Control script: User Manual</div>
      <div class="pads-deco">%s</div>
      <div class="meta">Version %s<br>%s</div></section>""" % (deco, VERSION, REPO)
    html = """<!doctype html><html><head><meta charset="utf-8"><title>Akai Force x FL Studio: Manual</title>
      <style>%s</style></head><body>%s<h1 id="contents">Contents</h1>%s%s</body></html>""" % (
        CSS, cover, "".join(toc), "".join(body))
    open(OUT_HTML, "w", encoding="utf-8").write(html)
    return OUT_HTML


def find_browser():
    for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        if os.path.exists(p):
            return p
    return (shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("msedge")
            or shutil.which("chromium") or shutil.which("chromium-browser"))


if __name__ == "__main__":
    html = build()
    browser = find_browser()
    if not browser:
        sys.exit("Built %s but found no Chrome/Edge to print the PDF." % html)
    subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    "--print-to-pdf=" + OUT_PDF, "file:///" + html.replace("\\", "/")], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("Wrote", OUT_PDF)
