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

/** Manhattan in context, rather than a single Midtown block. The opening view
 * makes it clear that this is a city-scale map; zooming in brings the shadow
 * model down to the individual building. */
export const INITIAL_VIEW = {
  longitude: -73.9812,
  latitude: 40.745,
  zoom: 11.7,
  pitch: 34,
  bearing: -16,
} as const;
