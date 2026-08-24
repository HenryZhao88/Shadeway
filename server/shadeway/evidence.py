"""The evidence line under a turn card: what is shading this, and until when.

"Cross to the east side of 5th Ave — the west side is in full sun until 6:40,
the east side is under the 158 m tower on 5th Ave, about 5 degrees between
them." Everything in that sentence except the delta is computed here.

Two honest limitations, stated here and in docs/model.md rather than papered
over in the UI:

  * Buildings have no names. NYC Building Footprints carries BIN and height,
    not an address (`name` is null for essentially every footprint), and we do
    not load PLUTO. So a blocking building is identified by what we can
    actually prove about it — its measured roof height and the street it
    fronts — never by an address we would be inventing.

  * `sunlit_until` scans forward in discrete steps, so it answers to the step,
    not to the second. It is a headline, not an ephemeris.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import shapely

from shadeway import occluder
from shadeway.thermal.solar import sun_position

# Latin genus -> what a person would call it. Only the genera that actually
# appear in quantity in the NYC street tree census are worth naming; anything
# else falls back to the honest generic.
COMMON_NAME: dict[str, str] = {
    "gleditsia": "honey locust",
    "platanus": "London plane",
    "pyrus": "Callery pear",
    "quercus": "oak",
    "acer": "maple",
    "tilia": "linden",
    "celtis": "hackberry",
    "zelkova": "zelkova",
    "ulmus": "elm",
    "ginkgo": "ginkgo",
    "prunus": "cherry",
    "styphnolobium": "Japanese pagoda tree",
    "sophora": "Japanese pagoda tree",
    "fraxinus": "ash",
    "betula": "birch",
}

SUNLIT_THRESHOLD = 0.5  # mean f_sun above this is "in the sun"
SHADED_THRESHOLD = 0.5  # ...and below it is "shaded"
DAPPLED_BAND = (0.05, 0.5)  # canopy shade lets a little through; walls do not
SCAN_STEP_MINUTES = 5
SCAN_HOURS = 6
TOWER_HEIGHT_M = 60.0  # above this, call it a tower; below, a building


class EvidenceProvider:
    """Answers the two questions a turn card needs. Cheap: everything below is
    a horizon-cache lookup or one ray, never a re-route."""

    def __init__(self, graph, scene, horizon, lat: float, lon: float) -> None:
        self.graph = graph
        self.scene = scene
        self.horizon = horizon
        self.lat = lat
        self.lon = lon
        self._street_index = None

    # ---------------------------------------------------------------- sun

    def _sun(self, when: datetime) -> tuple[float, float]:
        position = sun_position(when, self.lat, self.lon)
        return position.azimuth_deg, position.elevation_deg

    def sunlit_until(self, edge_id: int, from_time: datetime) -> datetime | None:
        """When this stretch of sidewalk stops being in the sun.

        Steps forward over the horizon cache, which is exactly the operation
        the cache was built to make free — no rays are cast here at all. Returns
        None if the edge is not in the sun to begin with, or if it stays sunlit
        past the scan window (in which case there is no headline to give).
        """
        ids = self.graph.sample_ids(edge_id)
        if not len(ids):
            return None
        if self._mean_f_sun(ids, from_time) <= SUNLIT_THRESHOLD:
            return None  # already shaded: nothing to promise

        steps = int(SCAN_HOURS * 60 / SCAN_STEP_MINUTES)
        for step in range(1, steps + 1):
            at = from_time + timedelta(minutes=step * SCAN_STEP_MINUTES)
            if self._mean_f_sun(ids, at) <= SUNLIT_THRESHOLD:
                return at
        return None

    def _mean_f_sun(self, ids: np.ndarray, when: datetime) -> float:
        azimuth, elevation = self._sun(when)
        return float(np.mean(self.horizon.f_sun(ids, azimuth, elevation)))

    # ------------------------------------------------------------ shading

    def shaded_by(self, edge_id: int, when: datetime) -> tuple[str | None, bool]:
        """(description, dappled) for whatever is keeping this edge cool.

        Buildings win over canopy when both apply, because an opaque wall is
        the stronger claim and the one a pedestrian can verify by looking up.
        """
        ids = self.graph.sample_ids(edge_id)
        if not len(ids):
            return None, False
        azimuth, elevation = self._sun(when)
        if elevation <= 0.0:
            return "nightfall", False

        mid = int(ids[len(ids) // 2])
        x, y = self.graph.sample_xy[mid]

        building = self._blocking_building(float(x), float(y), azimuth, elevation)
        if building is not None:
            return self._describe_building(building), False

        crowns = occluder._intercepted_crown_data(  # same package, one helper
            self.scene, float(x), float(y), azimuth, elevation
        )[0]
        if len(crowns):
            f_sun = float(np.mean(self.horizon.f_sun(ids, azimuth, elevation)))
            dappled = DAPPLED_BAND[0] < f_sun < DAPPLED_BAND[1]
            return self._describe_canopy(crowns), dappled
        return None, False

    def _blocking_building(
        self, x: float, y: float, azimuth_deg: float, elevation_deg: float
    ) -> int | None:
        """Index of the building whose roofline the sun is actually behind.

        Same 2D test as occluder.building_horizon_deg — one ray, one height
        comparison per hit — but it keeps the identity of the winner instead of
        collapsing to an angle.
        """
        ray = occluder._ray(  # same package, one geometry helper
            x, y, azimuth_deg, occluder.RAY_CAP_M
        )
        hits = self.scene.building_tree.query(ray)
        best_index, best_angle = None, elevation_deg
        for index in hits:
            geom = self.scene.building_geoms[index]
            crossing = geom.intersection(ray)
            if crossing.is_empty:
                continue
            distance = float(shapely.distance(shapely.points(x, y), crossing))
            if distance <= 0.01:
                continue  # standing inside a footprint: not a useful answer
            top = float(
                self.scene.building_bases_m[index]
                + self.scene.building_heights_m[index]
            )
            angle = float(
                np.degrees(np.arctan((top - occluder.EYE_HEIGHT_M) / distance))
            )
            if angle > best_angle:
                best_index, best_angle = int(index), angle
        return best_index

    def _describe_building(self, index: int) -> str:
        height = float(
            self.scene.building_bases_m[index] + self.scene.building_heights_m[index]
        )
        noun = "tower" if height >= TOWER_HEIGHT_M else "building"
        street = self._street_near(self.scene.building_geoms[index])
        if street:
            return f"the {height:.0f} m {noun} on {street}"
        return f"a {height:.0f} m {noun}"

    def _describe_canopy(self, crown_ids: np.ndarray) -> str:
        """Name the trees. This is the line no other shade router can say."""
        names: list[str] = []
        species = self.scene.tree_species
        for crown in crown_ids:
            index = int(crown)
            if index >= len(species):
                continue
            genus = (species[index] or "").strip().split(" ")[0].lower()
            common = COMMON_NAME.get(genus)
            if common:
                names.append(common)
        if not names:
            return "tree canopy"
        # the dominant species on this stretch, not a list nobody will read
        dominant = max(set(names), key=names.count)
        plural = dominant if dominant.endswith("s") else f"{dominant}s"
        return f"{plural} overhead"

    # ------------------------------------------------------------- streets

    def _street_near(self, geom) -> str:
        """The street a footprint fronts, from the nearest graph sample point.

        The graph already covers every sidewalk in the city at 10 m spacing, so
        the nearest sample to a building is a good proxy for the street it
        addresses, and it costs one KD query.
        """
        if self._street_index is None:
            from scipy.spatial import cKDTree

            self._street_index = cKDTree(self.graph.sample_xy)
        centroid = geom.centroid
        _, sample = self._street_index.query([centroid.x, centroid.y])
        edge_id = self._edge_of_sample(int(sample))
        if edge_id is None:
            return ""
        return (self.graph.street_names[edge_id] or "").strip()

    def _edge_of_sample(self, sample_id: int) -> int | None:
        """Which edge owns a sample id. Samples are contiguous per edge, so a
        binary search over the start offsets answers it."""
        starts = self.graph.sample_start
        index = int(np.searchsorted(starts, sample_id, side="right")) - 1
        if index < 0 or index >= len(starts):
            return None
        if sample_id >= starts[index] + self.graph.sample_count[index]:
            return None
        return index
