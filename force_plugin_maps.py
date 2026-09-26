"""
Your own knob pages for plugins (Akai Force script, device page and PLUGIN mode).

Without an entry here, the 8 knobs step through a plugin's parameters in the
order the plugin lists them (macros first). With an entry, the banks are your
pages, in your order, each with its own name on the Force's screen.

    "Plugin name": [
        ("Page name", ["Param", "Param", ...]),    # up to 8 per page
        ...
    ],

- The plugin name is what FL shows in the plugin's title bar (not case-sensitive).
- Give a parameter by its name (not case-sensitive) or by its number (0 = first).
- "" or None leaves a knob empty. A name that isn't found is reported in FL's
  script output (View > Script output) and leaves the knob empty.

Getting the names: select the plugin, go to PLUGIN mode on the Force and press
SHIFT+COPY. The script prints a ready-made entry with every parameter in FL's
script output; paste it below, then keep and reorder the ones you want.

The installer never overwrites this file, so your pages survive updates. After
editing it, reload the script: Options > MIDI Settings > Update MIDI scripts
(or restart FL).
"""

APPEND_ALL_PARAMS = True     # after your pages, also offer the automatic banks of every parameter

PLUGIN_MAPS = {
    # Example (a made-up synth -- replace with your own):
    #
    # "My Synth": [
    #     ("Filter", ["Cutoff", "Resonance", "Env Amount", "Key Track", "", "", "Drive", "Mix"]),
    #     ("Amp Env", ["Attack", "Decay", "Sustain", "Release"]),
    #     ("FX", [40, 41, 42, 43]),          # by parameter number
    # ],
}
