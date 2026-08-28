/** The only module that talks to the server.
 *
 * Everything crossing this boundary is WGS84 lon/lat and degrees Celsius, per
 * the frozen contract in contracts/shadeway_contracts/api.py. `types.ts` next
 * to this file is generated from it — do not hand-edit either.
 *
 * Two endpoints (amenities, buildings) are map furniture rather than part of
 * the route contract, so they are typed here instead.
 */

import type {
  DepartureCurveResponse,
  HeatProfile,
  LatLon,
  PlantResponse,
  RouteRequest,
  RouteResponse,
  TimeseriesResponse,
  WeatherSnapshot,
} from './types';

const BASE = '/api';

export interface Amenity {
  amenity_id: number;
  kind: number;
  name: string;
  lat: number;
  lon: number;
}

/** tables.AmenityKind, mirrored for display. */
export const AMENITY_KIND = {
  DRINKING_FOUNTAIN: 0,
  COOLING_CENTER: 1,
  PARK_ENTRANCE: 2,
} as const;

export const AMENITY_LABEL: Record<number, string> = {
  0: 'drinking fountain',
  1: 'cooling site',
  2: 'park entrance',
};

export interface BuildingFootprint {
  building_id: number;
  height_m: number;
  base_m: number;
  polygon: [number, number][];
}

export interface BuildingResponse {
  buildings: BuildingFootprint[];
  truncated: boolean;
}

export interface GeocodeResult {
  label: string;
  lat: number;
  lon: number;
  kind: string;
}

export interface GeocodeResponse {
  results: GeocodeResult[];
  attribution: string;
}

export interface Health {
  status: string;
  scene: string;
  cache_warm: boolean;
  warm_fraction: number;
  n_edges: number;
  n_samples: number;
  scene_version: number;
  planting_enabled: boolean;
}

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
    });
  } catch (cause) {
    if ((cause as Error)?.name === 'AbortError') throw cause;
    // A dead server is the single most likely failure on demo day, so it gets
    // a sentence a person can act on rather than "Failed to fetch".
    throw new ApiError(
      0,
      'Cannot reach shadeway right now. Check your connection and try again.',
    );
  }
  if (!response.ok) {
    throw new ApiError(response.status, await detail(response));
  }
  return (await response.json()) as T;
}

async function detail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === 'string') return body.detail;
  } catch {
    /* a non-JSON error body is not worth a second failure */
  }
  return `The server answered ${response.status}.`;
}

export function getHealth(signal?: AbortSignal) {
  return json<Health>('/health', { signal });
}

/** Place search is submit-only rather than typeahead: the public Nominatim
 * service explicitly disallows autocomplete traffic. */
export function searchPlaces(query: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ q: query.trim() });
  return json<GeocodeResponse>(`/geocode?${params}`, { signal });
}

export interface RouteArgs {
  origin: LatLon;
  destination: LatLon;
  departAt: Date;
  profile: HeatProfile;
  walkSpeedMs: number;
  signal?: AbortSignal;
}

export function postRoute(args: RouteArgs) {
  const body: RouteRequest = {
    origin: args.origin,
    destination: args.destination,
    depart_iso: args.departAt.toISOString(),
    profile: args.profile,
    walk_speed_ms: args.walkSpeedMs,
    max_alternatives: 3,
    time_dependent: true,
  };
  return json<RouteResponse>('/route', {
    method: 'POST',
    body: JSON.stringify(body),
    signal: args.signal,
  });
}

export function getTimeseries(
  routeId: string,
  requestId: string,
  departAt: Date,
  walkSpeedMs: number,
  hours = 6,
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({
    request_id: requestId,
    depart_iso: departAt.toISOString(),
    // 15-minute resolution over six hours: fine enough to see the afternoon
    // turn over, coarse enough to stay one cheap call.
    step_minutes: '15',
    hours: String(hours),
    walk_speed_ms: String(walkSpeedMs),
  });
  return json<TimeseriesResponse>(
    `/route/${encodeURIComponent(routeId)}/timeseries?${query}`,
    { signal },
  );
}

export function getDepartureCurve(
  origin: LatLon,
  destination: LatLon,
  fromAt: Date,
  walkSpeedMs: number,
  hours = 4,
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({
    origin_lat: String(origin.lat),
    origin_lon: String(origin.lon),
    dest_lat: String(destination.lat),
    dest_lon: String(destination.lon),
    from_iso: fromAt.toISOString(),
    hours: String(hours),
    walk_speed_ms: String(walkSpeedMs),
  });
  return json<DepartureCurveResponse>(`/departure-curve?${query}`, { signal });
}

export function getWeather(at: LatLon, when: Date, signal?: AbortSignal) {
  const query = new URLSearchParams({
    lat: String(at.lat),
    lon: String(at.lon),
    at_iso: when.toISOString(),
  });
  return json<WeatherSnapshot>(`/weather?${query}`, { signal });
}

export type Bbox = [west: number, south: number, east: number, north: number];

export function getAmenities(bbox: Bbox, signal?: AbortSignal) {
  return json<Amenity[]>(`/amenities?bbox=${bbox.join(',')}`, { signal });
}

export function getBuildings(
  bbox: Bbox,
  maxFeatures = 1600,
  signal?: AbortSignal,
  omitTruncated = false,
) {
  const omit = omitTruncated ? '&omit_truncated=true' : '';
  return json<BuildingResponse>(
    `/buildings?bbox=${bbox.join(',')}&max_features=${maxFeatures}${omit}`,
    { signal },
  );
}

const PACKED_BUILDING_MAGIC = [0x53, 0x57, 0x42, 0x31] as const; // SWB1
const PACKED_VIEWPORT_PADDING = 0.18;
const PACKED_VIEWPORT_CACHE_MAX = 2;
const packedViewportCache: Array<{
  bbox: Bbox;
  buildings: BuildingFootprint[];
}> = [];
let buildingOverviewPromise: Promise<BuildingResponse> | undefined;

/** Load a complete navigation viewport in one compact response. Coordinates
 * are int32 microdegrees and all other fields are typed arrays, cutting the
 * live opening waterfall from 28 JSON requests to one small binary request. */
export async function getPackedBuildings(
  bbox: Bbox,
  signal?: AbortSignal,
): Promise<BuildingResponse> {
  return fetchPackedBuildings(`/buildings.bin?bbox=${bbox.join(',')}`, signal);
}

/** Load the whole-city low-detail prisms once. They stay resident so zooming
 * out never turns Manhattan into an empty basemap while exact rings unload. */
export function getBuildingOverview(): Promise<BuildingResponse> {
  if (!buildingOverviewPromise) {
    buildingOverviewPromise = fetchPackedBuildings(
      '/buildings-overview-v2.bin',
    ).catch((error) => {
      buildingOverviewPromise = undefined;
      throw error;
    });
  }
  return buildingOverviewPromise;
}

async function fetchPackedBuildings(
  path: string,
  signal?: AbortSignal,
): Promise<BuildingResponse> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { signal });
  } catch (cause) {
    if ((cause as Error)?.name === 'AbortError') throw cause;
    throw new ApiError(
      0,
      'Cannot reach shadeway right now. Check your connection and try again.',
    );
  }
  if (!response.ok) {
    throw new ApiError(response.status, await detail(response));
  }
  const buildings = decodePackedBuildings(await response.arrayBuffer());
  return {
    buildings,
    truncated: response.headers.get('x-shadeway-truncated') === '1',
  };
}

/** Binary first; bounded JSON tiles remain the compatibility path for an old
 * server or a viewport that exceeds the packed endpoint's safety ceiling. */
export async function getViewportBuildings(
  bbox: Bbox,
  tileMaxFeatures = 450,
  signal?: AbortSignal,
): Promise<BuildingResponse> {
  const cachedIndex = packedViewportCache.findIndex((entry) =>
    bboxContains(entry.bbox, bbox),
  );
  if (cachedIndex >= 0) {
    const cached = packedViewportCache[cachedIndex]!;
    packedViewportCache.splice(cachedIndex, 1);
    packedViewportCache.push(cached);
    return {
      buildings: cached.buildings.filter((building) =>
        buildingIntersectsBbox(building, bbox),
      ),
      truncated: false,
    };
  }

  const requestBbox = padBbox(bbox, PACKED_VIEWPORT_PADDING);
  try {
    const response = await getPackedBuildings(requestBbox, signal);
    if (response.truncated) {
      return getCompleteBuildings(bbox, tileMaxFeatures, signal);
    }
    packedViewportCache.push({ bbox: requestBbox, buildings: response.buildings });
    while (packedViewportCache.length > PACKED_VIEWPORT_CACHE_MAX) {
      packedViewportCache.shift();
    }
    return {
      buildings: response.buildings.filter((building) =>
        buildingIntersectsBbox(building, bbox),
      ),
      truncated: false,
    };
  } catch (error) {
    // Allows the new frontend to roll out against a briefly older container.
    // Other failures should retry the primary path instead of multiplying a
    // struggling server's load by starting a 28-request fallback waterfall.
    if (error instanceof ApiError && [404, 413].includes(error.status)) {
      return getCompleteBuildings(bbox, tileMaxFeatures, signal);
    }
    throw error;
  }
}

function decodePackedBuildings(buffer: ArrayBuffer): BuildingFootprint[] {
  const headerBytes = 12;
  if (buffer.byteLength < 16) throw invalidPackedBuildings();
  const bytes = new Uint8Array(buffer);
  if (PACKED_BUILDING_MAGIC.some((byte, index) => bytes[index] !== byte)) {
    throw invalidPackedBuildings();
  }
  const view = new DataView(buffer);
  const buildingCount = view.getUint32(4, true);
  const coordinateCount = view.getUint32(8, true);
  const idsStart = headerBytes;
  const heightsStart = idsStart + buildingCount * 4;
  const basesStart = heightsStart + buildingCount * 4;
  const offsetsStart = basesStart + buildingCount * 4;
  const coordinatesStart = offsetsStart + (buildingCount + 1) * 4;
  const expectedBytes = coordinatesStart + coordinateCount * 8;
  if (expectedBytes !== buffer.byteLength) throw invalidPackedBuildings();

  const ids = new Int32Array(buffer, idsStart, buildingCount);
  const heights = new Float32Array(buffer, heightsStart, buildingCount);
  const bases = new Float32Array(buffer, basesStart, buildingCount);
  const offsets = new Uint32Array(buffer, offsetsStart, buildingCount + 1);
  const coordinates = new Int32Array(
    buffer,
    coordinatesStart,
    coordinateCount * 2,
  );
  if (offsets[0] !== 0 || offsets[buildingCount] !== coordinateCount) {
    throw invalidPackedBuildings();
  }

  const buildings: BuildingFootprint[] = new Array(buildingCount);
  for (let index = 0; index < buildingCount; index += 1) {
    const start = offsets[index]!;
    const end = offsets[index + 1]!;
    if (end < start || end > coordinateCount) throw invalidPackedBuildings();
    const polygon: [number, number][] = new Array(end - start);
    for (let coordinate = start; coordinate < end; coordinate += 1) {
      polygon[coordinate - start] = [
        coordinates[coordinate * 2]! / 1_000_000,
        coordinates[coordinate * 2 + 1]! / 1_000_000,
      ];
    }
    buildings[index] = {
      building_id: ids[index]!,
      height_m: heights[index]!,
      base_m: bases[index]!,
      polygon,
    };
  }
  return buildings;
}

function invalidPackedBuildings() {
  return new ApiError(502, 'The server returned invalid building geometry.');
}

function padBbox([west, south, east, north]: Bbox, ratio: number): Bbox {
  const lonPadding = (east - west) * ratio;
  const latPadding = (north - south) * ratio;
  return [
    west - lonPadding,
    south - latPadding,
    east + lonPadding,
    north + latPadding,
  ];
}

function bboxContains(
  [outerWest, outerSouth, outerEast, outerNorth]: Bbox,
  [innerWest, innerSouth, innerEast, innerNorth]: Bbox,
) {
  return (
    outerWest <= innerWest &&
    outerSouth <= innerSouth &&
    outerEast >= innerEast &&
    outerNorth >= innerNorth
  );
}

const BUILDING_TILE_LON_DEG = 0.0075;
const BUILDING_TILE_LAT_DEG = 0.005;
const BUILDING_TILE_CONCURRENCY = 4;
const BUILDING_TILE_MAX_DEPTH = 4;
const BUILDING_MAX_SEED_TILES = 64;
const BUILDING_TILE_CACHE_MAX = 48;
const buildingTileCache = new Map<string, BuildingResponse>();

/** Load every building in a street-level viewport without ever asking the
 * server to serialize the entire viewport in one response. Dense tiles split
 * again until the endpoint reports a complete result. */
export async function getCompleteBuildings(
  bbox: Bbox,
  maxFeatures = 450,
  signal?: AbortSignal,
): Promise<BuildingResponse> {
  type Tile = { bbox: Bbox; depth: number };
  const seeds = seedBuildingTiles(bbox);
  if (seeds.length > BUILDING_MAX_SEED_TILES) {
    // Defensive fallback for a caller that accidentally requests completeness
    // at city scale. One bounded partial response is preferable to hundreds of
    // otherwise valid tile requests.
    return getBuildings(bbox, maxFeatures, signal);
  }
  const pending: Tile[] = seeds.map((tile) => ({
    bbox: tile,
    depth: 0,
  }));
  const found = new Map<number, BuildingFootprint>();
  let truncated = false;

  while (pending.length) {
    const batch = pending.splice(0, BUILDING_TILE_CONCURRENCY);
    const responses = await Promise.all(
      batch.map(async (tile) => ({
        tile,
        response: await getBuildingTile(
          tile.bbox,
          maxFeatures,
          signal,
        ),
      })),
    );
    for (const { tile, response } of responses) {
      if (response.truncated && tile.depth < BUILDING_TILE_MAX_DEPTH) {
        pending.push(
          ...splitBbox(tile.bbox).map((child) => ({
            bbox: child,
            depth: tile.depth + 1,
          })),
        );
        continue;
      }
      truncated ||= response.truncated;
      for (const building of response.buildings) {
        found.set(building.building_id, building);
      }
    }
  }

  return {
    buildings: [...found.values()]
      .filter((building) => buildingIntersectsBbox(building, bbox))
      .sort((a, b) => a.building_id - b.building_id),
    truncated,
  };
}

function buildingIntersectsBbox(
  building: BuildingFootprint,
  [west, south, east, north]: Bbox,
) {
  let buildingWest = Infinity;
  let buildingSouth = Infinity;
  let buildingEast = -Infinity;
  let buildingNorth = -Infinity;
  for (const [lon, lat] of building.polygon) {
    buildingWest = Math.min(buildingWest, lon);
    buildingSouth = Math.min(buildingSouth, lat);
    buildingEast = Math.max(buildingEast, lon);
    buildingNorth = Math.max(buildingNorth, lat);
  }
  return (
    buildingEast >= west &&
    buildingWest <= east &&
    buildingNorth >= south &&
    buildingSouth <= north
  );
}

async function getBuildingTile(
  bbox: Bbox,
  maxFeatures: number,
  signal?: AbortSignal,
): Promise<BuildingResponse> {
  const key = `${bbox.join(',')}|${maxFeatures}`;
  const cached = buildingTileCache.get(key);
  if (cached) {
    buildingTileCache.delete(key);
    buildingTileCache.set(key, cached);
    return cached;
  }
  const response = await getBuildings(bbox, maxFeatures, signal, true);
  buildingTileCache.set(key, response);
  while (buildingTileCache.size > BUILDING_TILE_CACHE_MAX) {
    const oldest = buildingTileCache.keys().next().value;
    if (oldest === undefined) break;
    buildingTileCache.delete(oldest);
  }
  return response;
}

/** Exposed so a scene replacement can invalidate geometry and tests can stay
 * isolated. Ordinary pans deliberately keep this cache warm. */
export function clearBuildingTileCache() {
  buildingTileCache.clear();
  packedViewportCache.length = 0;
  buildingOverviewPromise = undefined;
}

function seedBuildingTiles([west, south, east, north]: Bbox): Bbox[] {
  // Align the seed grid globally, not to the current viewport, so adjacent pans
  // ask for identical tile keys and can reuse successful responses.
  const firstColumn = Math.floor(west / BUILDING_TILE_LON_DEG);
  const lastColumn = Math.floor((east - 1e-12) / BUILDING_TILE_LON_DEG);
  const firstRow = Math.floor(south / BUILDING_TILE_LAT_DEG);
  const lastRow = Math.floor((north - 1e-12) / BUILDING_TILE_LAT_DEG);
  const tiles: Bbox[] = [];
  for (let row = firstRow; row <= lastRow; row += 1) {
    for (let column = firstColumn; column <= lastColumn; column += 1) {
      const tileWest = column * BUILDING_TILE_LON_DEG;
      const tileSouth = row * BUILDING_TILE_LAT_DEG;
      tiles.push([
        tileWest,
        tileSouth,
        tileWest + BUILDING_TILE_LON_DEG,
        tileSouth + BUILDING_TILE_LAT_DEG,
      ]);
    }
  }
  return tiles;
}

function splitBbox([west, south, east, north]: Bbox): Bbox[] {
  const midLon = (west + east) / 2;
  const midLat = (south + north) / 2;
  return [
    [west, south, midLon, midLat],
    [midLon, south, east, midLat],
    [west, midLat, midLon, north],
    [midLon, midLat, east, north],
  ];
}

export function postPlant(
  positions: LatLon[],
  species: string,
  dbhCm: number,
  signal?: AbortSignal,
) {
  return json<PlantResponse>('/scene/plant', {
    method: 'POST',
    body: JSON.stringify({ positions, species, dbh_cm: dbhCm }),
    signal,
  });
}
