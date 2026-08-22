"""The 2D shade test. Twenty lines that the whole system rests on.

Buildings are vertical prisms, so "does this building block the sun" reduces to
a plan-view ray crossing and one height comparison. There is no 3D geometry here
and there does not need to be. Trees are not opaque: a beam through a crown is
attenuated by that crown's transmissivity tau, multiplied per crown.
"""

from __future__ import annotations

import numpy as np
import shapely
from shapely.geometry import LineString

from shadeway.scene import Scene

EYE_HEIGHT_M = 1.1
RAY_CAP_M = 400.0
AZIMUTH_BINS = 72
BIN_WIDTH_DEG = 360.0 / AZIMUTH_BINS


def _ray(x: float, y: float, azimuth_deg: float, length_m: float) -> LineString:
    """Azimuth is compass degrees: 0 = north (+y), 90 = east (+x)."""
    radians = np.radians(azimuth_deg)
    return LineString(
        [(x, y), (x + length_m * np.sin(radians), y + length_m * np.cos(radians))]
    )


def building_horizon_deg(scene: Scene, x: float, y: float, azimuth_deg: float) -> float:
    """Highest obstruction angle above horizontal in one direction, in degrees."""
    ray = _ray(x, y, azimuth_deg, RAY_CAP_M)
    hits = scene.building_tree.query(ray)
    if len(hits) == 0:
        return 0.0

    best = 0.0
    for index in hits:
        geom = scene.building_geoms[index]
        crossing = geom.intersection(ray)
        if crossing.is_empty:
            continue
        # nearest point of the crossing is the near face; that is what subtends
        # the largest angle for a prism of uniform height
        distance = shapely.distance(shapely.points(x, y), crossing)
        if distance <= 0.01:
            return 90.0  # we are inside the footprint
        top = float(scene.building_bases_m[index] + scene.building_heights_m[index])
        angle = np.degrees(np.arctan((top - EYE_HEIGHT_M) / distance))
        best = max(best, float(angle))
    return max(0.0, best)


def is_shaded_by_building(
    scene: Scene, x: float, y: float, azimuth_deg: float, elevation_deg: float
) -> bool:
    if elevation_deg <= 0.0:
        return True  # sun is down
    return building_horizon_deg(scene, x, y, azimuth_deg) > elevation_deg


def building_horizon_profile(
    scene: Scene, x: float, y: float, bins: int = AZIMUTH_BINS
) -> np.ndarray:
    """72 rays, one per 5 degrees. ~3 ms. This is the expensive call, and it is
    the ONLY expensive call — everything afterwards is an array lookup."""
    out = np.zeros(bins, dtype=np.uint8)
    for i in range(bins):
        angle = building_horizon_deg(scene, x, y, i * (360.0 / bins))
        out[i] = np.uint8(np.clip(round(angle), 0, 90))
    return out


# ------------------------------------------------------------------ canopy


def _tree_kdtree(scene: Scene):
    """Lazy cKDTree over trunk positions, cached on the scene object."""
    index = getattr(scene, "_kdtree", None)
    if index is None:
        from scipy.spatial import cKDTree

        index = cKDTree(scene.tree_xy) if len(scene.tree_xy) else None
        scene._kdtree = index  # noqa: SLF001 — deliberate cache slot
    return index


def _crown_geometry(scene: Scene, x: float, y: float, azimuth_deg: float):
    """Vectorised plan geometry of every nearby crown relative to a ray.

    Returns (indices, along_m, lateral_m) for trees within the ray cap,
    sorted by distance from the origin point.
    """
    index = _tree_kdtree(scene)
    if index is None:
        empty_i = np.zeros(0, dtype=np.int64)
        return empty_i, np.zeros(0), np.zeros(0)

    # prefilter to everything that could touch a 400 m ray plus crown radius
    reach = RAY_CAP_M + float(scene.tree_radius_m.max())
    candidate_ids = index.query_ball_point([x, y], reach)
    if not candidate_ids:
        empty_i = np.zeros(0, dtype=np.int64)
        return empty_i, np.zeros(0), np.zeros(0)

    ids = np.asarray(sorted(candidate_ids), dtype=np.int64)
    tx = scene.tree_xy[ids, 0] - x
    ty = scene.tree_xy[ids, 1] - y
    radians = np.radians(azimuth_deg)
    # compass azimuth: 0 = north (+y), 90 = east (+x)
    along = tx * np.sin(radians) + ty * np.cos(radians)
    lateral = np.abs(tx * np.cos(radians) - ty * np.sin(radians))
    ok = (lateral <= scene.tree_radius_m[ids]) & (along > 0.0) & (along <= RAY_CAP_M)
    return ids[ok], along[ok], lateral[ok]


def _intercepted_crown_data(
    scene: Scene, x: float, y: float, azimuth_deg: float, elevation_deg: float
):
    """(ids, along) for crowns whose height band the sun beam actually pierces."""
    if len(scene.tree_xy) == 0 or elevation_deg <= 0.0:
        empty_i = np.zeros(0, dtype=np.int64)
        return empty_i, np.zeros(0)
    ids, along, _ = _crown_geometry(scene, x, y, azimuth_deg)
    if not len(ids):
        return ids, along
    ray_height_m = EYE_HEIGHT_M + along * np.tan(np.radians(elevation_deg))
    hit = (scene.crown_base_m[ids] <= ray_height_m) & (
        ray_height_m <= scene.crown_top_m[ids]
    )
    return ids[hit], along[hit]


def _intercepted_crowns(
    scene: Scene, x: float, y: float, azimuth_deg: float, elevation_deg: float
) -> list[int]:
    """Indices of crowns the sun ray actually passes through.

    A crown is intercepted when the ray passes within crown_radius_m of the trunk
    in PLAN view AND the ray's height at that plan distance falls between
    crown_base_m and crown_top_m. Both conditions matter: skipping the height
    check means every tree on the block shades you, which is very wrong at noon.
    """
    ids, _ = _intercepted_crown_data(scene, x, y, azimuth_deg, elevation_deg)
    return [int(i) for i in ids]


def canopy_transmittance(
    scene: Scene, x: float, y: float, azimuth_deg: float, elevation_deg: float
) -> float:
    """Product of tau over every crown the beam passes through. 1.0 = open sky."""
    ids, _ = _intercepted_crown_data(scene, x, y, azimuth_deg, elevation_deg)
    if not len(ids):
        return 1.0
    return float(np.prod(scene.tau[ids]))


def f_sun(
    scene: Scene, x: float, y: float, azimuth_deg: float, elevation_deg: float
) -> float:
    """Fraction of the direct beam reaching a pedestrian. 0 behind a building,
    tau-product under canopy, 1 in the open."""
    if is_shaded_by_building(scene, x, y, azimuth_deg, elevation_deg):
        return 0.0
    return canopy_transmittance(scene, x, y, azimuth_deg, elevation_deg)


def canopy_horizon_profile(
    scene: Scene, x: float, y: float, bins: int = AZIMUTH_BINS
) -> np.ndarray:
    """Second cache layer: per bin, the highest elevation at which canopy still
    intercepts the beam. Above that angle the beam clears the crowns entirely.

    Solved directly rather than probed: a crown at along-track distance d is
    pierced while base <= eye + d·tan(h) <= top, i.e. for elevations up to
    atan((crown_top - eye)/d). One vectorised pass over nearby crowns.
    """
    out = np.zeros(bins, dtype=np.uint8)
    if len(scene.tree_xy) == 0:
        return out
    for i in range(bins):
        ids, along, _ = _crown_geometry(scene, x, y, i * (360.0 / bins))
        if not len(ids):
            continue
        highest_tan = (scene.crown_top_m[ids] - EYE_HEIGHT_M) / along
        out[i] = np.uint8(
            np.clip(round(float(np.degrees(np.arctan(highest_tan.max())))), 0, 90)
        )
    return out
