/** The deck.gl layers.
 *
 * The shadow layer is the first five seconds of the demo: the shadows are on
 * the map and already moving when the scrubber is dragged, before a word is
 * said. It is entirely client-side and entirely geometric — see shadows.ts, and
 * note that nothing here is lit: the shade you see is a polygon computed from a
 * building height and a solar angle, not a lighting model. That is why it
 * matches what the router thinks.
 */

import {
  PathLayer,
  PolygonLayer,
  ScatterplotLayer,
  SolidPolygonLayer,
} from '@deck.gl/layers';

import { AMENITY_KIND, type Amenity, type BuildingFootprint } from '../api/client';
import { heatRgb } from '../heat';
import type { LegStep, Route, WaypointSuggestion } from '../api/types';
import type { ShadowPolygon } from './shadows';

export type Rgba = [number, number, number, number];

/** Path and scatterplot layers are unlit, so nothing shadows them and they need
 *  no opt-out: only the extruded buildings and the ground plane take part in the
 *  lighting at all.
 *
 *  Routes and pins must never be hidden behind an extruded building when the
 *  camera is pitched, so they skip the depth test entirely. luma.gl v9 spells
 *  that as a WebGPU compare function rather than the old `depthTest: false`. */
const ALWAYS_ON_TOP = { depthCompare: 'always' as const, depthWriteEnabled: false };

/** Buildings read as flat dark masses with a slightly lighter roof. Deliberate:
 *  an unlit prism cannot mislead anyone about where the sun is, and the shadow
 *  polygons are doing that job with real geometry. */
const BUILDING_FILL: Rgba = [48, 59, 72, 248];
const BUILDING_LINE: Rgba = [86, 103, 119, 215];

/** Shade needs something to be darker THAN.
 *
 *  The warm wash over open ground is kept deliberately faint. An earlier,
 *  stronger version turned the whole basemap sepia, which is the failure mode
 *  to avoid: the city should look like a city in the sun, not like a photograph
 *  of one. The contrast is carried instead by the shadows, which are nearly
 *  opaque — in real shade you cannot read the street either. */
const SUNLIT_GROUND: Rgba = [255, 226, 176, 16];
const SHADOW_FILL: Rgba = [2, 5, 11, 228];

const ROUTE_WIDTH_CHOSEN = 7;
const ROUTE_WIDTH_OTHER = 3.5;

/** The warm wash over open ground. Drawn under the shadows, never over them. */
export function sunlitGroundLayer(
  bbox: [number, number, number, number],
  sunElevationDeg: number,
) {
  const [west, south, east, north] = bbox;
  const pad = 0.02;
  // After sunset there is no sunlit ground to wash, and washing it anyway
  // would show a lit city at midnight.
  const lit = sunElevationDeg > 0;
  return new SolidPolygonLayer<{ polygon: [number, number][] }>({
    id: 'sunlit-ground',
    data: lit
      ? [
          {
            polygon: [
              [west - pad, south - pad],
              [east + pad, south - pad],
              [east + pad, north + pad],
              [west - pad, north + pad],
            ] as [number, number][],
          },
        ]
      : [],
    getPolygon: (d) => d.polygon,
    // Low sun means weak, raking light: fade the wash out toward dusk.
    getFillColor: [
      SUNLIT_GROUND[0],
      SUNLIT_GROUND[1],
      SUNLIT_GROUND[2],
      Math.round(SUNLIT_GROUND[3] * Math.min(1, sunElevationDeg / 25)),
    ] as Rgba,
    material: false,
    pickable: false,
    updateTriggers: { getFillColor: sunElevationDeg, data: lit },
  });
}

/** The shadows. One polygon per building, swept along the anti-solar azimuth.
 *  Redrawn whenever the scrubber moves, which costs one pass over the footprints
 *  in view and no network at all. */
export function shadowLayer(shadows: ShadowPolygon[]) {
  return new PolygonLayer<ShadowPolygon>({
    id: 'shadows',
    data: shadows,
    extruded: false,
    filled: true,
    stroked: false,
    getPolygon: (d) => d.polygon,
    getFillColor: SHADOW_FILL,
    material: false,
    pickable: false,
    updateTriggers: { getPolygon: shadows.length },
  });
}

export function buildingLayer(buildings: BuildingFootprint[]) {
  return new PolygonLayer<BuildingFootprint>({
    id: 'buildings',
    data: buildings,
    extruded: true,
    wireframe: false,
    filled: true,
    stroked: true,
    lineWidthUnits: 'pixels',
    getLineWidth: 1,
    getLineColor: BUILDING_LINE,
    getPolygon: (d) => d.polygon,
    getElevation: (d) => d.height_m,
    getFillColor: BUILDING_FILL,
    // Unlit on purpose: see the note on BUILDING_FILL.
    material: false,
    pickable: false,
    updateTriggers: { getElevation: buildings.length },
  });
}

interface LegDatum {
  path: [number, number][];
  feels: number;
  legIndex: number;
  routeId: string;
  chosen: boolean;
  streetName: string;
}

function legData(route: Route, chosen: boolean): LegDatum[] {
  return route.legs.map((leg: LegStep, index) => ({
    path: leg.geometry,
    feels: leg.feels_like_c,
    legIndex: index,
    routeId: route.route_id,
    chosen,
    streetName: leg.street_name.replace(/\s+/g, ' ').trim(),
  }));
}

/** The route, coloured by felt temperature along its length, so the hot blocks
 *  are visible without reading anything. The unchosen route stays desaturated:
 *  two temperature-coloured lines at equal weight would compete, and only one
 *  of them is the recommendation. */
export function routeLayers(
  routes: Route[],
  chosenId: string | null,
  hoveredLegIndex: number | null,
) {
  const layers = [];
  for (const route of routes) {
    const chosen = route.route_id === chosenId;
    if (chosen) continue; // drawn last, on top
    layers.push(
      new PathLayer<LegDatum>({
        id: `route-${route.route_id}`,
        data: legData(route, false),
        getPath: (d) => d.path,
        getColor: [111, 143, 168, 150],
        getWidth: ROUTE_WIDTH_OTHER,
        widthUnits: 'pixels',
        capRounded: true,
        jointRounded: true,
        pickable: true,
        parameters: ALWAYS_ON_TOP,
      }),
    );
  }
  const chosenRoute = routes.find((route) => route.route_id === chosenId);
  if (chosenRoute) {
    const data = legData(chosenRoute, true);
    layers.push(
      new PathLayer<LegDatum>({
        id: 'route-casing',
        data,
        getPath: (d) => d.path,
        getColor: [14, 19, 25, 235],
        getWidth: ROUTE_WIDTH_CHOSEN + 4,
        widthUnits: 'pixels',
        capRounded: true,
        jointRounded: true,
        pickable: false,
        parameters: ALWAYS_ON_TOP,
      }),
      new PathLayer<LegDatum>({
        id: 'route-chosen',
        data,
        getPath: (d) => d.path,
        getColor: (d) => {
          const [r, g, b] = heatRgb(d.feels);
          return [r, g, b, 255] as Rgba;
        },
        getWidth: (d) =>
          hoveredLegIndex === d.legIndex
            ? ROUTE_WIDTH_CHOSEN + 4
            : ROUTE_WIDTH_CHOSEN,
        widthUnits: 'pixels',
        capRounded: true,
        jointRounded: true,
        pickable: true,
        parameters: ALWAYS_ON_TOP,
        updateTriggers: { getWidth: hoveredLegIndex, getColor: data.length },
      }),
    );
  }
  return layers;
}

export interface EndpointDatum {
  position: [number, number];
  kind: 'origin' | 'destination';
  label: string;
}

export function endpointLayer(data: EndpointDatum[]) {
  return new ScatterplotLayer<EndpointDatum>({
    id: 'endpoints',
    data,
    getPosition: (d) => d.position,
    getRadius: 7,
    radiusUnits: 'pixels',
    getFillColor: (d) =>
      d.kind === 'origin' ? [255, 217, 121, 255] : [232, 237, 242, 255],
    stroked: true,
    lineWidthUnits: 'pixels',
    getLineWidth: 2.5,
    getLineColor: [14, 19, 25, 255],
    pickable: true,
    parameters: ALWAYS_ON_TOP,
  });
}

/** Amenity pins. Cool water is the one thing on this map allowed to use the
 *  cool end of the heat ramp, because that is exactly what it is: relief. */
const AMENITY_COLOR: Record<number, Rgba> = {
  [AMENITY_KIND.DRINKING_FOUNTAIN]: [80, 191, 190, 210],
  [AMENITY_KIND.COOLING_CENTER]: [130, 205, 235, 210],
  [AMENITY_KIND.PARK_ENTRANCE]: [124, 190, 140, 200],
};

export function amenityLayer(amenities: Amenity[]) {
  return new ScatterplotLayer<Amenity>({
    id: 'amenities',
    data: amenities,
    getPosition: (d) => [d.lon, d.lat],
    getRadius: 3.4,
    radiusUnits: 'pixels',
    getFillColor: (d) => AMENITY_COLOR[d.kind] ?? [154, 167, 180, 190],
    stroked: false,
    pickable: true,
    parameters: ALWAYS_ON_TOP,
    updateTriggers: { getFillColor: amenities.length },
  });
}

/** The rest stops the post-pass suggested. Ringed, so they read as a
 *  recommendation rather than as one more pin in the amenity field. */
export function waypointLayer(waypoints: WaypointSuggestion[]) {
  return new ScatterplotLayer<WaypointSuggestion>({
    id: 'waypoints',
    data: waypoints,
    getPosition: (d) => [d.at.lon, d.at.lat],
    getRadius: 8,
    radiusUnits: 'pixels',
    getFillColor: [80, 191, 190, 235],
    stroked: true,
    lineWidthUnits: 'pixels',
    getLineWidth: 2.5,
    getLineColor: [14, 19, 25, 255],
    pickable: true,
    parameters: ALWAYS_ON_TOP,
    updateTriggers: { getPosition: waypoints.length },
  });
}
