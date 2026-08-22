from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from shadeway.thermal.solar import sun_position, sun_positions

EDT = timezone(timedelta(hours=-4))
EST = timezone(timedelta(hours=-5))
TIMES_SQUARE = (40.7580, -73.9855)

# (when, lat, lon, azimuth_deg, elevation_deg)
# SOURCE: cross-checked against the independent Pysolar 0.13 implementation
# (itself NOAA-aligned), computed 2026-08-22. Agreement between our NOAA
# implementation and Pysolar is within 0.1 deg on these instants.
REFERENCES = [
    (datetime(2025, 7, 22, 15, 0, tzinfo=EDT), *TIMES_SQUARE, 239.29, 57.59),
    (datetime(2025, 12, 21, 9, 0, tzinfo=EST), *TIMES_SQUARE, 139.33, 14.19),
    (datetime(2025, 7, 22, 8, 0, tzinfo=EDT), *TIMES_SQUARE, 83.18, 23.73),
]


@pytest.mark.parametrize("when,lat,lon,azimuth,elevation", REFERENCES)
def test_matches_reference(when, lat, lon, azimuth, elevation):
    got = sun_position(when, lat, lon)
    assert abs(got.azimuth_deg - azimuth) < 0.5
    assert abs(got.elevation_deg - elevation) < 0.5


def test_references_were_actually_filled_in():
    assert REFERENCES, (
        "look up reference values from an independent solar implementation and "
        "paste them in. an unverified solar position silently breaks every shadow."
    )


def test_sun_is_below_the_horizon_at_midnight():
    at_midnight = datetime(2025, 7, 22, 0, 30, tzinfo=EDT)
    assert sun_position(at_midnight, *TIMES_SQUARE).elevation_deg < 0


def test_sun_is_highest_around_solar_noon():
    day = [
        sun_position(datetime(2025, 7, 22, h, 0, tzinfo=EDT), *TIMES_SQUARE)
        for h in range(6, 21)
    ]
    peak = max(range(len(day)), key=lambda i: day[i].elevation_deg)
    assert 6 <= peak + 6 <= 14, "solar noon in NYC EDT is around 13:00"


def test_azimuth_sweeps_east_to_west_through_the_day():
    morning = sun_position(datetime(2025, 7, 22, 8, 0, tzinfo=EDT), *TIMES_SQUARE)
    evening = sun_position(datetime(2025, 7, 22, 18, 0, tzinfo=EDT), *TIMES_SQUARE)
    assert morning.azimuth_deg < 180.0 < evening.azimuth_deg


def test_azimuth_moves_about_fifteen_degrees_per_hour():
    """The design doc's central claim: over a 40-minute walk the sun moves
    enough to change which route wins."""
    a = sun_position(datetime(2025, 7, 22, 15, 0, tzinfo=EDT), *TIMES_SQUARE)
    b = sun_position(datetime(2025, 7, 22, 16, 0, tzinfo=EDT), *TIMES_SQUARE)
    assert 8.0 < abs(b.azimuth_deg - a.azimuth_deg) < 30.0


def test_vectorised_matches_scalar():
    times = [
        datetime(2025, 7, 22, 15, 0, tzinfo=EDT) + timedelta(minutes=5 * i)
        for i in range(8)
    ]
    az, el = sun_positions(times, *TIMES_SQUARE)
    for i, when in enumerate(times):
        one = sun_position(when, *TIMES_SQUARE)
        assert abs(az[i] - one.azimuth_deg) < 1e-6
        assert abs(el[i] - one.elevation_deg) < 1e-6
