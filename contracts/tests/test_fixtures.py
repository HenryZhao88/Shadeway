import numpy as np
import pyarrow.parquet as pq
import pytest

from shadeway_contracts.fixtures import build_fixture_city, write_fixture_city
from shadeway_contracts.tables import (
    ALL_TABLES,
    EdgeKind,
    Side,
    read_table,
    validate_table,
)


@pytest.fixture(scope="module")
def city():
    return build_fixture_city()


def test_every_table_conforms(city):
    assert set(city) == set(ALL_TABLES)
    for name, table in city.items():
        validate_table(name, table)


def test_is_deterministic():
    a = build_fixture_city(seed=7)["trees"].to_pydict()
    b = build_fixture_city(seed=7)["trees"].to_pydict()
    assert a == b


def test_sidewalks_come_in_left_right_pairs(city):
    edges = city["edges"].to_pydict()
    sidewalks = [
        (p, s)
        for p, s, k in zip(edges["physical_id"], edges["side"], edges["kind"])
        if k == EdgeKind.SIDEWALK
    ]
    by_parent: dict[int, set[int]] = {}
    for parent, side in sidewalks:
        by_parent.setdefault(parent, set()).add(side)
    assert by_parent
    assert all(sides == {Side.LEFT, Side.RIGHT} for sides in by_parent.values())


def test_crossings_exist_and_have_no_side(city):
    edges = city["edges"].to_pydict()
    crossings = [
        s for s, k in zip(edges["side"], edges["kind"]) if k == EdgeKind.CROSSING
    ]
    assert len(crossings) > 0
    assert set(crossings) == {Side.NONE}


def test_graph_is_one_connected_component(city):
    edges = city["edges"].to_pydict()
    nodes = set(city["nodes"].to_pydict()["node_id"])
    adj: dict[int, set[int]] = {n: set() for n in nodes}
    for u, v in zip(edges["u"], edges["v"]):
        adj[u].add(v)
        adj[v].add(u)
    seen = {next(iter(nodes))}
    stack = list(seen)
    while stack:
        cur = stack.pop()
        for nxt in adj[cur] - seen:
            seen.add(nxt)
            stack.append(nxt)
    assert seen == nodes


def test_sample_ranges_tile_the_samples_table_exactly(city):
    edges = city["edges"].to_pydict()
    n_samples = city["samples"].num_rows
    covered = np.zeros(n_samples, dtype=bool)
    for start, count in zip(edges["sample_start"], edges["sample_count"]):
        assert count >= 2  # at minimum both endpoints
        assert not covered[start : start + count].any(), "sample ranges overlap"
        covered[start : start + count] = True
    assert covered.all(), "some samples belong to no edge"


def test_samples_are_about_ten_metres_apart(city):
    edges = city["edges"].to_pydict()
    samples = city["samples"].to_pydict()
    xs = np.asarray(samples["x_m"])
    ys = np.asarray(samples["y_m"])
    for start, count in zip(edges["sample_start"], edges["sample_count"]):
        sl = slice(start, start + count)
        step = np.hypot(np.diff(xs[sl]), np.diff(ys[sl]))
        assert step.max() <= 10.5, "sample spacing exceeds the 10 m contract"


def test_buildings_are_tall_enough_to_cast_shade(city):
    heights = np.asarray(city["buildings"].to_pydict()["height_m"])
    assert heights.min() > 3.0
    assert heights.max() > 60.0  # at least one real occluder


def test_trees_have_sourced_transmissivity(city):
    trees = city["trees"].to_pydict()
    assert all(0.0 < t < 1.0 for t in trees["tau"])
    assert all(src for src in trees["tau_source"])


def test_write_fixture_city_round_trips(tmp_path):
    write_fixture_city(tmp_path)
    for name in ALL_TABLES:
        table = read_table(tmp_path / f"{name}.parquet")
        assert table.num_rows > 0
        assert pq.read_metadata(tmp_path / f"{name}.parquet").num_rows == table.num_rows


def test_crossings_join_two_real_nodes():
    """A crossing must be an edge you can actually walk.

    The fixture city used to give each intersection one node, which made every
    crossing a `u == v` self-loop — a dead edge no path could ever use, and a
    topology real NYC data does not have. That divergence meant the flagship
    side-of-street mechanic was only ever exercised against the real graph.
    """
    edges = build_fixture_city()["edges"].to_pydict()
    crossings = [
        i for i, kind in enumerate(edges["kind"]) if kind == int(EdgeKind.CROSSING)
    ]
    assert crossings, "the fixture city has no crossings in it"
    for i in crossings:
        assert edges["u"][i] != edges["v"][i], "crossing is a self-loop"
        assert edges["length_m"][i] > 1.0, "crossing has no length to walk"


def test_no_edge_anywhere_is_a_self_loop():
    edges = build_fixture_city()["edges"].to_pydict()
    assert not [
        i for i, (u, v) in enumerate(zip(edges["u"], edges["v"])) if u == v
    ]


def test_the_two_sides_of_a_street_do_not_share_endpoints():
    """If they did, a router could change sides for free and the crossing edge
    would never be worth taking."""
    edges = build_fixture_city()["edges"].to_pydict()
    by_parent: dict[int, list[int]] = {}
    for i, kind in enumerate(edges["kind"]):
        if kind != int(EdgeKind.SIDEWALK):
            continue
        by_parent.setdefault(edges["physical_id"][i], []).append(i)

    pairs = [ids for ids in by_parent.values() if len(ids) == 2]
    assert pairs, "no street in the fixture has two sides"
    for left, right in pairs:
        assert {edges["u"][left], edges["v"][left]} != {
            edges["u"][right],
            edges["v"][right],
        }, "both sides of a street share their endpoints"
