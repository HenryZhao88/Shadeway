import { describe, expect, test } from 'vitest';

import { INITIAL_VIEW } from '../map/basemapStyle';
import {
  BUILDING_DETAIL_ZOOM,
  bboxFor,
  buildingLevels,
  fitRoute,
  renderBudget,
  type ViewState,
} from '../map/camera';

const OVERVIEW: ViewState = {
  longitude: -73.9812,
  latitude: 40.745,
  zoom: 13,
  pitch: 40,
  bearing: 0,
};

describe('map camera building policy', () => {
  test('keeps overview buildings visible until exact detail is ready', () => {
    const overview = ['overview'];
    expect(buildingLevels(true, overview, [])).toEqual({
      overview,
      detail: [],
    });
  });

  test('swaps overview and exact buildings without overlapping them', () => {
    const overview = ['overview'];
    const detail = ['detail'];
    expect(buildingLevels(true, overview, detail)).toEqual({
      overview: [],
      detail,
    });
    expect(buildingLevels(false, overview, detail)).toEqual({
      overview,
      detail: [],
    });
  });

  test('opens close enough to load complete real buildings', () => {
    expect(INITIAL_VIEW.zoom).toBeGreaterThanOrEqual(BUILDING_DETAIL_ZOOM);
    expect(renderBudget({ ...INITIAL_VIEW }).buildingLoad).toEqual({
      maxFeatures: 450,
      complete: true,
    });
  });

  test('does not issue a city-scale building request', () => {
    expect(renderBudget(OVERVIEW)).toEqual({
      buildingLoad: { maxFeatures: 0, complete: false },
      showShadows: false,
    });
  });

  test('loads complete buildings once they are visually readable', () => {
    expect(
      renderBudget({ ...OVERVIEW, zoom: BUILDING_DETAIL_ZOOM }),
    ).toEqual({
      buildingLoad: { maxFeatures: 450, complete: true },
      showShadows: true,
    });
  });

  test('fits a short walking route at building detail', () => {
    const fitted = fitRoute(
      OVERVIEW,
      { lat: 40.758, lon: -73.9855 },
      { lat: 40.7527, lon: -73.9772 },
    );
    expect(fitted.zoom).toBeGreaterThan(BUILDING_DETAIL_ZOOM);
    expect(renderBudget(fitted).showShadows).toBe(true);
  });

  test('keeps the initial building viewport within the tiled loader ceiling', () => {
    const [west, south, east, north] = bboxFor({ ...INITIAL_VIEW });
    const columns = Math.ceil((east - west) / 0.0075) + 1;
    const rows = Math.ceil((north - south) / 0.005) + 1;
    expect(columns * rows).toBeLessThanOrEqual(64);
  });
});
