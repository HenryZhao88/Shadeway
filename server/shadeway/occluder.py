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


def _geoms_array(scene: Scene) -> np.ndarray:
    """Building geometries as a numpy object array, cached on the scene."""
    arr = getattr(scene, "_geoms_array", None)
    if arr is None:
        arr = np.array(scene.building_geoms, dtype=object)
        scene._geoms_array = arr  # noqa: SLF001 — deliberate cache slot
    return arr


def building_horizon_profile(
    scene: Scene, x: float, y: float, bins: int = AZIMUTH_BINS
) -> np.ndarray:
    """72 rays, one per 5 degrees. Vectorised: one STRtree query for all rays,
    then bulk intersection/distance. This is the expensive call, and it is the
    ONLY expensive call — everything afterwards is an array lookup."""
    angles = np.arange(bins) * (360.0 / bins)
    radians = np.radians(angles)
    xs = x + RAY_CAP_M * np.sin(radians)
    ys = y + RAY_CAP_M * np.cos(radians)
    rays = shapely.linestrings(
        np.column_stack([np.full(bins, x), np.full(bins, y), xs, ys]).reshape(
            bins, 2, 2
        )
    )
    hits = scene.building_tree.query(rays)  # (2, k): ray index, geom index
    if hits.size == 0:
        return np.zeros(bins, dtype=np.uint8)

    ray_idx, geom_idx = hits
    crossings = shapely.intersection(rays[ray_idx], _geoms_array(scene)[geom_idx])
    nonempty = ~shapely.is_empty(crossings)
    if not nonempty.any():
        return np.zeros(bins, dtype=np.uint8)
    ray_idx, crossings = ray_idx[nonempty], crossings[nonempty]
    geom_idx = geom_idx[nonempty]

    origin = shapely.points(np.full(len(crossings), x), np.full(len(crossings), y))
    distance = np.asarray(shapely.distance(origin, crossings))
    tops = (
        scene.building_bases_m[geom_idx] + scene.building_heights_m[geom_idx]
    ).astype(np.float64)
    inside = distance <= 0.01  # we are inside the footprint: blocked fully
    with np.errstate(divide="ignore", invalid="ignore"):
        angle = np.where(
            inside,
            90.0,
            np.degrees(np.arctan((tops - EYE_HEIGHT_M) / np.where(inside, 1.0, distance))),
        )

    best = np.zeros(bins, dtype=np.float64)
    np.maximum.at(best, ray_idx, angle)
    return np.clip(np.rint(best), 0, 90).astype(np.uint8)


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


def _crown_geometry_all_bins(scene: Scene, x: float, y: float, bins: int = AZIMUTH_BINS):
    """(ids, along[N, bins], lateral[N, bins]) for every tree within reach of
    any of the bin rays — one KD query, one vectorised rotation."""
    index = _tree_kdtree(scene)
    if index is None:
        return np.zeros(0, dtype=np.int64), np.zeros((0, bins)), np.zeros((0, bins))

    reach = RAY_CAP_M + float(scene.tree_radius_m.max())
    candidate_ids = index.query_ball_point([x, y], reach)
    if not candidate_ids:
        return np.zeros(0, dtype=np.int64), np.zeros((0, bins)), np.zeros((0, bins))

    ids = np.asarray(sorted(candidate_ids), dtype=np.int64)
    tx = scene.tree_xy[ids, 0] - x
    ty = scene.tree_xy[ids, 1] - y
    angles = np.radians(np.arange(bins) * (360.0 / bins))
    sin_a = np.sin(angles)[None, :]
    cos_a = np.cos(angles)[None, :]
    along = tx[:, None] * sin_a + ty[:, None] * cos_a            # (N, bins)
    lateral = np.abs(tx[:, None] * cos_a - ty[:, None] * sin_a)  # (N, bins)
    in_view = (
        (lateral <= scene.tree_radius_m[ids][:, None])
        & (along > 0.0)
        & (along <= RAY_CAP_M)
    )
    return ids, along, np.where(in_view, lateral, np.inf)


def canopy_horizon_profile(
    scene: Scene, x: float, y: float, bins: int = AZIMUTH_BINS
) -> np.ndarray:
    """Second cache layer: per bin, the highest elevation at which canopy still
    intercepts the beam. Above that angle the beam clears the crowns entirely.

    Solved directly rather than probed: a crown at along-track distance d is
    pierced while base <= eye + d·tan(h) <= top, i.e. for elevations up to
    atan((crown_top - eye)/d). One vectorised pass over nearby crowns.

    Only crowns the ray actually passes through may contribute: `lateral` is
    inf where the plan-view test fails, and unmasked candidates would poison
    every bin — a tree 50 m to the side (or behind) would otherwise report a
    ~90 degree canopy horizon in directions it cannot shade.
    """
    out = np.zeros(bins, dtype=np.uint8)
    ids, along, lateral = _crown_geometry_all_bins(scene, x, y, bins)
    if not len(ids):
        return out
    highest_tan = (scene.crown_top_m[ids][:, None] - EYE_HEIGHT_M) / np.maximum(
        along, 0.01
    )
    highest_tan = np.where(np.isfinite(lateral), highest_tan, -np.inf)
    best = np.degrees(np.arctan(highest_tan.max(axis=0)))
    return np.clip(np.rint(best), 0, 90).astype(np.uint8)


def tau_profile(
    scene: Scene, x: float, y: float, elevation_deg: float = 30.0,
    bins: int = AZIMUTH_BINS,
) -> np.ndarray:
    """Tau product per azimuth bin at a given beam elevation.

    Approximation, deliberate: tau depends only on WHICH crowns the beam
    crosses, and for a given azimuth that set barely changes with elevation
    once inside the crown's height band; the height band itself is carried by
    the canopy horizon layer. Noted in docs/model.md.
    """
    ones = np.ones(bins, dtype=np.float32)
    if len(scene.tree_xy) == 0 or elevation_deg <= 0.0:
        return ones
    ids, along, lateral = _crown_geometry_all_bins(scene, x, y, bins)
    if not len(ids):
        return ones
    ray_height = EYE_HEIGHT_M + along * np.tan(np.radians(elevation_deg))
    in_band = (
        (scene.crown_base_m[ids][:, None] <= ray_height)
        & (ray_height <= scene.crown_top_m[ids][:, None])
    )
    hit = in_band & np.isfinite(lateral)
    log_tau = np.where(hit, np.log(np.maximum(scene.tau[ids][:, None], 1e-6)), 0.0)
    with np.errstate(divide="ignore"):
        return np.exp(log_tau.sum(axis=0)).astype(np.float32).clip(0.0, 1.0)
