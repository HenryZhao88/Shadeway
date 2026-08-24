"""Cool waypoints and rest stops: a post-pass over an already-chosen route.

Deliberately NOT a constrained search. The design doc calls this the risky
feature and says to build it so it can be deleted the night before without
anything else noticing — so it takes a finished Route in and hands back
suggestions, and every other module stays unaware it exists. Delete the two
call sites in api.py and the system is exactly as it was.

The rule it implements: walk the route accumulating thermal load, and when the
load crosses a threshold, look for water or a cooling site inside a small
detour budget and offer it as an insertion.

"Thermal load" is degree-minutes above the UTCI moderate-heat-stress boundary,
which is 26 C (Broede et al. 2012, table 1 — the same categorisation the
felt-temperature number is reported on). Time spent below that boundary is not
load: a shaded stroll at 24 C never earns a rest stop, which is correct.
"""

from __future__ import annotations

import numpy as np

from shadeway_contracts.api import Instruction, LatLon, WaypointSuggestion
from shadeway_contracts.tables import AmenityKind

# UTCI category boundary: below this there is no heat stress to accumulate.
COMFORT_BASELINE_C = 26.0
# Degree-minutes of accumulated load that earn a stop. A 12-minute walk at a
# felt 33 C accumulates (33-26)*12 = 84, so this fires roughly once on a hot
# mid-length walk and not at all on a cool one.
LOAD_THRESHOLD_DM = 80.0
# Round-trip walking seconds we are willing to spend reaching one. Past this it
# is not a rest stop on the way, it is a different trip.
DETOUR_BUDGET_S = 150.0
MAX_STOPS = 2

_KIND_NOUN = {
    int(AmenityKind.DRINKING_FOUNTAIN): "drinking fountain",
    int(AmenityKind.COOLING_CENTER): "cooling site",
    int(AmenityKind.PARK_ENTRANCE): "park",
}


class AmenityIndex:
    """KD-tree over amenity positions in projected metres.

    Built once at startup from amenities.parquet. Kept here rather than in the
    router so that deleting this feature deletes the index with it.
    """

    def __init__(self, records: list[dict]) -> None:
        self.records = records
        self.xy = np.array(
            [[r["x_m"], r["y_m"]] for r in records], dtype=np.float64
        ).reshape(-1, 2)
        self._tree = None

    @classmethod
    def load(cls, data_dir) -> "AmenityIndex":
        from pathlib import Path

        from shadeway_contracts.tables import read_table

        path = Path(data_dir) / "amenities.parquet"
        if not path.exists():
            return cls([])
        return cls(read_table(path).to_pylist())

    def __len__(self) -> int:
        return len(self.records)

    def near(self, x: float, y: float, radius_m: float) -> list[tuple[int, float]]:
        """(record index, distance) for everything within radius, nearest first."""
        if not len(self.records):
            return []
        if self._tree is None:
            from scipy.spatial import cKDTree

            self._tree = cKDTree(self.xy)
        found = self._tree.query_ball_point([x, y], radius_m)
        if not found:
            return []
        distances = np.hypot(
            self.xy[found, 0] - x, self.xy[found, 1] - y
        )
        order = np.argsort(distances)
        return [(int(found[i]), float(distances[i])) for i in order]


def suggest(
    route,
    index: AmenityIndex,
    graph,
    *,
    walk_speed_ms: float = 1.35,
    load_threshold_dm: float = LOAD_THRESHOLD_DM,
    detour_budget_s: float = DETOUR_BUDGET_S,
    max_stops: int = MAX_STOPS,
) -> list[WaypointSuggestion]:
    """Suggestions for one route, in walk order.

    One pass over the legs. `route` is a fully built contracts Route; nothing
    is mutated.
    """
    if not len(index) or not route.legs:
        return []

    out: list[WaypointSuggestion] = []
    load_dm = 0.0
    used: set[int] = set()
    reach_m = detour_budget_s * walk_speed_ms / 2.0  # there and back again

    for leg_index, leg in enumerate(route.legs):
        minutes = (leg.exit_iso - leg.enter_iso).total_seconds() / 60.0
        load_dm += max(0.0, leg.feels_like_c - COMFORT_BASELINE_C) * minutes
        if load_dm < load_threshold_dm or len(out) >= max_stops:
            continue
        if leg_index == len(route.legs) - 1:
            break  # no point suggesting a stop on the doorstep

        x, y = graph.sample_xy[int(graph.sample_ids(leg.edge_id)[-1])]
        pick = next(
            (
                (record_index, distance)
                for record_index, distance in index.near(float(x), float(y), reach_m)
                if record_index not in used
            ),
            None,
        )
        if pick is None:
            continue  # nothing in range: keep accumulating and try further on
        record_index, distance = pick
        record = index.records[record_index]
        used.add(record_index)
        out.append(
            WaypointSuggestion(
                amenity_id=int(record["amenity_id"]),
                kind=int(record["kind"]),
                name=_display_name(record),
                at=LatLon(lat=float(record["lat"]), lon=float(record["lon"])),
                detour_s=float(2.0 * distance / walk_speed_ms),
                inserted_after_leg=leg_index,
            )
        )
        load_dm = 0.0  # the stop resets the accumulated load: that is its job
    return out


def rest_instructions(
    waypoints: list[WaypointSuggestion], route
) -> list[Instruction]:
    """Turn suggestions into "rest" cards, in the contract's instruction shape.

    api.py splices these in ahead of the final "arrive" card, in walk order.
    Instructions carry no leg index, so this is placement by ordering rather
    than by exact position — accurate enough for a card list, and it keeps the
    contract unchanged.
    """
    _ = route
    cards: list[Instruction] = []
    for waypoint in waypoints:
        noun = _KIND_NOUN.get(waypoint.kind, "cool spot")
        minutes = waypoint.detour_s / 60.0
        cards.append(
            Instruction(
                type="rest",
                at=waypoint.at,
                text=(
                    f"Cool off at {waypoint.name} — a {noun} "
                    f"{minutes:.0f} min out of your way"
                    if minutes >= 1.0
                    else f"Cool off at {waypoint.name} — a {noun} right here"
                ),
            )
        )
    return cards


def _display_name(record: dict) -> str:
    name = (record.get("name") or "").strip()
    if name:
        return name
    return _KIND_NOUN.get(int(record["kind"]), "cool spot").capitalize()
