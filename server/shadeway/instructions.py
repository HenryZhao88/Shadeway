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


def build(graph, path, legs) -> list[Instruction]:
    """legs is the list of LegStep already built by api.py, in walk order."""
    out: list[Instruction] = []
    if not legs:
        return out

    def at(leg, end: bool = False) -> LatLon:
        lon, lat = leg.geometry[-1 if end else 0]
        return LatLon(lat=lat, lon=lon)

    first = legs[0]
    start_side = side_name(float(graph.edge_bearing_deg[first.edge_id]), first.side)
    out.append(
        Instruction(
            type="start",
            at=at(first),
            text=(
                f"Head off along the {start_side} of {first.street_name}"
                if start_side
                else f"Head off along {first.street_name}"
            ),
        )
    )

    for previous, leg in zip(legs, legs[1:]):
        bearing = float(graph.edge_bearing_deg[leg.edge_id])
        this_side = side_name(bearing, leg.side)

        if leg.kind == EdgeKind.CROSSING:
            continue  # the crossing itself is narrated by the leg that follows it

        crossed_street = (
            previous.street_name == leg.street_name and previous.side != leg.side
        )
        if crossed_street and this_side:
            out.append(
                Instruction(
                    type="cross",
                    at=at(leg),
                    text=f"Cross to the {this_side} of {leg.street_name}",
                    why=_why(previous, leg),
                )
            )
        elif previous.street_name != leg.street_name:
            out.append(
                Instruction(
                    type="turn",
                    at=at(leg),
                    text=(
                        f"Turn onto the {this_side} of {leg.street_name}"
                        if this_side
                        else f"Turn onto {leg.street_name}"
                    ),
                    why=_why(previous, leg),
                )
            )

    out.append(Instruction(type="arrive", at=at(legs[-1], end=True), text="Arrive"))
    return out


def _why(previous, leg) -> InstructionWhy | None:
    """The evidence line under the card. This is the bit that makes people
    believe us, so populate as much of it as we honestly can."""
    delta = round(previous.feels_like_c - leg.feels_like_c, 1)
    dappled = 0.05 < leg.f_sun < 0.5
    if abs(delta) < 0.3 and not dappled:
        return None
    return InstructionWhy(
        delta_c=delta if abs(delta) >= 0.3 else None,
        shaded_by="tree canopy" if dappled else None,
        dappled=dappled,
    )
