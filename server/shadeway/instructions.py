"""Turn a routed path into human instructions, including the side-of-street call.

"Cross to the east side of 5th Ave at 42nd" is a sentence Google Maps
structurally cannot produce, because it routes on street centerlines. We can,
because the graph has per-side edges. This module is where that turns into words.
"""

from __future__ import annotations

from shadeway_contracts.api import Instruction, InstructionWhy, LatLon
from shadeway_contracts.tables import EdgeKind, Side

_COMPASS = ["north", "north-east", "east", "south-east",
            "south", "south-west", "west", "north-west"]


def side_name(bearing_deg: float, side: int) -> str:
    """Which compass side of the street this edge is on.

    Left of travel is 90 degrees counter-clockwise from the bearing; right is 90
    clockwise. Naming the compass direction rather than left/right is what makes
    the instruction actionable — a pedestrian knows which side of 5th Ave is
    east, but not which side is 'left' without knowing which way they face.
    """
    if side == Side.NONE:
        return ""
    offset = -90.0 if side == Side.LEFT else 90.0
    heading = (bearing_deg + offset) % 360.0
    index = int((heading + 22.5) // 45.0) % 8
    return f"{_COMPASS[index]} side"


def build(graph, path, legs, evidence=None) -> list[Instruction]:
    """legs is the list of LegStep already built by api.py, in walk order.

    `evidence` is an optional EvidenceProvider. Without one the cards still
    carry the temperature delta, which is the load-bearing half; with one they
    also name what is doing the shading and how long the sunny side stays
    sunny. It is optional so this module stays testable with no scene loaded.

    Crossing legs sit between the two sides of a street (and between the two
    streets at every junction), so narration compares each sidewalk leg with
    the LAST SIDEWALK leg rather than its immediate predecessor — otherwise the
    flagship cross card is unreachable and every intersection spawns a bogus
    turn card.
    """
    out: list[Instruction] = []
    if not legs:
        return out

    def at(leg, end: bool = False) -> LatLon:
        lon, lat = leg.geometry[-1 if end else 0]
        return LatLon(lat=lat, lon=lon)

    def narrate(leg) -> tuple[str, int]:  # (street, side) of a sidewalk leg
        return leg.street_name, int(leg.side)

    first = next((leg for leg in legs if leg.kind != EdgeKind.CROSSING), None)
    if first is None:  # degenerate: nothing but crossings
        first = legs[0]
    start_side = side_name(float(graph.edge_bearing_deg[first.edge_id]), first.side)
    out.append(
        Instruction(
            type="start",
            at=at(legs[0]),
            text=(
                f"Head off along the {start_side} of {first.street_name}"
                if start_side
                else f"Head off along {first.street_name}"
            ),
        )
    )

    last_sidewalk = first if first.kind != EdgeKind.CROSSING else None
    for leg in legs:
        if leg.kind == EdgeKind.CROSSING or leg is first:
            continue  # a crossing is narrated by the sidewalk leg that follows it

        bearing = float(graph.edge_bearing_deg[leg.edge_id])
        this_side = side_name(bearing, leg.side)

        if last_sidewalk is not None and (
            last_sidewalk.street_name == leg.street_name
            and last_sidewalk.side != leg.side
        ):
            out.append(
                Instruction(
                    type="cross",
                    at=at(leg),
                    text=f"Cross to the {this_side} of {leg.street_name}",
                    why=_why(last_sidewalk, leg, evidence),
                )
            )
        elif last_sidewalk is None or last_sidewalk.street_name != leg.street_name:
            out.append(
                Instruction(
                    type="turn",
                    at=at(leg),
                    text=(
                        f"Turn onto the {this_side} of {leg.street_name}"
                        if this_side
                        else f"Turn onto {leg.street_name}"
                    ),
                    why=(
                        _why(last_sidewalk, leg, evidence)
                        if last_sidewalk is not None
                        else None
                    ),
                )
            )
        # same street, same side: straight through an intersection — no card
        last_sidewalk = leg

    out.append(Instruction(type="arrive", at=at(legs[-1], end=True), text="Arrive"))
    return out


def _why(previous, leg, evidence=None) -> InstructionWhy | None:
    """The evidence line under the card. This is the bit that makes people
    believe us, so populate as much of it as we honestly can.

    Three fields, three different questions:
      delta_c            how much cooler the side we are moving to is
      sunlit_until_iso   how long the side we are LEAVING stays in the sun —
                         only meaningful when we are leaving a sunlit side, and
                         it is the reason to cross now rather than later
      shaded_by          what is shading the side we are moving TO
    """
    delta = round(previous.feels_like_c - leg.feels_like_c, 1)
    dappled = 0.05 < leg.f_sun < 0.5
    shaded_by = "tree canopy" if dappled else None
    sunlit_until = None

    if evidence is not None:
        if leg.f_sun < 0.5:
            named, named_dappled = evidence.shaded_by(leg.edge_id, leg.enter_iso)
            if named:
                shaded_by, dappled = named, named_dappled
        if previous.f_sun > 0.5:
            sunlit_until = evidence.sunlit_until(previous.edge_id, previous.enter_iso)

    if abs(delta) < 0.3 and not dappled and shaded_by is None and sunlit_until is None:
        return None
    return InstructionWhy(
        delta_c=delta if abs(delta) >= 0.3 else None,
        shaded_by=shaded_by,
        sunlit_until_iso=sunlit_until,
        dappled=dappled,
    )
