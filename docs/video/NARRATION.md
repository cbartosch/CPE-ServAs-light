# Narration script — 7 minute demo

**423 seconds (7.04 min) · 932 words · 132.3 wpm**

## Before you record

Read for a **female voice-over**, unhurried and level. The pace is set at 138
words per minute deliberately: this material is dense with figures, and a
listener needs the gap after a number more than they need momentum. Do not
speed up to fill a shot — the shot lengths were derived from these word counts,
not the other way round, so if you deliver at pace the picture will fit.

Numbers are written as words where they are spoken, so *two hundred and twelve*
rather than *212*. That is not a stylistic choice: a TTS engine reads `$212` as
"dollar two one two" often enough to matter.

Tone: this is an internal engineering review, not a product launch. Where the
script says a result is unflattering, let it sound unflattering.

## Shots

### 01. `01_title` — in at 00:00.0, runs 19.4s

*41 words at 127 wpm*

> This is a working demonstration of end-to-end service assurance orchestration for a fixed access network, HFC and PON, across the Puerto Rico footprint. Everything you will see runs from a seed, so every figure in it can be reproduced and checked.

### 02. `02_problem` — in at 00:19.4, runs 36.8s

*81 words at 132 wpm*

> The core problem is simple to state and expensive to get wrong. A modem reporting poor performance looks much the same whether the fault is in the customer's drop, at the tap serving eight houses, or at a node serving four hundred and fifty. Each needs a different crew, and sending the wrong one costs a wasted visit. Against a published benchmark that is two hundred and twelve dollars in the metro and six hundred and fifty five on an island.

### 03. `03_footprint` — in at 00:56.2, runs 28.1s

*61 words at 130 wpm*

> The fixed footprint is Puerto Rico: seventy eight municipios, including the island municipalities of Vieques and Culebra. The U.S. Virgin Islands are modelled but excluded, because Liberty serves them for mobile while fixed broadband there sits with a separate entity. Six dispatch hubs are modelled. Their locations are assumed, from a practitioner assessment, and the bundle says so everywhere they appear.

### 04. `04_islands` — in at 01:24.3, runs 45.5s

*101 words at 133 wpm*

> Geography is not decoration here. A fault in Bayamón is twenty two minutes from its hub. Utuado is seventy five. Vieques is two hundred and fourteen, because the crew drives to Fajardo and then takes a ferry. Culebra is two hundred and sixty nine, and a round trip plus the work does not fit inside one shift, so it needs an overnight plan. An earlier version of this model billed zero travel whenever a hub sat in the same municipality as the fault. That was a genuine defect, and it was found by reading the output rather than by a test.

### 05. `05_gate` — in at 02:09.8, runs 38.6s

*85 words at 132 wpm*

> The decision architecture was chosen by the operator, not by me. Agents decide, and policy and the approval gates are the only guard. The deterministic classifier still runs on every incident, but its job changed from deciding to checking. It is the baseline the gate compares against, so any disagreement routes to a person. It is the fallback when the model is unreachable. And it is the floor: on an incident where the agent fails, the outcome is exactly what it would have been before.

### 06. `06_ab` — in at 02:48.4, runs 52.0s

*116 words at 134 wpm*

> This is the measurement that matters, and one result in it is unflattering. With a scripted model the system behaves exactly as the rules alone do, because the scripted model echoes the rules and the disagreement gate never fires. Anyone demonstrating that configuration and claiming the model contributes is mistaken. With retrieval standing in for the agent, every rules error is caught, at the cost of three false alarms in eighteen cases. And when the agent decides rather than advises, correct answers rise from fourteen of eighteen to sixteen. Gate load is a third of incidents, at roughly twenty dollars each in review time. That is cheap against a wasted visit, but it is not free.

### 07. `07_cost` — in at 03:40.4, runs 35.5s

*78 words at 132 wpm*

> The economics turn on an asymmetry. A false alarm costs about twenty dollars: an engineer reviews a case that did not need reviewing. A missed gate costs three hundred and fifty four dollars in Arecibo, and a thousand and seventy one on Culebra, where the wasted visit involves a ferry and an overnight stay. That is a factor of eighteen to fifty four. It is why a gate can be wrong quite often and still be worth having.

### 08. `08_predictive` — in at 04:15.9, runs 42.9s

*95 words at 133 wpm*

> A separate scheduled branch scans modems nightly and raises two classes of ticket: ones already breaching a threshold, and ones a trend says will breach inside a fortnight. Two numbers come out of it, and they answer different questions. The first run after deployment surfaces four hundred tickets, because everything quietly degrading appears at once. The standing daily workload is four to eleven. A modem is only flagged when the trend fit explains enough of the variance, so erratic signals are correctly ignored, and no modem with a healthy underlying cause was flagged at all.

### 09. `09_provenance` — in at 04:58.8, runs 39.4s

*87 words at 132 wpm*

> The bundle separates what is sourced from what is assumed, and it does so on the surface rather than in a footnote. Truck roll cost is published and cited. The CPE parameter names come from the Broadband Forum specifications, and the ticket and work order shapes from TM Forum. Against that, every labour rate, every hub location, every plant ratio and the entire NXT message envelope are assumed. Each panel carries a chip saying which, and that chip travels with the number when you drill into it.

### 10. `10_rigour` — in at 05:38.2, runs 45.1s

*100 words at 133 wpm*

> Four audits were run against this bundle, the last of them adversarial. It found four live breaks, and all four share one shape: a check that trusted its caller. A guard let an unrecognised fault domain through to execution because it was not in the forbidden set. A budget arrived inside the request, so the thing being guarded set its own limit. An approval token verified cleanly while a different action was performed, because nothing compared the claims to the work. And twenty nine hundred of San Juan's modelled taps shared an identifier. Each of those looked correct in isolation.

### 11. `11_close` — in at 06:23.3, runs 39.4s

*87 words at 132 wpm*

> So where does this stand. Six hundred and twenty seven tests run with no install and no network. The control tower ships as a single self-contained HTML file that needs no server. The northbound contracts for CPE, work force management and ticketing come from published specifications. What comes next is yours: replace the assumed rates and hub locations with real figures, confirm the NXT message shape against a real message, and run the integration suite, because the workflow engine remains the largest untested surface in the bundle.

## Assembly

The video ships silent. Record or synthesise the narration as a single
`narration.wav` matching the shot order, then:

```bash
ffmpeg -i LPR_CPE_demo_7min_UHD_silent.mp4 -i narration.wav \
  -c:v copy -c:a aac -b:a 192k -shortest \
  LPR_CPE_demo_7min_UHD.mp4
```

If your narration runs long, re-time rather than trimming the audio: each
shot's duration is in `narration.json`, and `generate_video_slates.py`
recomputes the timing from `TARGET_WPM`.

## What is not in this video

Eight of the ten Streamlit pages have never been rendered in any environment.
A video showing them would be fabricating screens, so it does not. The visuals
are the generated footprint map, figures the harnesses actually print, and
typeset slates. Nothing on screen is a mock-up of a page that has not run.
