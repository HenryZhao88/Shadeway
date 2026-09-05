import pyarrow as pa
import pytest

from shadeway_contracts.tables import (
    ALL_TABLES,
    CRS_EPSG,
    EDGES,
    EdgeKind,
    SchemaError,
    Side,
    validate_table,
)


def test_crs_is_metric_state_plane():
    assert CRS_EPSG == 32118  # NAD83 / New York Long Island, metres


def test_every_table_is_registered():
    assert set(ALL_TABLES) == {
        "nodes",
        "edges",
        "samples",
        "buildings",
        "trees",
        "amenities",
    }


def test_edge_schema_carries_units_in_names():
    for field in EDGES:
        if field.type in (pa.float32(), pa.float64()):
            assert field.name.endswith(("_m", "_c", "_deg", "_s")), field.name


def test_edges_index_into_samples_contiguously():
    # sample_start/sample_count is how the horizon cache indexes without a join
    names = [f.name for f in EDGES]
    assert "sample_start" in names
    assert "sample_count" in names


def test_side_is_signed_so_crossings_can_be_none():
    assert Side.NONE == -1
    assert Side.LEFT == 0
    assert Side.RIGHT == 1
    assert EdgeKind.SIDEWALK == 0
    assert EdgeKind.CROSSING == 1


def test_validate_table_accepts_an_empty_conforming_table():
    validate_table("edges", EDGES.empty_table())


def test_validate_table_reports_all_problems_at_once():
    wrong = pa.table({"edge_id": pa.array([], type=pa.int64())})
    with pytest.raises(SchemaError) as exc:
        validate_table("edges", wrong)
    msg = str(exc.value)
    assert "edge_id" in msg  # wrong type
    assert "length_m" in msg  # missing column


def test_required_columns_reject_null_values_even_with_matching_arrow_types():
    from shadeway_contracts.fixtures import build_fixture_city

    table = build_fixture_city()["edges"].slice(0, 1)
    table = table.set_column(
        table.schema.get_field_index("u"), "u", pa.array([None], type=pa.uint32())
    )
    with pytest.raises(SchemaError, match="u.*null"):
        validate_table("edges", table)


def test_nullable_columns_still_allow_missing_values():
    from shadeway_contracts.fixtures import build_fixture_city

    table = build_fixture_city()["edges"].slice(0, 1)
    table = table.set_column(
        table.schema.get_field_index("width_m"), "width_m", pa.array([None], type=pa.float32())
    )
    validate_table("edges", table)
