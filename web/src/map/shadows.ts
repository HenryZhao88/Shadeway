/** Building shadows, cast in 2D on the client.
 *
 * This is the same insight the server's occluder is built on, run in the other
 * direction. A building is a vertical prism, so its shadow on flat ground is
 * just its footprint swept along the anti-solar azimuth by
 *
 *     reach = height / tan(elevation)
 *
 * There is no 3D geometry involved, no shadow map, and no render pass that can
 * go wrong — a shadow is a polygon, computed from the same building heights and
 * the same solar position the routing uses. If the map says a block is shaded,
 * the route agrees, because both came from this arithmetic.
 *
 * (deck.gl ships a shadow-mapping effect. It is not used here: on this scene it
 * composited its depth pass into the visible canvas, and a demo that opens on
 * moving shadows cannot rest on a render pass we do not control.)
 */

import type { BuildingFootprint } from '../api/client';

/** Below this the sun is so low that reach goes to infinity and the whole
 *  street is in shade anyway. */
const MIN_ELEVATION_DEG = 3;
/** Metres. Past this a shadow is longer than the viewport and adds nothing but
 *  triangles. */
const MAX_REACH_M = 900;
/** Shadows from a garden wall are noise; from a tower they are the product. */
const MIN_HEIGHT_M = 8;

export interface ShadowPolygon {
  polygon: [number, number][];
  /** Kept so a taller building's shadow can be drawn a shade deeper. */
  heightM: number;
}

/** Metres per degree of latitude, and of longitude at this latitude. Good to a
 *  fraction of a percent over a city, which is far finer than a footprint. */
function metresPerDegree(lat: number): { x: number; y: number } {
  const radians = (lat * Math.PI) / 180;
  return {
    y: 111_132.92 - 559.82 * Math.cos(2 * radians),
    x: 111_412.84 * Math.cos(radians) - 93.5 * Math.cos(3 * radians),
  };
}

export function shadowPolygons(
  buildings: BuildingFootprint[],
  sun: { azimuthDeg: number; elevationDeg: number },
  centreLat: number,
): ShadowPolygon[] {
  if (sun.elevationDeg < MIN_ELEVATION_DEG) return [];

  const scale = metresPerDegree(centreLat);
  // The shadow falls AWAY from the sun: azimuth + 180.
  const away = ((sun.azimuthDeg + 180) % 360) * (Math.PI / 180);
  const unitEast = Math.sin(away);
  const unitNorth = Math.cos(away);
  const tan = Math.tan((sun.elevationDeg * Math.PI) / 180);

  const out: ShadowPolygon[] = [];
  for (const building of buildings) {
    const height = building.height_m;
    if (height < MIN_HEIGHT_M) continue;
    const reach = Math.min(height / tan, MAX_REACH_M);
    if (reach < 2) continue;

    const dLon = (reach * unitEast) / scale.x;
    const dLat = (reach * unitNorth) / scale.y;

    const swept: [number, number][] = [];
    for (const [lon, lat] of building.polygon) {
      swept.push([lon, lat]);
      swept.push([lon + dLon, lat + dLat]);
    }
    const hull = convexHull(swept);
    if (hull.length >= 3) out.push({ polygon: hull, heightM: height });
  }
  // Tallest last, so the deepest shade lands on top of the shallower.
  return out.sort((a, b) => a.heightM - b.heightM);
}

/** Monotone-chain convex hull.
 *
 *  The exact swept region of a footprint is the union of the footprint, its
 *  translate, and the parallelogram each edge sweeps. For the near-rectangular
 *  footprints in the building table the convex hull of both copies IS that
 *  union; for a concave footprint (a courtyard, an L-shaped tower) the hull
 *  fills the notch, which overstates the shadow slightly. That trade is worth
 *  naming: it errs toward MORE shade on screen than the routing model uses, and
 *  it never claims sun where there is shade.
 */
function convexHull(points: [number, number][]): [number, number][] {
  if (points.length < 3) return points;
  const sorted = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);

  const cross = (
    o: [number, number],
    a: [number, number],
    b: [number, number],
  ) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);

  const build = (input: [number, number][]) => {
    const chain: [number, number][] = [];
    for (const point of input) {
      while (
        chain.length >= 2 &&
        cross(chain[chain.length - 2]!, chain[chain.length - 1]!, point) <= 0
      ) {
        chain.pop();
      }
      chain.push(point);
    }
    return chain;
  };

  const lower = build(sorted);
  const upper = build([...sorted].reverse());
  return [...lower.slice(0, -1), ...upper.slice(0, -1)];
}
