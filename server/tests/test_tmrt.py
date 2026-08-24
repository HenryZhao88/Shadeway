import inspect

import numpy as np

from shadeway.thermal import tmrt

HOT_AFTERNOON = dict(  # noqa: C408 — reads as a named parameter set
    direct_normal_wm2=799.0,
    diffuse_wm2=148.0,
    global_horizontal_wm2=712.0,
    air_temp_c=30.6,
    relative_humidity_pct=48.0,
    cloud_cover_pct=6.0,
    solar_elevation_deg=55.0,
)
NIGHT = dict(  # noqa: C408 — reads as a named parameter set
    direct_normal_wm2=0.0,
    diffuse_wm2=0.0,
    global_horizontal_wm2=0.0,
    air_temp_c=26.0,
    relative_humidity_pct=70.0,
    cloud_cover_pct=0.0,
    solar_elevation_deg=-10.0,
)


def _r(**overrides):
    return tmrt.RadiationInputs(**{**HOT_AFTERNOON, **overrides})


def _s(f_sun, svf, ground_albedo=0.15, wall_albedo=0.20):
    return tmrt.SurfaceInputs(
        f_sun=f_sun, svf=svf, ground_albedo=ground_albedo, wall_albedo=wall_albedo
    )


# ---------------------------------------------------------------- provenance

def test_every_constant_carries_a_source_comment():
    source = inspect.getsource(tmrt)
    for name in (
        "HUMAN_ABSORPTIVITY_SW",
        "HUMAN_EMISSIVITY_LW",
        "ANGULAR_WEIGHTS",
        "SUNLIT_SURFACE_BUMP_C",
        "SHADED_SURFACE_BUMP_C",
    ):
        line = next(
            row for row in source.splitlines() if row.strip().startswith(name)
        )
        assert "# source:" in line or "source:" in source.split(name)[1][:400], (
            f"{name} has no provenance comment"
        )
    assert "PLACEHOLDER" not in source, "replace placeholder constants before the demo"


def test_angular_weights_sum_to_one():
    assert abs(sum(tmrt.ANGULAR_WEIGHTS.values()) - 1.0) < 1e-6


# ------------------------------------------------------------------- physics

def test_full_sun_is_much_hotter_than_full_shade():
    sun = tmrt.tmrt_c(_r(), _s(f_sun=1.0, svf=0.8))
    shade = tmrt.tmrt_c(_r(), _s(f_sun=0.0, svf=0.8))
    assert sun - shade > 12.0, "direct beam should dominate on a clear afternoon"


def test_dappled_light_lands_between_sun_and_shade():
    sun = tmrt.tmrt_c(_r(), _s(f_sun=1.0, svf=0.6))
    dappled = tmrt.tmrt_c(_r(), _s(f_sun=0.35, svf=0.6))
    shade = tmrt.tmrt_c(_r(), _s(f_sun=0.0, svf=0.6))
    assert shade < dappled < sun


def test_honey_locust_is_hotter_than_london_plane():
    """The product claim, as a test: airy canopy gives weaker shade."""
    airy = tmrt.tmrt_c(_r(), _s(f_sun=0.35, svf=0.5))
    dense = tmrt.tmrt_c(_r(), _s(f_sun=0.15, svf=0.5))
    assert airy > dense


def test_tmrt_exceeds_air_temperature_in_full_sun():
    assert tmrt.tmrt_c(_r(), _s(1.0, 0.9)) > HOT_AFTERNOON["air_temp_c"] + 10.0


def test_at_night_open_sky_is_cooler_than_a_canyon():
    """With no sun, a high SVF radiates to cold sky; a canyon traps longwave."""
    open_sky = tmrt.tmrt_c(_r(**NIGHT), _s(f_sun=0.0, svf=0.95))
    canyon = tmrt.tmrt_c(_r(**NIGHT), _s(f_sun=0.0, svf=0.25))
    assert open_sky < canyon


def test_sky_emissivity_rises_with_cloud_cover():
    clear = tmrt.sky_emissivity(30.0, 50.0, 0.0)
    overcast = tmrt.sky_emissivity(30.0, 50.0, 100.0)
    assert 0.6 < clear < overcast <= 1.0


def test_surface_temperature_bump_is_bounded():
    sunlit = tmrt.surface_temp_c(30.0, f_sun=1.0, global_horizontal_wm2=900.0)
    shaded = tmrt.surface_temp_c(30.0, f_sun=0.0, global_horizontal_wm2=900.0)
    assert 30.0 + 8.0 <= sunlit <= 30.0 + 22.0
    assert 30.0 <= shaded <= 30.0 + 4.0


def test_bright_pavement_reflects_more_heat_at_you():
    dark = tmrt.tmrt_c(_r(), _s(0.0, 0.6, ground_albedo=0.08))
    bright = tmrt.tmrt_c(_r(), _s(0.0, 0.6, ground_albedo=0.35))
    assert bright > dark


def test_output_is_a_plausible_temperature_not_a_flux():
    value = tmrt.tmrt_c(_r(), _s(1.0, 0.8))
    assert -40.0 < value < 90.0, f"got {value} — did you forget the ^0.25 inversion?"


# ---------------------------------------------------------------- vectorised

def test_vectorised_matches_scalar():
    f_sun = np.array([0.0, 0.35, 1.0], dtype=np.float32)
    svf = np.array([0.3, 0.6, 0.9], dtype=np.float32)
    albedo = np.array([0.12, 0.20, 0.25], dtype=np.float32)
    batch = tmrt.tmrt_c_vec(_r(), f_sun, svf, albedo, wall_albedo=0.20)
    for i in range(3):
        one = tmrt.tmrt_c(
            _r(), _s(float(f_sun[i]), float(svf[i]), float(albedo[i]), 0.20)
        )
        assert abs(batch[i] - one) < 1e-3
