from pathlib import Path

from shadeway_contracts.export_ts import render_types

WEB_TYPES = Path(__file__).resolve().parents[2] / "web" / "src" / "api" / "types.ts"


def test_every_model_is_exported():
    ts = render_types()
    for name in (
        "LatLon", "HeatProfile", "RouteRequest", "WeatherSnapshot", "FeelsLike",
        "Exposure", "LegStep", "InstructionWhy", "Instruction", "WaypointSuggestion",
        "Route", "FrontierPoint", "RouteResponse", "TimeseriesResponse",
        "DepartureCurveResponse", "PlantRequest", "PlantResponse",
    ):
        assert f"export interface {name} " in ts


def test_optional_fields_are_nullable_not_missing():
    ts = render_types()
    assert "shaded_by: string | null;" in ts


def test_datetimes_are_iso_strings():
    ts = render_types()
    assert "depart_iso: string;" in ts


def test_checked_in_file_is_not_stale():
    assert WEB_TYPES.read_text() == render_types(), (
        "web/src/api/types.ts is stale — run `make types`"
    )
