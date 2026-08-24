import pytest

from shadeway.router.graph import Graph
from shadeway_contracts.fixtures import write_fixture_city


@pytest.fixture(scope="module")
def graph(tmp_path_factory) -> Graph:
    data = tmp_path_factory.mktemp("g")
    write_fixture_city(data)
    return Graph.load(data)


def test_arrays_are_flat_and_aligned(graph):
    n = len(graph.edge_u)
    for array in (graph.edge_v, graph.edge_kind, graph.edge_side,
                  graph.edge_length_m, graph.sample_start, graph.sample_count):
        assert len(array) == n


def test_adjacency_is_csr_and_covers_every_node(graph):
    assert len(graph.adj_offsets) == graph.n_nodes + 1
    assert graph.adj_offsets[0] == 0
    assert graph.adj_offsets[-1] == len(graph.adj_edges)


def test_neighbours_are_reachable_both_ways(graph):
    """Sidewalks are undirected for a pedestrian."""
    edge = 0
    u, v = int(graph.edge_u[edge]), int(graph.edge_v[edge])
    assert edge in graph.neighbours(u)
    assert edge in graph.neighbours(v)


def test_nearest_node_finds_something_close(graph):
    lon, lat = graph.node_lonlat[5]
    assert graph.nearest_node(float(lon) + 1e-5, float(lat) + 1e-5) == 5


def test_sample_ranges_are_within_bounds(graph):
    assert (graph.sample_start + graph.sample_count).max() <= graph.n_samples
