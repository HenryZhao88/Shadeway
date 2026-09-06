import { describe, expect, test } from 'vitest';

import { INITIAL_VIEW } from '../map/basemapStyle';
import {
  BUILDING_DETAIL_ZOOM,
  bboxFor,
  buildingLevels,
  fitRoute,
  renderBudget,
  sunReference,
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

  // The detail set belongs to the viewport it was fetched for. A pan or a
  // zoom exposes ground it does not cover, and the request for that ground
  // takes a settle delay plus a round trip to arrive. Dropping the overview
  // the moment any detail exists left that ground bare for the whole wait.
  test('keeps the overview under exact detail, so new ground is never bare', () => {
    const overview = ['overview'];
    const detail = ['detail'];
    expect(buildingLevels(true, overview, detail)).toEqual({
      overview,
      detail,
    });
  });

  test('drops exact detail below the detail zoom', () => {
    expect(buildingLevels(false, ['overview'], ['detail'])).toEqual({
      overview: ['overview'],
      detail: [],
    });
  });

  // The overview never changes once loaded. Handing deck.gl the same array
  // every time is what stops it re-tessellating 44k prisms on a level swap.
  test('passes the overview through by reference', () => {
    const overview = ['overview'];
    expect(buildingLevels(true, overview, ['detail']).overview).toBe(overview);
    expect(buildingLevels(false, overview, ['detail']).overview).toBe(overview);
  });

  // Shadows are rebuilt whenever the sun moves, and the sun moved on every
  // frame of a pan because it was read from the exact camera centre. Over a
  // city the sun is the same sun, so the reference point is quantised and a
  // pan recomputes nothing.
  describe('sun reference', () => {
    test('does not move while the camera pans across a neighbourhood', () => {
      const a = sunReference({ ...OVERVIEW, longitude: -73.9812, latitude: 40.745 });
      const b = sunReference({ ...OVERVIEW, longitude: -73.9769, latitude: 40.7481 });
      expect(b).toEqual(a);
    });

    test('stays within a fraction of a degree of the camera', () => {
      const view = { ...OVERVIEW, longitude: -73.9812, latitude: 40.745 };
      const reference = sunReference(view);
      expect(Math.abs(reference.longitude - view.longitude)).toBeLessThan(0.05);
      expect(Math.abs(reference.latitude - view.latitude)).toBeLessThan(0.05);
    });

    test('follows the camera across the city', () => {
      const here = sunReference({ ...OVERVIEW, longitude: -73.98, latitude: 40.74 });
      const there = sunReference({ ...OVERVIEW, longitude: -73.78, latitude: 40.64 });
      expect(there).not.toEqual(here);
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
