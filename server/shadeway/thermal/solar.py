"""Solar position.

Implements the NOAA solar position algorithm (the same one behind
gml.noaa.gov/grad/solcalc/). Accurate to well under a degree over our date
range, which is far tighter than our 5-degree azimuth bins need.

# source: NOAA Global Monitoring Laboratory solar calculation equations,
#         gml.noaa.gov/grad/solcalc/calcdetails.html, read 2026-08-22;
#         reference values cross-checked against the independent Pysolar
#         implementation (0.13), agreement within 0.1 deg on test instants.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np


@dataclass(frozen=True)
class SunPosition:
    azimuth_deg: float  # compass degrees, 0 = north, increasing clockwise
    elevation_deg: float  # degrees above the horizon; negative after sunset


def _julian_day(times_utc: np.ndarray) -> np.ndarray:
    """Julian day from POSIX seconds."""
    return times_utc / 86400.0 + 2440587.5


def _solar_terms(julian_century: np.ndarray):
    geom_mean_long = np.radians(
        (280.46646 + julian_century * (36000.76983 + julian_century * 0.0003032)) % 360.0
    )
    geom_mean_anom = np.radians(
        357.52911 + julian_century * (35999.05029 - 0.0001537 * julian_century)
    )
    eccentricity = 0.016708634 - julian_century * (
        0.000042037 + 0.0000001267 * julian_century
    )
    centre = np.radians(
        np.sin(geom_mean_anom)
        * (1.914602 - julian_century * (0.004817 + 0.000014 * julian_century))
        + np.sin(2 * geom_mean_anom) * (0.019993 - 0.000101 * julian_century)
        + np.sin(3 * geom_mean_anom) * 0.000289
    )
    true_long = geom_mean_long + centre
    omega = np.radians(125.04 - 1934.136 * julian_century)
    apparent_long = true_long - np.radians(0.00569) - np.radians(0.00478) * np.sin(omega)

    mean_obliquity = np.radians(
        23.0
        + (26.0 + (21.448 - julian_century * (46.815 + julian_century
           * (0.00059 - julian_century * 0.001813))) / 60.0) / 60.0
    )
    obliquity = mean_obliquity + np.radians(0.00256) * np.cos(omega)

    declination = np.arcsin(np.sin(obliquity) * np.sin(apparent_long))

    y = np.tan(obliquity / 2.0) ** 2
    equation_of_time = 4.0 * np.degrees(
        y * np.sin(2 * geom_mean_long)
        - 2 * eccentricity * np.sin(geom_mean_anom)
        + 4 * eccentricity * y * np.sin(geom_mean_anom) * np.cos(2 * geom_mean_long)
        - 0.5 * y * y * np.sin(4 * geom_mean_long)
        - 1.25 * eccentricity * eccentricity * np.sin(2 * geom_mean_anom)
    )
    return declination, equation_of_time


def _positions(times_utc: np.ndarray, lat: float, lon: float):
    julian_day = _julian_day(times_utc)
    julian_century = (julian_day - 2451545.0) / 36525.0
    declination, equation_of_time = _solar_terms(julian_century)

    minutes_utc = (times_utc % 86400.0) / 60.0
    true_solar_time = (minutes_utc + equation_of_time + 4.0 * lon) % 1440.0
    hour_angle = np.radians(true_solar_time / 4.0 - 180.0)

    lat_rad = np.radians(lat)
    zenith = np.arccos(
        np.clip(
            np.sin(lat_rad) * np.sin(declination)
            + np.cos(lat_rad) * np.cos(declination) * np.cos(hour_angle),
            -1.0,
            1.0,
        )
    )
    elevation = 90.0 - np.degrees(zenith)

    denominator = np.cos(lat_rad) * np.sin(zenith)
    cos_azimuth = np.where(
        np.abs(denominator) < 1e-9,
        0.0,
        (np.sin(lat_rad) * np.cos(zenith) - np.sin(declination)) / denominator,
    )
    azimuth = np.degrees(np.arccos(np.clip(cos_azimuth, -1.0, 1.0)))
    # hour angle > 0 means afternoon: sun is west of the meridian
    azimuth = np.where(hour_angle > 0.0, (azimuth + 180.0) % 360.0,
                       (540.0 - azimuth) % 360.0)
    return azimuth, elevation


def sun_position(when: datetime, lat: float, lon: float) -> SunPosition:
    if when.tzinfo is None:
        raise ValueError("sun_position needs a timezone-aware datetime")
    seconds = np.array([when.astimezone(UTC).timestamp()], dtype=np.float64)
    azimuth, elevation = _positions(seconds, lat, lon)
    return SunPosition(float(azimuth[0]), float(elevation[0]))


def sun_positions(
    times: Sequence[datetime], lat: float, lon: float
) -> tuple[np.ndarray, np.ndarray]:
    seconds = np.array(
        [t.astimezone(UTC).timestamp() for t in times], dtype=np.float64
    )
    return _positions(seconds, lat, lon)
