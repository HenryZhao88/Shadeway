/** A route response shaped exactly like the server's, for tests that must not
 *  need a server. Values are taken from a real Times Square -> Grand Central
 *  response so the numbers behave like real ones. */

import type {
  DepartureCurveResponse,
  Instruction,
  LegStep,
  Route,
  RouteResponse,
  TimeseriesResponse,
} from '../api/types';

const DEPART = '2026-08-24T15:00:00-04:00';

function leg(overrides: Partial<LegStep> & { edge_id: number }): LegStep {
  return {
    street_name: 'Broadway',
    side: 0,
    kind: 0,
    geometry: [
      [-73.9855, 40.758],
      [-73.985, 40.7575],
    ],
    length_m: 120,
    enter_iso: DEPART,
    exit_iso: '2026-08-24T15:01:29-04:00',
    feels_like_c: 30,
    tmrt_c: 42,
    f_sun: 0.5,
    svf: 0.3,
    ...overrides,
  } satisfies LegStep;
}

const FAST_LEGS: LegStep[] = [
  leg({ edge_id: 1, feels_like_c: 41, f_sun: 0.95, street_name: 'Broadway' }),
  leg({ edge_id: 2, feels_like_c: 39.5, f_sun: 0.9, street_name: 'W 42 St' }),
  leg({ edge_id: 3, feels_like_c: 43, f_sun: 1, street_name: 'W 42 St' }),
  leg({ edge_id: 4, kind: 1, side: -1, feels_like_c: 42, street_name: 'W 42 St' }),
  leg({ edge_id: 5, feels_like_c: 38, f_sun: 0.6, street_name: 'E 42 St', side: 1 }),
];

const COOL_LEGS: LegStep[] = [
  leg({ edge_id: 11, feels_like_c: 31, f_sun: 0.05, street_name: 'W 45 St' }),
  leg({ edge_id: 12, kind: 1, side: -1, feels_like_c: 34, street_name: 'W 45 St' }),
  leg({ edge_id: 13, feels_like_c: 30, f_sun: 0.02, street_name: 'E 45 St', side: 1 }),
  leg({ edge_id: 14, feels_like_c: 33, f_sun: 0.3, street_name: 'Park Ave' }),
];

const FAST_INSTRUCTIONS: Instruction[] = [
  {
    type: 'start',
    at: { lat: 40.758, lon: -73.9855 },
    text: 'Head off along the east side of Broadway',
    why: null,
  },
  {
    type: 'turn',
    at: { lat: 40.7549, lon: -73.984 },
    text: 'Turn onto the north-east side of W 42 St',
    why: {
      sunlit_until_iso: null,
      shaded_by: null,
      delta_c: -0.3,
      dappled: false,
    },
  },
];

const COOL_INSTRUCTIONS: Instruction[] = [
  {
    type: 'start',
    at: { lat: 40.7568, lon: -73.9827 },
    text: 'Head off along the north-east side of W 45 St',
    why: null,
  },
  {
    type: 'cross',
    at: { lat: 40.7555, lon: -73.9794 },
    text: 'Cross to the east side of W 45 St',
    why: {
      sunlit_until_iso: '2026-08-24T15:56:00-04:00',
      shaded_by: 'the 226 m tower on Broadway',
      delta_c: 4.2,
      dappled: false,
    },
  },
  {
    type: 'turn',
    at: { lat: 40.7524, lon: -73.9775 },
    text: 'Turn onto the east side of Park Ave',
    why: {
      sunlit_until_iso: null,
      shaded_by: 'honey locusts overhead',
      delta_c: 1.1,
      dappled: true,
    },
  },
  {
    type: 'arrive',
    at: { lat: 40.7524, lon: -73.9774 },
    text: 'Arrive',
    why: null,
  },
];

function route(
  id: string,
  legs: LegStep[],
  instructions: Instruction[],
  durationS: number,
  meanC: number,
): Route {
  const feels = legs.map((l) => l.feels_like_c);
  return {
    route_id: id,
    label: id,
    depart_iso: DEPART,
    arrive_iso: new Date(
      new Date(DEPART).getTime() + durationS * 1000,
    ).toISOString(),
    duration_s: durationS,
    distance_m: legs.reduce((sum, l) => sum + l.length_m, 0),
    feels_like_c: {
      mean_c: meanC,
      max_c: Math.max(...feels),
      p90_c: Math.max(...feels) - 0.5,
    },
    exposure: { sun_fraction: 0.4, mean_svf: 0.25, canopy_fraction: 0.2 },
    legs,
    instructions,
    waypoints: [],
  };
}

export const FASTEST = route('fastest', FAST_LEGS, FAST_INSTRUCTIONS, 1080, 41);
export const SHADEWAY = route('shadeway', COOL_LEGS, COOL_INSTRUCTIONS, 1380, 33);

export const ROUTE_RESPONSE: RouteResponse = {
  request_id: 'test-request',
  computed_at: DEPART,
  weather: {
    observed_iso: DEPART,
    air_temp_c: 32,
    relative_humidity_pct: 45,
    wind_speed_10m_ms: 3,
    cloud_cover_pct: 10,
    direct_normal_wm2: 799,
    diffuse_wm2: 148,
    global_horizontal_wm2: 712,
    uv_index: 8,
    source: 'open-meteo',
  },
  frontier: [
    { route_id: 'fastest', duration_s: 1080, mean_feels_like_c: 41 },
    { route_id: 'shadeway', duration_s: 1380, mean_feels_like_c: 33 },
  ],
  routes: { fastest: FASTEST, shadeway: SHADEWAY },
  chosen_route_id: 'shadeway',
  cache_warm: true,
  compute_ms: 412,
};

/** Six hours at 15-minute steps, the window the client actually asks for.
 *  Shaped like a real afternoon: warms to a peak, then falls away. */
export const TIMESERIES: TimeseriesResponse = {
  route_id: 'shadeway',
  points: [33, 34, 35, 36, 35.5, 34, 32, 30, 28, 27, 26, 25].map(
    (mean, index) => ({
      at_iso: new Date(
        new Date(DEPART).getTime() + index * 30 * 60_000,
      ).toISOString(),
      mean_feels_like_c: mean,
      max_feels_like_c: mean + 3,
      sun_fraction: Math.max(0, 0.4 - index * 0.03),
    }),
  ),
};

export const DEPARTURE_CURVE: DepartureCurveResponse = {
  points: [
    { depart_iso: DEPART, best_mean_feels_like_c: 33, best_duration_s: 1380 },
    {
      depart_iso: '2026-08-24T15:15:00-04:00',
      best_mean_feels_like_c: 31.5,
      best_duration_s: 1370,
    },
    {
      depart_iso: '2026-08-24T15:30:00-04:00',
      best_mean_feels_like_c: 29,
      best_duration_s: 1350,
    },
    {
      depart_iso: '2026-08-24T15:45:00-04:00',
      best_mean_feels_like_c: 26,
      best_duration_s: 1340,
    },
  ],
  now_index: 0,
  best_index: 3,
};

export const HEALTH = {
  status: 'ok',
  scene: 'data/nyc',
  cache_warm: true,
  warm_fraction: 1,
  n_edges: 138439,
  n_samples: 520741,
  scene_version: 1,
  planting_enabled: true,
};

/** A fetch stand-in that answers every endpoint the client calls. */
export function mockFetch(overrides: Record<string, unknown> = {}) {
  return async (
    input: RequestInfo | URL,
    _init?: RequestInit,
  ): Promise<Response> => {
    const url = String(typeof input === 'string' ? input : input.toString());
    const body = pick(url, overrides);
    if (body === undefined) {
      return new Response(JSON.stringify({ detail: `no stub for ${url}` }), {
        status: 404,
      });
    }
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };
}

function pick(url: string, overrides: Record<string, unknown>): unknown {
  for (const [fragment, value] of Object.entries(overrides)) {
    if (url.includes(fragment)) return value;
  }
  if (url.includes('/health')) return HEALTH;
  if (url.includes('/geocode')) {
    return {
      results: [
        {
          label: 'Times Square, Manhattan, New York, NY',
          lat: 40.758,
          lon: -73.9855,
          kind: 'square',
        },
        {
          label: 'Grand Central Terminal, Manhattan, New York, NY',
          lat: 40.7527,
          lon: -73.9772,
          kind: 'station',
        },
      ],
      attribution: '© OpenStreetMap contributors',
    };
  }
  if (url.includes('/departure-curve')) return DEPARTURE_CURVE;
  if (url.includes('/timeseries')) return TIMESERIES;
  if (url.includes('/route')) return ROUTE_RESPONSE;
  if (url.includes('/amenities')) return [];
  if (url.includes('/buildings')) return { buildings: [], truncated: false };
  return undefined;
}
