from datetime import datetime, timedelta, timezone

import pytest

from shadeway.instructions import build, side_name
from shadeway_contracts.api import LegStep
from shadeway_contracts.tables import EdgeKind

EDT = timezone(timedelta(hours=-4))


class _FakeGraph:
    """build() reads edge_bearing_deg[edge_id]; nothing else."""

    def __init__(self, bearings):
        self.edge_bearing_deg = list(bearings)


def _leg(edge_id, name, side, kind=EdgeKind.SIDEWALK, feels=35.0, f_sun=0.3):
    coords = [(-73.9840, 40.7536), (-73.9840, 40.7546)]
    return LegStep(
        edge_id=edge_id, street_name=name, side=int(side), kind=int(kind),
        geometry=coords, length_m=100.0,
        enter_iso=datetime(2025, 7, 22, 15, 0, tzinfo=EDT),
        exit_iso=datetime(2025, 7, 22, 15, 1, tzinfo=EDT),
        feels_like_c=feels, tmrt_c=feels + 8.0, f_sun=f_sun, svf=0.5,
    )


@pytest.mark.parametrize(
    "bearing_deg,side,expected",
    [
        (0.0, 0, "west side"),  # heading north, left is west
        (0.0, 1, "east side"),  # heading north, right is east
        (90.0, 0, "north side"),  # heading east, left is north
        (90.0, 1, "south side"),
        (180.0, 0, "east side"),  # heading south, left is east
        (270.0, 1, "north side"),
    ],
)
def test_side_names_are_compass_directions_not_left_right(bearing_deg, side, expected):
    """'Cross to the east side' is a sentence a New Yorker can act on.
    'Cross to the left side' is not."""
    assert side_name(bearing_deg, side) == expected


def test_a_crossing_has_no_side_name():
    assert side_name(0.0, -1) == ""


def _types(instructions):
    return [i.type for i in instructions]


def test_switching_sides_of_one_street_is_a_cross_not_a_turn():
    """Real paths always have a crossing edge between the two sides of a street;
    the cross card must look past it to the last sidewalk leg."""
    legs = [
        _leg(0, "5th Avenue", 0),                              # west/left side
        _leg(1, "5th Avenue / E 42nd Street", -1, EdgeKind.CROSSING),
        _leg(2, "5th Avenue", 1),                              # east/right side
    ]
    out = build(_FakeGraph([0.0, 0.0, 0.0]), None, legs)
    assert _types(out) == ["start", "cross", "arrive"]
    cross = out[1]
    assert cross.text == "Cross to the east side of 5th Avenue"


def test_continuing_straight_through_an_intersection_is_not_narrated():
    legs = [
        _leg(0, "5th Avenue", 0),
        _leg(1, "5th Avenue / E 42nd Street", -1, EdgeKind.CROSSING),
        _leg(2, "5th Avenue", 0),
    ]
    out = build(_FakeGraph([0.0, 0.0, 0.0]), None, legs)
    assert _types(out) == ["start", "arrive"], (
        "walking two blocks of the same avenue on the same side produces no "
        "per-intersection cards"
    )


def test_a_genuine_street_change_is_a_turn():
    legs = [
        _leg(0, "5th Avenue", 0),
        _leg(1, "5th Avenue / E 42nd Street", -1, EdgeKind.CROSSING),
        _leg(2, "E 42nd Street", 1),
    ]
    out = build(_FakeGraph([0.0, 90.0, 90.0]), None, legs)
    types = _types(out)
    assert "turn" in types and "cross" not in types
    turn = out[types.index("turn")]
    assert turn.text.startswith("Turn onto")


def test_consecutive_crossings_at_a_junction_are_transparent():
    legs = [
        _leg(0, "5th Avenue", 0),
        _leg(1, "5th Avenue / E 42nd Street", -1, EdgeKind.CROSSING),
        _leg(2, "E 42nd Street / 5th Avenue", -1, EdgeKind.CROSSING),
        _leg(3, "5th Avenue", 1),
    ]
    out = build(_FakeGraph([0.0, 90.0, 90.0, 0.0]), None, legs)
    assert _types(out) == ["start", "cross", "arrive"]
