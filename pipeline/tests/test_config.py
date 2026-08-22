from shadeway_pipeline.config import SCOPES, SOURCE_CRS, TARGET_CRS, offset_for


def test_target_crs_is_metric():
    assert TARGET_CRS == "EPSG:32118"  # metres
    # verified live 2026-08-20: the Socrata API reprojects to lon/lat on the way
    # out, even though the attributes (streetwidth, height_roof) stay in feet
    assert SOURCE_CRS == "EPSG:4326"


def test_scopes_cover_the_spec_and_the_fallback():
    assert set(SCOPES) == {"midtown", "manhattan", "manhattan_brooklyn"}
    assert SCOPES["manhattan"].boroughs == ["1"]
    assert SCOPES["manhattan_brooklyn"].boroughs == ["1", "3"]


def test_bboxes_are_west_south_east_north_and_contain_times_square():
    for scope in SCOPES.values():
        w, s, e, n = scope.bbox_wgs84
        assert w < e and s < n
        assert w < -73.9855 < e and s < 40.7580 < n, scope.name


def test_offset_for_scales_with_street_width():
    # 70 ft avenue -> 70*0.3048/2 + 2 = 12.7 m; 30 ft side street -> 6.6 m
    assert abs(offset_for(70.0) - 12.668) < 0.01
    assert abs(offset_for(30.0) - 6.572) < 0.01
    assert offset_for(None) == 6.0
    assert offset_for(0) == 6.0
    # a 300 ft plaza clamps to the 120 ft street maximum
    assert offset_for(300.0) == offset_for(120.0)
