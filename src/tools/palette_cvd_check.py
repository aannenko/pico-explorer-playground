"""Host-side CVD (colour-vision-deficiency) verification for the palette.

Runs on CPython (NOT the Pico).  Simulates how each palette colour looks under
protanopia / deuteranopia / tritanopia (Machado et al. 2009, severity 1.0,
applied in LINEAR RGB), converts to CIELAB, and reports the closest pairs by
CIEDE2000 so we can see which colours become indistinguishable for each CVD
type.  CIEDE2000 is self-checked against Sharma et al.'s reference vector.

Purpose: replace eyeballed colour picks with measured distinguishability, and
anchor the qualitative slots on authentic Okabe-Ito values where possible.
"""

import math
import pathlib
import sys
import types

# Import the canonical palette RGBs so this checker can never drift from the
# device.  ``displays.palette`` keeps module-level imports to
# ``micropython.const`` only, so a small shim is all CPython needs.
_TOOL_DIR = pathlib.Path(__file__).resolve().parent
_PICO_DIR = _TOOL_DIR.parent / "pico"
if str(_PICO_DIR) not in sys.path:
    sys.path.insert(0, str(_PICO_DIR))
if "micropython" not in sys.modules:
    _mp = types.ModuleType("micropython")
    _mp.const = lambda x: x  # type: ignore[attr-defined]
    sys.modules["micropython"] = _mp

from displays.palette import PALETTE_RGB  # noqa: E402

# Names for the 12 authored slots (slots 12-15 are spare); RGBs come from the
# canonical PALETTE_RGB so they can never drift.
_NAMES = ("BLACK", "WHITE", "GRAY", "DKGRAY", "BLUE", "GREEN", "YELLOW",
          "RED", "SKY", "ORANGE", "RPURPLE", "BROWN")
PALETTE = tuple((_NAMES[i], *PALETTE_RGB[i]) for i in range(len(_NAMES)))

# Slots where colour is NOT the sole signal (achromatic + ordered ramp uses
# luminance + value-pixel position).  We focus clash-reporting on the
# qualitative chromatic slots, but compute everything.
ACHROMATIC = {0, 1, 2, 3}

# Machado 2009 severity-1.0 matrices (apply to LINEAR rgb).
M = {
    "protan": ((0.152286, 1.052583, -0.204868),
               (0.114503, 0.786281, 0.099216),
               (-0.003882, -0.048116, 1.051998)),
    "deutan": ((0.367322, 0.860646, -0.227968),
               (0.280085, 0.672501, 0.047413),
               (-0.011820, 0.042940, 0.968881)),
    "tritan": ((1.255528, -0.076749, -0.178779),
               (-0.078411, 0.930809, 0.147602),
               (0.004733, 0.691367, 0.303900)),
}


def _to_lin(c):
    c /= 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _from_lin(c):
    c = min(1.0, max(0.0, c))
    return (12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055) * 255.0


def simulate(rgb, kind):
    if kind == "normal":
        return rgb
    lin = [_to_lin(v) for v in rgb]
    m = M[kind]
    out = [sum(m[i][j] * lin[j] for j in range(3)) for i in range(3)]
    return tuple(_from_lin(v) for v in out)


def rgb_to_lab(rgb):
    r, g, b = (_to_lin(v) for v in rgb)
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    x, y, z = x / 0.95047, y / 1.0, z / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def ciede2000(lab1, lab2):
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2
    c1 = math.hypot(a1, b1)
    c2 = math.hypot(a2, b2)
    cbar = (c1 + c2) / 2
    g = 0.5 * (1 - math.sqrt(cbar ** 7 / (cbar ** 7 + 25 ** 7))) if cbar > 0 else 0
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360
    h2p = math.degrees(math.atan2(b2, a2p)) % 360
    dlp = l2 - l1
    dcp = c2p - c1p
    if c1p * c2p == 0:
        dhp = 0.0
    else:
        dh = h2p - h1p
        if dh > 180:
            dh -= 360
        elif dh < -180:
            dh += 360
        dhp = dh
    dHp = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp) / 2)
    lbarp = (l1 + l2) / 2
    cbarp = (c1p + c2p) / 2
    if c1p * c2p == 0:
        hbarp = h1p + h2p
    elif abs(h1p - h2p) > 180:
        hbarp = (h1p + h2p + 360) / 2 if (h1p + h2p) < 360 else (h1p + h2p - 360) / 2
    else:
        hbarp = (h1p + h2p) / 2
    t = (1 - 0.17 * math.cos(math.radians(hbarp - 30))
         + 0.24 * math.cos(math.radians(2 * hbarp))
         + 0.32 * math.cos(math.radians(3 * hbarp + 6))
         - 0.20 * math.cos(math.radians(4 * hbarp - 63)))
    dtheta = 30 * math.exp(-(((hbarp - 275) / 25) ** 2))
    rc = 2 * math.sqrt(cbarp ** 7 / (cbarp ** 7 + 25 ** 7)) if cbarp > 0 else 0
    sl = 1 + (0.015 * (lbarp - 50) ** 2) / math.sqrt(20 + (lbarp - 50) ** 2)
    sc = 1 + 0.045 * cbarp
    sh = 1 + 0.015 * cbarp * t
    rt = -math.sin(math.radians(2 * dtheta)) * rc
    return math.sqrt((dlp / sl) ** 2 + (dcp / sc) ** 2 + (dHp / sh) ** 2
                     + rt * (dcp / sc) * (dHp / sh))


# Self-check CIEDE2000 against Sharma's reference (expected 2.0425).
_ref = ciede2000((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485))
assert abs(_ref - 2.0425) < 0.01, "CIEDE2000 impl wrong: %.4f" % _ref
print("CIEDE2000 self-check OK (%.4f vs 2.0425)\n" % _ref)

names = [p[0] for p in PALETTE]
rgbs = [(p[1], p[2], p[3]) for p in PALETTE]
_BY_NAME = {p[0]: (p[1], p[2], p[3]) for p in PALETTE}

THRESH = 12.0  # below ~12 dE2000 = hard to tell apart
for kind in ("normal", "protan", "deutan", "tritan"):
    labs = [rgb_to_lab(simulate(c, kind)) for c in rgbs]
    pairs = []
    for i in range(len(rgbs)):
        for j in range(i + 1, len(rgbs)):
            if i in ACHROMATIC and j in ACHROMATIC:
                continue
            de = ciede2000(labs[i], labs[j])
            pairs.append((de, names[i], names[j]))
    pairs.sort()
    print("=== %s ===" % kind.upper())
    clonce = [p for p in pairs if p[0] < THRESH]
    if not clonce:
        print("  no pairs below dE %.0f" % THRESH)
    for de, n1, n2 in clonce:
        print("  dE %5.1f  %-8s <-> %-8s   *** CLASH" % (de, n1, n2))
    # also show the 3 closest above-threshold for context
    above = [p for p in pairs if p[0] >= THRESH][:3]
    for de, n1, n2 in above:
        print("  dE %5.1f  %-8s <-> %-8s" % (de, n1, n2))
    print()


# Per-metric sensor-band fill sets (band 0 -> 3, low -> high).  Within one graph
# these 4 fills co-occur, but the band is ALSO carried by the icon + the
# value-pixel position, so a sub-threshold fill pair degrades rather than breaks
# readability.  This reports the worst within-set pair per CVD type for info.
METRIC_SETS = (
    ("TEMPERATURE", ("SKY", "GREEN", "ORANGE", "RED")),
    ("HUMIDITY", ("YELLOW", "GREEN", "SKY", "BLUE")),
    ("PRESSURE", ("RPURPLE", "GREEN", "YELLOW", "ORANGE")),
    ("GAS", ("RED", "ORANGE", "GREEN", "SKY")),
)
print("### Per-metric band-fill distinguishability (worst pair per CVD type) ###")
for label, members in METRIC_SETS:
    print("%-12s %s" % (label, " ".join(members)))
    for kind in ("normal", "protan", "deutan", "tritan"):
        labs = {m: rgb_to_lab(simulate(_BY_NAME[m], kind)) for m in members}
        worst = None
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                de = ciede2000(labs[members[a]], labs[members[b]])
                if worst is None or de < worst[0]:
                    worst = (de, members[a], members[b])
        flag = "  *** below %.0f" % THRESH if worst[0] < THRESH else ""
        print("    %-7s worst dE %5.1f  %s<->%s%s" % (kind, worst[0], worst[1], worst[2], flag))
    print()
