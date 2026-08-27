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

export function getBuildings(bbox: Bbox, maxFeatures = 1600, signal?: AbortSignal) {
  return json<{ buildings: BuildingFootprint[]; truncated: boolean }>(
    `/buildings?bbox=${bbox.join(',')}&max_features=${maxFeatures}`,
    { signal },
  );
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
