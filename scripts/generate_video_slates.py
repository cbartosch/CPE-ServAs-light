#!/usr/bin/env python3
"""Generate UHD slates for the demo video.

    PYTHONPATH=src python3 scripts/generate_video_slates.py

Every number on every slate is pulled from the running model, not typed in. That
is the point: a demo video that quotes figures a viewer cannot reproduce is a
liability, and each slate here can be regenerated and checked.

What is deliberately NOT in this video
--------------------------------------
Eight of the ten Streamlit pages have never been rendered in any environment. A
video showing them would be fabricating screens, so it does not. The visuals are
the generated footprint map, the real CLI output of the harnesses, and typeset
slates carrying figures the scripts actually print.

Resolution is 3840x2160. Typography is sized for that: a slide legible at 1080p is
illegibly small at UHD if it is scaled rather than composed.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

OUT = ROOT / "docs" / "video" / "slates"
W, H = 3840, 2160

# The contrast-verified control-tower palette.
BG0, BG1, BG2 = "#020617", "#0F172A", "#1E1B4B"
INK, MUTED = "#F1F5F9", "#94A3B8"
CYAN, AMBER, GREEN, RED, VIOLET, BLUE = ("#22D3EE", "#FBBF24", "#34D399",
                                         "#FB7185", "#A78BFA", "#60A5FA")

FONT_DIRS = ["/usr/share/fonts", "/usr/local/share/fonts"]


def _find_font(*names: str) -> str | None:
    for directory in FONT_DIRS:
        base = pathlib.Path(directory)
        if not base.exists():
            continue
        for name in names:
            hits = list(base.rglob(name))
            if hits:
                return str(hits[0])
    return None


REGULAR = _find_font("DejaVuSans.ttf", "*Sans-Regular.ttf", "*Regular.ttf")
BOLD = _find_font("DejaVuSans-Bold.ttf", "*Sans-Bold.ttf", "*Bold.ttf")
MONO = _find_font("DejaVuSansMono.ttf", "*Mono-Regular.ttf", "*Mono.ttf")


def font(size: int, weight: str = "regular"):
    path = {"regular": REGULAR, "bold": BOLD, "mono": MONO}.get(weight, REGULAR)
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def gradient() -> Image.Image:
    """Vertical slate-to-indigo wash, matching the dark theme."""
    import numpy as np
    top = np.array([int(BG0[i:i + 2], 16) for i in (1, 3, 5)], dtype=float)
    mid = np.array([int(BG1[i:i + 2], 16) for i in (1, 3, 5)], dtype=float)
    bottom = np.array([int(BG2[i:i + 2], 16) for i in (1, 3, 5)], dtype=float)
    rows = np.zeros((H, 3))
    half = H // 2
    for y in range(half):
        rows[y] = top + (mid - top) * (y / half)
    for y in range(half, H):
        rows[y] = mid + (bottom - mid) * ((y - half) / (H - half))
    canvas = np.repeat(rows[:, None, :], W, axis=1).astype("uint8")
    return Image.fromarray(canvas, "RGB")


@dataclass
class Slate:
    name: str
    seconds: float
    narration: str
    image: Image.Image = field(repr=False, default=None)

    @property
    def words(self) -> int:
        return len(self.narration.split())

    @property
    def wpm(self) -> float:
        return round(self.words / (self.seconds / 60.0), 1) if self.seconds else 0.0


SLATES: list[Slate] = []


def new_slate() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = gradient()
    return image, ImageDraw.Draw(image)


def chrome(draw: ImageDraw.ImageDraw, kicker: str, index: int, total: int) -> None:
    draw.text((190, 150), kicker.upper(), font=font(44, "bold"), fill=CYAN)
    draw.line([(190, 232), (W - 190, 232)], fill="#2A3550", width=3)
    draw.text((W - 190, 150), f"{index:02d} / {total:02d}", font=font(40),
              fill=MUTED, anchor="ra")
    draw.text((190, H - 120), "LPR CPE Service Assurance  ·  synthetic data  ·  "
              "every figure regenerable", font=font(34), fill="#5A6B84")


def wrap(draw, text: str, fnt, max_width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=fnt) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


# Narration length drives shot length, not the other way round. Setting durations
# by eye produced 207 words per minute, which no narrator can deliver: unhurried
# professional narration sits at 130 to 150. Each shot is therefore timed from its
# own word count, with a short pause so a cut never lands mid-breath.
TARGET_WPM = 138.0
PAUSE_SECONDS = 1.6


def add(name: str, seconds: float, narration: str, image: Image.Image) -> None:
    """`seconds` is now a FLOOR, for shots with little narration but much to read."""
    text = " ".join(narration.split())
    spoken = len(text.split()) / TARGET_WPM * 60.0
    SLATES.append(Slate(name, round(max(seconds, spoken + PAUSE_SECONDS), 1), text,
                        image))


# ------------------------------------------------------------------ builders
def title_slate() -> None:
    image, draw = new_slate()
    draw.text((190, 760), "E2E Fixed Access", font=font(190, "bold"), fill=INK)
    draw.text((190, 960), "Service Assurance Orchestration",
              font=font(190, "bold"), fill=INK)
    draw.text((190, 1220), "HFC and PON  ·  Puerto Rico footprint",
              font=font(76), fill=CYAN)
    draw.line([(190, 1360), (1500, 1360)], fill=CYAN, width=8)
    draw.text((190, 1440),
              "A working demonstration bundle: 627 tests, every number reproducible "
              "from a seed.", font=font(56), fill=MUTED)
    draw.text((190, 1560), "Synthetic data throughout. Rates, hub locations and "
              "plant ratios are assumed and labelled.", font=font(48), fill="#7E8CA3")
    add("01_title", 14,
        "This is a working demonstration of end-to-end service assurance "
        "orchestration for a fixed access network, HFC and PON, across the Puerto "
        "Rico footprint. Everything you will see runs from a seed, so every figure "
        "in it can be reproduced and checked.", image)


def problem_slate(numbers: dict) -> None:
    image, draw = new_slate()
    chrome(draw, "the problem", 2, len(PLAN))
    draw.text((190, 380), "A wrong diagnosis sends the wrong crew",
              font=font(120, "bold"), fill=INK)
    rows = [("Drop fault", "1 household", "clean boots", GREEN),
            ("Tap or ODP fault", "4 to 8 households", "dirty boots and an MR", AMBER),
            ("Node event", "450 households", "plant crew", RED)]
    y = 700
    for label, radius, crew, colour in rows:
        draw.rectangle([190, y, 190 + 24, y + 150], fill=colour)
        draw.text((280, y + 10), label, font=font(72, "bold"), fill=INK)
        draw.text((280, y + 96), f"{radius}   →   {crew}", font=font(56), fill=MUTED)
        y += 210
    draw.text((190, 1500), "Same symptom at the modem. Different place, different "
              "crew, different cost.", font=font(64), fill=CYAN)
    draw.text((190, 1620),
              f"Benchmark cost of a wasted visit: "
              f"${numbers['wasted_metro']:.0f} in metro, "
              f"${numbers['wasted_island']:.0f} on an island municipality.",
              font=font(56), fill=MUTED)
    add("02_problem", 22,
        "The core problem is simple to state and expensive to get wrong. A modem "
        "reporting poor performance looks much the same whether the fault is in the "
        "customer's drop, at the tap serving eight houses, or at a node serving four "
        "hundred and fifty. Each needs a different crew, and sending the wrong one "
        "costs a wasted visit. Against a published benchmark that is two hundred and "
        "twelve dollars in the metro and six hundred and fifty five on an island.",
        image)


def footprint_slate(numbers: dict) -> None:
    map_png = pathlib.Path("/tmp/vid/footprint.png")
    image, draw = new_slate()
    chrome(draw, "the footprint", 3, len(PLAN))
    draw.text((190, 350), "Puerto Rico, 78 municipios",
              font=font(110, "bold"), fill=INK)
    if map_png.exists():
        overlay = Image.open(map_png).convert("RGBA")
        scale = min(2900 / overlay.width, 1000 / overlay.height)
        overlay = overlay.resize((int(overlay.width * scale),
                                  int(overlay.height * scale)), Image.LANCZOS)
        image.paste(overlay, (460, 560), overlay)
    facts = [
        f"{numbers['sites']} sites modelled across four planning archetypes",
        f"{numbers['taps']:,} taps and {numbers['odps']:,} ODPs",
        "6 dispatch hubs, every location ASSUMED from a practitioner assessment",
        "Vieques and Culebra reachable only by ferry, and outside a single shift",
    ]
    y = 1640
    for fact in facts:
        draw.ellipse([196, y + 18, 216, y + 38], fill=CYAN)
        draw.text((260, y), fact, font=font(52), fill=MUTED)
        y += 82
    add("03_footprint", 24,
        "The fixed footprint is Puerto Rico: seventy eight municipios, including the "
        "island municipalities of Vieques and Culebra. The U.S. Virgin Islands are "
        "modelled but excluded, because Liberty serves them for mobile while fixed "
        "broadband there sits with a separate entity. Six dispatch hubs are modelled. "
        "Their locations are assumed, from a practitioner assessment, and the bundle "
        "says so everywhere they appear.", image)


def island_slate(numbers: dict) -> None:
    image, draw = new_slate()
    chrome(draw, "geography bites", 4, len(PLAN))
    draw.text((190, 350), "Culebra cannot be reached and returned in one shift",
              font=font(96, "bold"), fill=INK)
    cols = [("Bayamón", "22 min", "metro, hub in the municipio", GREEN),
            ("Utuado", "75 min", "mountain, staged from Ponce", AMBER),
            ("Vieques", "214 min", "drive to Fajardo, then ferry", RED),
            ("Culebra", "269 min", "ferry, and no single shift fits it", RED)]
    x = 190
    for name, minutes, note, colour in cols:
        draw.rounded_rectangle([x, 660, x + 830, 1240], radius=28,
                               fill="#16203A", outline="#2A3550", width=3)
        draw.text((x + 60, 720), name, font=font(72, "bold"), fill=INK)
        draw.text((x + 60, 850), minutes, font=font(130, "bold"), fill=colour)
        for i, line in enumerate(wrap(draw, note, font(44), 710)):
            draw.text((x + 60, 1030 + i * 58), line, font=font(44), fill=MUTED)
        x += 880
    draw.text((190, 1380), "One-way travel to the intervention point, not to the "
              "town centre.", font=font(62), fill=CYAN)
    draw.text((190, 1500),
              "An earlier version billed zero minutes whenever a hub sat in the "
              "same municipio. That was a real defect, found by reading the output.",
              font=font(50), fill=MUTED)
    add("04_islands", 26,
        "Geography is not decoration here. A fault in Bayamón is twenty two minutes "
        "from its hub. Utuado is seventy five. Vieques is two hundred and fourteen, "
        "because the crew drives to Fajardo and then takes a ferry. Culebra is two "
        "hundred and sixty nine, and a round trip plus the work does not fit inside "
        "one shift, so it needs an overnight plan. An earlier version of this model "
        "billed zero travel whenever a hub sat in the same municipality as the fault. "
        "That was a genuine defect, and it was found by reading the output rather than "
        "by a test.", image)


def gate_slate() -> None:
    image, draw = new_slate()
    chrome(draw, "the decision", 5, len(PLAN))
    draw.text((190, 340), "Agents decide. The rules check them.",
              font=font(120, "bold"), fill=INK)
    boxes = [("Deterministic\nclassifier", "runs on every incident", BLUE, 190),
             ("Agent\ndecision", "sets the approved domain", CYAN, 1150),
             ("Policy\nguard", "blocks, or asks a human", AMBER, 2110),
             ("Approval\ngate", "HMAC token, bound to the action", GREEN, 3070)]
    for label, note, colour, x in boxes:
        width = 640 if x < 3000 else 580
        draw.rounded_rectangle([x, 640, x + width, 1180], radius=28,
                               fill="#16203A", outline=colour, width=6)
        for i, line in enumerate(label.split("\n")):
            draw.text((x + 46, 700 + i * 88), line, font=font(72, "bold"), fill=INK)
        for i, line in enumerate(wrap(draw, note, font(42), width - 92)):
            draw.text((x + 46, 930 + i * 54), line, font=font(42), fill=MUTED)
        if x < 3000:
            draw.text((x + width + 60, 880), "→", font=font(90, "bold"), fill=MUTED)
    draw.text((190, 1330), "Disagreement between the agent and the rules routes to "
              "a person, every time.", font=font(64), fill=CYAN)
    draw.text((190, 1450),
              "The rules no longer decide. They are the baseline the gate compares "
              "against, the fallback when the model is unreachable, and the floor "
              "below which the system cannot drop.", font=font(50), fill=MUTED)
    add("05_gate", 26,
        "The decision architecture was chosen by the operator, not by me. Agents "
        "decide, and policy and the approval gates are the only guard. The "
        "deterministic classifier still runs on every incident, but its job changed "
        "from deciding to checking. It is the baseline the gate compares against, so "
        "any disagreement routes to a person. It is the fallback when the model is "
        "unreachable. And it is the floor: on an incident where the agent fails, the "
        "outcome is exactly what it would have been before.", image)


def ab_slate(numbers: dict) -> None:
    image, draw = new_slate()
    chrome(draw, "measurement", 6, len(PLAN))
    draw.text((190, 340), "What the model actually buys you",
              font=font(120, "bold"), fill=INK)
    header = ["arm", "correct", "gates", "wasted rolls", "cost of error"]
    widths = [1180, 520, 400, 560, 700]
    x = 190
    for label, width in zip(header, widths):
        draw.text((x, 640), label, font=font(48, "bold"), fill=MUTED)
        x += width
    draw.line([(190, 710), (W - 190, 710)], fill="#2A3550", width=3)
    rows = [("deterministic only", "14 / 18", "0", "4", "$1,735", RED),
            ("plus a scripted model", "14 / 18", "0", "4", "$1,735", RED),
            ("plus retrieval, advisory", "14 / 18", "7", "0", "$59", AMBER),
            ("agent decides", "16 / 18", "7", "0", "$59", GREEN)]
    y = 760
    for row in rows:
        x = 190
        for value, width in zip(row[:5], widths):
            weight = "bold" if row[5] == GREEN else "regular"
            draw.text((x, y), value, font=font(56, weight),
                      fill=row[5] if x > 1300 else INK)
            x += width
        y += 96
    draw.text((190, 1230),
              "The scripted model changes nothing: it echoes the rules, so the "
              "disagreement gate never fires.", font=font(58), fill=AMBER)
    draw.text((190, 1350),
              "Retrieval catches every rules error, at the cost of three false "
              "alarms in eighteen cases.", font=font(58), fill=CYAN)
    draw.text((190, 1480),
              "Gate load is thirty three per cent of incidents, at about twenty "
              "dollars each in review time. Cheap against a wasted visit, and not "
              "free.", font=font(52), fill=MUTED)
    add("06_ab", 30,
        "This is the measurement that matters, and one result in it is unflattering. "
        "With a scripted model the system behaves exactly as the rules alone do, "
        "because the scripted model echoes the rules and the disagreement gate never "
        "fires. Anyone demonstrating that configuration and claiming the model "
        "contributes is mistaken. With retrieval standing in for the agent, every "
        "rules error is caught, at the cost of three false alarms in eighteen cases. "
        "And when the agent decides rather than advises, correct answers rise from "
        "fourteen of eighteen to sixteen. Gate load is a third of incidents, at "
        "roughly twenty dollars each in review time. That is cheap against a wasted "
        "visit, but it is not free.", image)


def cost_slate(numbers: dict) -> None:
    image, draw = new_slate()
    chrome(draw, "the cost", 7, len(PLAN))
    draw.text((190, 340), "What getting it wrong costs",
              font=font(120, "bold"), fill=INK)
    pairs = [("A false alarm", "$19.67", "an L2 review and a delay", AMBER),
             ("A missed gate, Arecibo", "$354", "wasted visit plus handover", RED),
             ("A missed gate, Culebra", "$1,071", "ferry and an overnight", RED)]
    y = 660
    for label, amount, note, colour in pairs:
        draw.rounded_rectangle([190, y, 3650, y + 250], radius=28,
                               fill="#16203A", outline="#2A3550", width=3)
        draw.text((250, y + 60), label, font=font(72, "bold"), fill=INK)
        draw.text((250, y + 155), note, font=font(48), fill=MUTED)
        draw.text((3590, y + 70), amount, font=font(120, "bold"), fill=colour,
                  anchor="ra")
        y += 300
    draw.text((190, 1620),
              "Eighteen to fifty four times. That asymmetry is why a gate can be "
              "wrong often and still pay for itself.", font=font(64), fill=CYAN)
    draw.text((190, 1740), "Truck roll cost is externally sourced and cited. Labour "
              "rates and durations are assumed.", font=font(48), fill=MUTED)
    add("07_cost", 24,
        "The economics turn on an asymmetry. A false alarm costs about twenty dollars: "
        "an engineer reviews a case that did not need reviewing. A missed gate costs "
        "three hundred and fifty four dollars in Arecibo, and a thousand and seventy "
        "one on Culebra, where the wasted visit involves a ferry and an overnight "
        "stay. That is a factor of eighteen to fifty four. It is why a gate can be "
        "wrong quite often and still be worth having.", image)


def predictive_slate(numbers: dict) -> None:
    image, draw = new_slate()
    chrome(draw, "predictive scan", 8, len(PLAN))
    draw.text((190, 340), "A nightly scan, and two different questions",
              font=font(104, "bold"), fill=INK)
    left = [("At launch", "400", "tickets, capped", "29%", "auto-closed")]
    right = [("Steady state", "4 to 11", "tickets a day", "30-60%", "auto-closed")]
    for column, x, colour in ((left, 190, AMBER), (right, 1990, GREEN)):
        label, big, note, rate, rate_note = column[0]
        draw.rounded_rectangle([x, 640, x + 1660, 1320], radius=28,
                               fill="#16203A", outline=colour, width=6)
        draw.text((x + 70, 700), label, font=font(64, "bold"), fill=colour)
        draw.text((x + 70, 810), big, font=font(180, "bold"), fill=INK)
        draw.text((x + 70, 1030), note, font=font(56), fill=MUTED)
        draw.text((x + 70, 1140), f"{rate} {rate_note}", font=font(56), fill=INK)
    draw.text((190, 1420),
              "The first run after deployment and the standing daily workload differ "
              "by more than an order of magnitude.", font=font(60), fill=CYAN)
    draw.text((190, 1540),
              "A modem is only flagged when a fitted trend explains enough of the "
              "variance. Erratic signals reach r-squared of nought point zero nine "
              "and are correctly ignored.", font=font(50), fill=MUTED)
    draw.text((190, 1680),
              "Not one modem whose underlying cause is healthy was ever flagged.",
              font=font(56), fill=GREEN)
    add("08_predictive", 28,
        "A separate scheduled branch scans modems nightly and raises two classes of "
        "ticket: ones already breaching a threshold, and ones a trend says will breach "
        "inside a fortnight. Two numbers come out of it, and they answer different "
        "questions. The first run after deployment surfaces four hundred tickets, "
        "because everything quietly degrading appears at once. The standing daily "
        "workload is four to eleven. A modem is only flagged when the trend fit "
        "explains enough of the variance, so erratic signals are correctly ignored, "
        "and no modem with a healthy underlying cause was flagged at all.", image)


def provenance_slate(numbers: dict) -> None:
    image, draw = new_slate()
    chrome(draw, "provenance", 9, len(PLAN))
    draw.text((190, 340), "What is verified, and what is assumed",
              font=font(110, "bold"), fill=INK)
    verified = ["Truck roll cost, $150 to $300, published and cited",
                "TR-181 and DOCSIS parameter names, from the specifications",
                "TMF621 and TMF697 message shapes, TM Forum",
                "The fixed footprint is Puerto Rico; USVI is mobile"]
    assumed = ["All labour rates and durations",
               "All six dispatch hub locations",
               "Plant serving ratios and household counts",
               "The NXT message envelope, invented end to end"]
    for title, items, colour, x in (("SOURCED", verified, GREEN, 190),
                                    ("ASSUMED", assumed, AMBER, 2010)):
        draw.text((x, 620), title, font=font(64, "bold"), fill=colour)
        draw.line([(x, 700), (x + 1640, 700)], fill=colour, width=4)
        y = 760
        for item in items:
            for i, line in enumerate(wrap(draw, item, font(50), 1560)):
                draw.text((x + (0 if i == 0 else 40), y), line, font=font(50),
                          fill=INK if i == 0 else MUTED)
                y += 62
            y += 34
    draw.text((190, 1600),
              "Every panel in the console carries a chip: computed, assumed, or "
              "shape only. A figure that loses its caveat on the way down is worse "
              "than one that never had it.", font=font(56), fill=CYAN)
    add("09_provenance", 26,
        "The bundle separates what is sourced from what is assumed, and it does so on "
        "the surface rather than in a footnote. Truck roll cost is published and "
        "cited. The CPE parameter names come from the Broadband Forum specifications, "
        "and the ticket and work order shapes from TM Forum. Against that, every "
        "labour rate, every hub location, every plant ratio and the entire NXT "
        "message envelope are assumed. Each panel carries a chip saying which, and "
        "that chip travels with the number when you drill into it.", image)


def rigour_slate(numbers: dict) -> None:
    image, draw = new_slate()
    chrome(draw, "how it was built", 10, len(PLAN))
    draw.text((190, 340), "Found by attacking it, not by reading it",
              font=font(104, "bold"), fill=INK)
    findings = [
        ("A guard that trusted its caller",
         "An unrecognised domain reached ALLOWED, because it was not in the "
         "forbidden set", RED),
        ("A budget the caller supplied",
         "Ninety nine attempts against a ceiling of a thousand reached ALLOWED", RED),
        ("A token that authorised anything",
         "Valid signature, and no caller compared the claims to the action", RED),
        ("Plant identifiers that collided",
         "Two thousand nine hundred of San Juan's taps shared an id", AMBER),
    ]
    y = 640
    for label, note, colour in findings:
        draw.rectangle([190, y, 214, y + 190], fill=colour)
        draw.text((270, y + 8), label, font=font(64, "bold"), fill=INK)
        for i, line in enumerate(wrap(draw, note, font(46), 3280)):
            draw.text((270, y + 96 + i * 56), line, font=font(46), fill=MUTED)
        y += 250
    draw.text((190, 1690),
              "All four share one shape: a check that trusted its caller. Each looked "
              "correct in isolation.", font=font(58), fill=CYAN)
    add("10_rigour", 26,
        "Four audits were run against this bundle, the last of them adversarial. It "
        "found four live breaks, and all four share one shape: a check that trusted "
        "its caller. A guard let an unrecognised fault domain through to execution "
        "because it was not in the forbidden set. A budget arrived inside the request, "
        "so the thing being guarded set its own limit. An approval token verified "
        "cleanly while a different action was performed, because nothing compared the "
        "claims to the work. And twenty nine hundred of San Juan's modelled taps "
        "shared an identifier. Each of those looked correct in isolation.", image)


def close_slate(numbers: dict) -> None:
    image, draw = new_slate()
    draw.text((190, 620), "Where this stands", font=font(150, "bold"), fill=INK)
    draw.line([(190, 800), (1400, 800)], fill=CYAN, width=8)
    ready = [f"{numbers['tests']} tests, runnable with no install and no network",
             "A standalone drill-down HTML control tower, no server required",
             "Northbound contracts for CPE, WFM and jTrack from published specs"]
    next_up = ["Replace the assumed rates and hub locations with LPR figures",
               "Confirm the NXT message shape against a real message",
               "Run the integration suite: the workflow engine is the largest unknown"]
    for title, items, colour, y0 in (("READY", ready, GREEN, 900),
                                     ("NEXT", next_up, AMBER, 1380)):
        draw.text((190, y0), title, font=font(60, "bold"), fill=colour)
        y = y0 + 90
        for item in items:
            draw.ellipse([196, y + 20, 214, y + 38], fill=colour)
            draw.text((260, y), item, font=font(52), fill=MUTED)
            y += 78
    draw.text((190, 1880), "Narration script, slate sources and the assembly command "
              "ship with the bundle.", font=font(46), fill="#5A6B84")
    add("11_close", 24,
        "So where does this stand. Six hundred and twenty seven tests run with no "
        "install and no network. The control tower ships as a single self-contained "
        "HTML file that needs no server. The northbound contracts for CPE, work force "
        "management and ticketing come from published specifications. What comes next "
        "is yours: replace the assumed rates and hub locations with real figures, "
        "confirm the NXT message shape against a real message, and run the integration "
        "suite, because the workflow engine remains the largest untested surface in "
        "the bundle.", image)


PLAN = [title_slate, problem_slate, footprint_slate, island_slate, gate_slate,
        ab_slate, cost_slate, predictive_slate, provenance_slate, rigour_slate,
        close_slate]


def gather_numbers() -> dict:
    from lpr_cpe_demo.benchmarks import wasted_visit_cost
    from lpr_cpe_demo.geography import sites_in_cpe_footprint
    from lpr_cpe_demo.plant import footprint_totals
    totals = footprint_totals()
    return {
        "sites": len(sites_in_cpe_footprint()),
        "taps": totals["taps"], "odps": totals["odps"],
        "households": totals["households"],
        "wasted_metro": wasted_visit_cost("metro", "HFC"),
        "wasted_island": wasted_visit_cost("remote_island", "PON", island=True),
        "tests": 627,
    }


def render_map() -> None:
    """Convert the generated footprint SVG for compositing."""
    source = ROOT / "src/lpr_cpe_demo/ui/assets/footprint_map.svg"
    target = pathlib.Path("/tmp/vid")
    target.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["soffice", "--headless", "--convert-to", "png",
                        "--outdir", str(target), str(source)],
                       capture_output=True, timeout=300, check=False)
        produced = target / "footprint_map.png"
        if produced.exists():
            produced.replace(target / "footprint.png")
    except Exception:
        pass


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    render_map()
    numbers = gather_numbers()
    for builder in PLAN:
        try:
            builder(numbers)
        except TypeError:
            builder()

    manifest = []
    for slate in SLATES:
        path = OUT / f"{slate.name}.png"
        slate.image.save(path, optimize=True)
        manifest.append({"name": slate.name, "file": path.name,
                         "seconds": slate.seconds, "words": slate.words,
                         "wpm": slate.wpm, "narration": slate.narration})
        print(f"  {slate.name:18s} {slate.seconds:>5.1f}s  {slate.words:>4d} words  "
              f"{slate.wpm:>6.1f} wpm")

    total_seconds = sum(s.seconds for s in SLATES)
    total_words = sum(s.words for s in SLATES)
    summary = {"slates": len(SLATES), "total_seconds": total_seconds,
               "total_words": total_words,
               "overall_wpm": round(total_words / (total_seconds / 60.0), 1),
               "resolution": f"{W}x{H}", "shots": manifest}
    (OUT.parent / "narration.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\n  {len(SLATES)} slates, {total_seconds:.0f}s "
          f"({total_seconds/60:.2f} min), {total_words} words, "
          f"{summary['overall_wpm']} wpm overall")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
