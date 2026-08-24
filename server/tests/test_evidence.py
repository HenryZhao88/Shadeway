"""The evidence fields on a turn card, against the fixture city.

The fixture city is a synthetic grid with known building heights, so these
assert on what the evidence provider CAN prove rather than on NYC specifics.
"""

from datetime import datetime, timedelta, timezone

import pytest

from shadeway.evidence import COMMON_NAME, EvidenceProvider
from shadeway.horizon import HorizonCache
from shadeway.router.graph import Graph
from shadeway.scene import Scene
from shadeway_contracts.fixtures import write_fixture_city

EDT = timezone(timedelta(hours=-4))
AFTERNOON = datetime(2025, 7, 22, 15, 0, tzinfo=EDT)
MIDNIGHT = datetime(2025, 7, 22, 1, 0, tzinfo=EDT)


@pytest.fixture(scope="module")
def evidence(tmp_path_factory):
    data = tmp_path_factory.mktemp("evidence")
    write_fixture_city(data)
    graph = Graph.load(data)
    scene = Scene.load(data)
    return EvidenceProvider(
        graph, scene, HorizonCache(scene, graph.sample_xy),
        lat=40.7536, lon=-73.9840,
    )


def test_species_come_through_from_the_scene(evidence):
    """Naming the trees is the flagship canopy line; it needs species on the
    Scene, which is easy to drop when Scene.load is edited."""
    assert len(evidence.scene.tree_species) == len(evidence.scene.tree_xy)


def test_after_dark_nothing_is_sunlit(evidence):
    for edge_id in range(min(20, len(evidence.graph.edge_u))):
        assert evidence.sunlit_until(edge_id, MIDNIGHT) is None


def test_sunlit_until_is_in_the_future_when_it_answers(evidence):
    answered = 0
    for edge_id in range(min(60, len(evidence.graph.edge_u))):
        when = evidence.sunlit_until(edge_id, AFTERNOON)
        if when is None:
            continue
        answered += 1
        assert when > AFTERNOON
    assert answered, "no fixture edge was sunlit — the fixture city changed"


def test_sunlit_until_declines_to_answer_for_an_already_shaded_edge(evidence):
    """It is a promise about a sunny side, so it must stay silent otherwise —
    an answer here would read as 'shade ends at 4pm', the exact opposite."""
    import numpy as np

    for edge_id in range(min(60, len(evidence.graph.edge_u))):
        ids = evidence.graph.sample_ids(edge_id)
        if not len(ids):
            continue
        azimuth, elevation = evidence._sun(AFTERNOON)
        f_sun = float(np.mean(evidence.horizon.f_sun(ids, azimuth, elevation)))
        if f_sun <= 0.5:
            assert evidence.sunlit_until(edge_id, AFTERNOON) is None


def test_shaded_by_names_a_height_and_a_street_when_a_building_blocks(evidence):
    described = [
        evidence.shaded_by(edge_id, AFTERNOON)[0]
        for edge_id in range(min(80, len(evidence.graph.edge_u)))
    ]
    named = [d for d in described if d and " m " in d]
    assert named, "nothing on the fixture grid was building-shaded at 3pm"
    for description in named:
        assert "building" in description or "tower" in description


def test_shaded_by_says_nightfall_after_dark(evidence):
    description, dappled = evidence.shaded_by(0, MIDNIGHT)
    assert description == "nightfall"
    assert dappled is False


def test_common_names_are_lowercase_genus_keys():
    """genus_of()-style lookups lowercase the latin name, so a capitalised key
    here would silently never match."""
    for genus in COMMON_NAME:
        assert genus == genus.lower()
