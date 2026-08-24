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
      paint: { 'background-color': '#0e1319' },
    },
  ],
  glyphs: undefined,
};

/** Midtown, framed on the demo route. Close enough that a 1 km walk fills the
 *  frame and the shadows have readable edges; pitched enough that the towers
 *  casting them are visible as towers. */
export const INITIAL_VIEW = {
  longitude: -73.9812,
  latitude: 40.7553,
  zoom: 15.4,
  pitch: 44,
  bearing: -20,
} as const;
