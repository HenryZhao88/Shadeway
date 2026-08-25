---
title: shadeway
emoji: 🌳
colorFrom: blue
colorTo: yellow
sdk: docker
app_port: 8000
pinned: false
license: mit
short_description: Walking routes for New York, priced in degrees
---

# shadeway

Pedestrian routing for New York that tells you what the walk will *feel like*,
in degrees, and models the sun moving while you walk.

Two routes come back for every request. The fast one and the cool one, with the
difference stated in degrees Celsius rather than percent-shaded — because "this
route feels like 41, the cool one feels like 33" is a sentence people already
understand.

## What it actually computes

Felt temperature is **UTCI**, computed from mean radiant temperature through a
SOLWEIG-style chain. Shade comes from ray casting against real NYC building
heights and modelled tree crowns — 44,793 buildings and 62,427 street trees for
Manhattan, with per-species crown transmissivity, so the interface can tell you
a block is shaded *by honey locusts* and that you will get dappled light rather
than real shade.

Because the graph carries left and right sidewalks as separate edges, it can
also say **"cross to the east side of E 45 St"** — an instruction routing on
street centrelines cannot produce.

The sun moves while you walk. A forty-minute walk starting at 3pm ends at 3:40
under different shadows, and every edge is costed at the moment you actually
step onto it.

## The map draws its own shadows

The shadows on screen are not a lighting effect. A building is a vertical prism,
so its shadow on flat ground is its footprint swept along the anti-solar azimuth
by `height / tan(elevation)` — the same 2D model the server's ray caster uses,
run in the browser. That is why the time scrubber is instant, and why the map
and the route can never disagree about which side of a street is lit.

## Honest about its limits

`docs/model.md` in the source repo states them: which constants are cited and
which are interpolated, that buildings are identified by measured height and
fronting street rather than an address dataset we do not have, that park
entrances are derived against the pedestrian network because NYC does not
publish them, and what the shadow approximation over- and under-states.

Weather comes from Open-Meteo. No API keys anywhere.
