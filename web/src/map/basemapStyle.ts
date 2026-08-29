/** The basemap, and what to do when it is not there.
 *
 * CARTO's dark styles are keyless, which matters: the whole project has no API
 * keys anywhere. But a demo can be offline, and a map that fails to load must
 * not take the shadows and routes with it — so `FALLBACK_STYLE` is a valid
 * style with no network sources at all. deck.gl draws on top of either one, so
 * the shadow layer, the routes and the pins are all still there.
 */

import type { StyleSpecification } from 'maplibre-gl';

export const BASEMAP_URL =
  'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';

/** Deliberately just a ground colour. Offline, the city is drawn entirely by
 *  our own building footprints, which is the honest picture anyway. */
export const FALLBACK_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [
    {
      id: 'ground',
      type: 'background',
      paint: { 'background-color': '#0f1113' },
    },
  ],
  glyphs: undefined,
};

/** Open close enough for the real building geometry to be visible immediately.
 * A city-wide opening used to request no buildings by design, which made the
 * main feature look broken before anyone had interacted with the map. */
export const INITIAL_VIEW = {
  longitude: -73.9812,
  latitude: 40.745,
  zoom: 15.4,
  pitch: 48,
  bearing: -16,
} as const;
