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

/** Which building levels to draw.
 *
 * The overview is the whole city and never changes, so it stays mounted at
 * every zoom and the exact street geometry is drawn on top of it. It used to
 * be dropped the moment any detail existed, which looked right only while the
 * two agreed about the same ground: the detail set belongs to the viewport it
 * was fetched for, so every pan and every zoom exposed blocks it does not
 * cover, and those blocks stayed bare for a settle delay plus a round trip.
 * On a slow connection that is seconds of empty city under the camera.
 *
 * Keeping one array mounted for the life of the session also spares deck.gl
 * the ~100 ms it spends re-tessellating 44k prisms every time the level would
 * otherwise have swapped — a hitch that landed on exactly the frames where a
 * newly arrived detail payload needed the main thread.
 *
 * layers.ts sinks the overview prisms by a fixed epsilon so a roof drawn twice
 * cannot z-fight. */
export function buildingLevels<T>(
  wantsDetail: boolean,
  overview: T[],
  detail: T[],
): { overview: T[]; detail: T[] } {
  return { overview, detail: wantsDetail ? detail : [] };
}

/** Degrees. Coarse enough that panning a neighbourhood never crosses a cell,
 * fine enough that the reference stays inside the city you are looking at. */
const SUN_REFERENCE_STEP_DEG = 0.05;

/** Where to stand to compute the sun.
 *
 * Reading it from the exact camera centre made the solar position — and with
 * it every shadow polygon on screen — a new value on every frame of a pan,
 * so the client rebuilt thousands of convex hulls and deck.gl re-tessellated
 * thousands of polygons sixty times a second, for a sun that had moved by a
 * hundredth of a degree. Quantising the reference point costs under 0.03° of
 * azimuth (a decimetre at the end of a long shadow) and makes a pan free. */
export function sunReference(view: ViewState): {
  longitude: number;
  latitude: number;
} {
  const quantise = (value: number) =>
    Math.round(value / SUN_REFERENCE_STEP_DEG) * SUN_REFERENCE_STEP_DEG;
  return { longitude: quantise(view.longitude), latitude: quantise(view.latitude) };
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
