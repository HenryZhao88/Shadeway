import pytest

from shadeway.instructions import side_name


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
