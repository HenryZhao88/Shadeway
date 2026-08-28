import type { Bbox } from '../api/client';

export interface ViewState {
  longitude: number;
  latitude: number;
  zoom: number;
  pitch: number;
  bearing: number;
}

export interface MapRenderBudget {
  buildingLoad: { maxFeatures: number; complete: boolean };
  showShadows: boolean;
}

/** At this scale the bounded tile grid stays below its defensive 64-tile
 * ceiling, while individual prisms are already large enough to read. */
export const BUILDING_DETAIL_ZOOM = 14.25;

/** Route overview uses the basemap, as navigation apps do. Neighbourhood and
 * street views switch to every real occluder in bounded tiles and cast exact
 * moving shadows. */
export function renderBudget(view: ViewState): MapRenderBudget {
  if (view.zoom < BUILDING_DETAIL_ZOOM) {
    return { buildingLoad: { maxFeatures: 0, complete: false }, showShadows: false };
  }
  return { buildingLoad: { maxFeatures: 450, complete: true }, showShadows: true };
}

export function fitRoute(
  current: ViewState,
  origin: { lat: number; lon: number },
  destination: { lat: number; lon: number },
): ViewState {
  const lonSpan = Math.max(0.001, Math.abs(origin.lon - destination.lon));
  const latSpan = Math.max(0.001, Math.abs(origin.lat - destination.lat));
  const span = Math.max(lonSpan, latSpan / 0.62);
  // Navigation should fill the map with the trip, not load several surrounding
  // neighbourhoods. The previous 2.4 factor made this short route occupy only
  // a small part of the canvas and multiplied the building viewport by ~6.5.
  const zoom = Math.max(12.5, Math.min(16.7, Math.log2(360 / (span * 0.95))));
  return {
    ...current,
    longitude: (origin.lon + destination.lon) / 2,
    latitude: (origin.lat + destination.lat) / 2,
    zoom,
    pitch: 40,
    bearing: 0,
  };
}

/** Approximate viewport bounds from the camera. Exact bounds would need the
 * unprojected corners of a pitched frustum; this is a data-fetch window, and a
 * little padding costs a few extra pins rather than correctness. */
export function bboxFor(view: ViewState): Bbox {
  const spanLon = 360 / 2 ** view.zoom;
  const spanLat = spanLon * 0.62;
  // A pitched camera sees further toward the horizon than a flat one, but only
  // a little further is worth fetching: the rest is a haze of rooftops that
  // costs a thousand footprints and shows nothing.
  const reach = 1 + view.pitch / 110;
  return [
    view.longitude - spanLon * reach,
    view.latitude - spanLat * reach,
    view.longitude + spanLon * reach,
    view.latitude + spanLat * reach,
  ];
}
