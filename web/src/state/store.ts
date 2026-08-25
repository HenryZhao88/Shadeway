/** All client state, in one store.
 *
 * The split that matters is between `scrubAt` and `departAt`:
 *
 *   scrubAt   what the sun is doing right now on screen. Set synchronously on
 *             every pixel of scrubber drag. Drives the shadow polygons, which
 *             are swept from building heights against a client-side solar
 *             position, so this updates at frame rate and waits for nothing.
 *   departAt  the departure the current route was actually planned for. Follows
 *             scrubAt after a debounce and triggers one server round trip.
 *
 * Three things were hiding behind the word "scrubber" and only the last needs
 * the server: the city's shadows (local geometry, see map/shadows.ts), the
 * route's heat-vs-time curve (one call, cached per route), and the re-route
 * itself (debounced).
 */

import { create } from 'zustand';

import {
  ApiError,
  getAmenities,
  getBuildings,
  getDepartureCurve,
  getHealth,
  getTimeseries,
  postPlant,
  postRoute,
  type Amenity,
  type Bbox,
  type BuildingFootprint,
  type Health,
} from '../api/client';
import { PRESET_PROFILE_NAMES } from '../api/types';
import type {
  DepartureCurveResponse,
  HeatProfile,
  LatLon,
  RouteResponse,
  TimeseriesResponse,
} from '../api/types';

/** Mirrors PRESET_PROFILES in the contract. The number is the whole model: how
 *  many extra walking minutes one degree of cooling is worth. */
export const PROFILES: Record<string, HeatProfile & { who: string }> = {
  standard: {
    name: 'standard',
    minutes_per_degree: 1,
    who: 'A minute of walking for a degree of cooling.',
  },
  sensitive: {
    name: 'sensitive',
    minutes_per_degree: 3,
    who: 'Heat-sensitive, on medication, or working outdoors all day.',
  },
  high_risk: {
    name: 'high risk',
    minutes_per_degree: 6,
    who: 'Over 65, pregnant, or with a heart or lung condition.',
  },
};

export type ProfileKey = (typeof PRESET_PROFILE_NAMES)[number];

export interface Place extends LatLon {
  label: string;
}

/** Midtown at 3pm — the opening frame of the demo. */
export const DEFAULT_ORIGIN: Place = {
  lat: 40.758,
  lon: -73.9855,
  label: 'Times Square',
};
export const DEFAULT_DESTINATION: Place = {
  lat: 40.7527,
  lon: -73.9772,
  label: 'Grand Central',
};

export type Status = 'idle' | 'loading' | 'ready' | 'error';
export type PickMode = 'none' | 'origin' | 'destination' | 'plant';

interface State {
  origin: Place;
  destination: Place;
  scrubAt: Date;
  departAt: Date;
  profileKey: ProfileKey;
  walkSpeedMs: number;

  route: RouteResponse | null;
  routeStatus: Status;
  routeError: string | null;
  /** Bumped on every completed route, so the strip can replay its wipe. */
  routeGeneration: number;
  /** null means "follow the server's heat-profile pick". */
  overrideRouteId: string | null;

  timeseries: Record<string, TimeseriesResponse>;
  departure: DepartureCurveResponse | null;
  departureStatus: Status;

  amenities: Amenity[];
  showAmenities: boolean;
  buildings: BuildingFootprint[];
  buildingsTruncated: boolean;

  health: Health | null;
  pickMode: PickMode;
  plantedCount: number;
  /** What the last plant invalidated — the cache story, in one number. */
  lastPlant: { planted: number; invalidated: number } | null;
  hoveredLegIndex: number | null;

  setScrubAt: (when: Date) => void;
  commitDeparture: () => void;
  setPlace: (which: 'origin' | 'destination', place: Place) => void;
  swapEnds: () => void;
  setProfile: (key: ProfileKey) => void;
  setWalkSpeed: (ms: number) => void;
  setPickMode: (mode: PickMode) => void;
  selectRoute: (routeId: string | null) => void;
  hoverLeg: (index: number | null) => void;
  toggleAmenities: () => void;

  fetchRoute: () => Promise<void>;
  fetchDeparture: () => Promise<void>;
  fetchViewportData: (bbox: Bbox) => Promise<void>;
  fetchHealth: () => Promise<void>;
  plant: (positions: LatLon[]) => Promise<void>;
}

/** The re-route is the only thing here that genuinely needs a round trip, so
 *  it is the only thing debounced. 150 ms per the design notes: long enough to
 *  swallow a drag, short enough that the lag reads as thinking. */
const REROUTE_DEBOUNCE_MS = 150;

let debounceTimer: ReturnType<typeof setTimeout> | undefined;
let routeAbort: AbortController | undefined;
let departureAbort: AbortController | undefined;
let viewportAbort: AbortController | undefined;

function initialDeparture(): Date {
  const now = new Date();
  // The demo opens at 3pm on a hot afternoon. Before 3, jump forward to it;
  // after, keep the real clock — a route for a time that has passed is a lie.
  if (now.getHours() < 15) now.setHours(15, 0, 0, 0);
  else now.setSeconds(0, 0);
  return now;
}

function message(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return 'Something went wrong.';
}

function aborted(error: unknown): boolean {
  return (error as Error)?.name === 'AbortError';
}

export const useStore = create<State>((set, get) => ({
  origin: DEFAULT_ORIGIN,
  destination: DEFAULT_DESTINATION,
  scrubAt: initialDeparture(),
  departAt: initialDeparture(),
  profileKey: 'standard',
  walkSpeedMs: 1.35,

  route: null,
  routeStatus: 'idle',
  routeError: null,
  routeGeneration: 0,
  overrideRouteId: null,

  timeseries: {},
  departure: null,
  departureStatus: 'idle',

  amenities: [],
  showAmenities: true,
  buildings: [],
  buildingsTruncated: false,

  health: null,
  pickMode: 'none',
  plantedCount: 0,
  hoveredLegIndex: null,
  lastPlant: null,

  setScrubAt: (when) => {
    set({ scrubAt: when });
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => get().commitDeparture(), REROUTE_DEBOUNCE_MS);
  },

  commitDeparture: () => {
    const { scrubAt, departAt } = get();
    if (Math.abs(scrubAt.getTime() - departAt.getTime()) < 30_000) return;
    set({ departAt: new Date(scrubAt) });
    void get().fetchRoute();
  },

  setPlace: (which, place) => {
    set({ [which]: place, pickMode: 'none' } as Partial<State>);
    set({ scrubAt: get().departAt });
    void get().fetchRoute();
  },

  swapEnds: () => {
    const { origin, destination } = get();
    set({ origin: destination, destination: origin });
    void get().fetchRoute();
  },

  setProfile: (key) => {
    // The heat profile is a display choice, not a re-route: the pareto frontier
    // we already hold contains the answer. But the server also applies the
    // profile when picking `chosen_route_id`, so ask it again — it is cheap and
    // it keeps one authority over which point is chosen.
    set({ profileKey: key, overrideRouteId: null });
    void get().fetchRoute();
  },

  setWalkSpeed: (ms) => {
    set({ walkSpeedMs: ms });
    void get().fetchRoute();
  },

  setPickMode: (mode) => set({ pickMode: mode }),
  selectRoute: (routeId) => set({ overrideRouteId: routeId }),
  hoverLeg: (index) => set({ hoveredLegIndex: index }),
  toggleAmenities: () => set({ showAmenities: !get().showAmenities }),

  fetchRoute: async () => {
    routeAbort?.abort();
    routeAbort = new AbortController();
    const { origin, destination, departAt, profileKey, walkSpeedMs } = get();
    const profile = PROFILES[profileKey]!;
    set({ routeStatus: 'loading', routeError: null });
    try {
      const response = await postRoute({
        origin: { lat: origin.lat, lon: origin.lon },
        destination: { lat: destination.lat, lon: destination.lon },
        departAt,
        profile: {
          name: profile.name,
          minutes_per_degree: profile.minutes_per_degree,
        },
        walkSpeedMs,
        signal: routeAbort.signal,
      });
      set((state) => ({
        route: response,
        routeStatus: 'ready',
        routeError: null,
        routeGeneration: state.routeGeneration + 1,
        // route ids are labels and get reused, so the old curves are stale
        timeseries: {},
      }));
      void loadTimeseries(response, departAt, walkSpeedMs, set);
      void get().fetchDeparture();
    } catch (error) {
      if (aborted(error)) return;
      set({ routeStatus: 'error', routeError: message(error) });
    }
  },

  fetchDeparture: async () => {
    departureAbort?.abort();
    departureAbort = new AbortController();
    const { origin, destination, departAt, walkSpeedMs } = get();
    set({ departureStatus: 'loading' });
    try {
      const response = await getDepartureCurve(
        { lat: origin.lat, lon: origin.lon },
        { lat: destination.lat, lon: destination.lon },
        departAt,
        walkSpeedMs,
        4,
        departureAbort.signal,
      );
      set({ departure: response, departureStatus: 'ready' });
    } catch (error) {
      if (aborted(error)) return;
      set({ departureStatus: 'error' });
    }
  },

  fetchViewportData: async (bbox) => {
    viewportAbort?.abort();
    viewportAbort = new AbortController();
    const signal = viewportAbort.signal;
    try {
      const [amenities, buildings] = await Promise.all([
        getAmenities(bbox, signal),
        getBuildings(bbox, 2600, signal),
      ]);
      set({
        amenities,
        buildings: buildings.buildings,
        buildingsTruncated: buildings.truncated,
      });
    } catch (error) {
      if (aborted(error)) return;
      // Map furniture. A failure here must not take the route down with it.
    }
  },

  fetchHealth: async () => {
    try {
      set({ health: await getHealth() });
    } catch {
      set({ health: null });
    }
  },

  plant: async (positions) => {
    try {
      const response = await postPlant(positions, 'Gleditsia triacanthos', 22);
      // Plant mode stays armed: the demo beat is a whole corridor of trees, and
      // re-arming the tool between every one of them would be absurd. The
      // button turns it off.
      set((state) => ({
        plantedCount: state.plantedCount + response.planted,
        lastPlant: {
          planted: response.planted,
          invalidated: response.invalidated_samples,
        },
      }));
      await get().fetchRoute();
    } catch (error) {
      if (aborted(error)) return;
      set({ routeError: message(error) });
    }
  },
}));

/** One call per route on screen. The whole heat-vs-time series comes back in
 *  one response because it is the same sample points at N times, which the
 *  server's horizon cache makes nearly free. */
async function loadTimeseries(
  response: RouteResponse,
  departAt: Date,
  walkSpeedMs: number,
  set: (partial: Partial<State> | ((state: State) => Partial<State>)) => void,
): Promise<void> {
  const ids = Object.keys(response.routes);
  const results = await Promise.all(
    ids.map(async (id) => {
      try {
        return [id, await getTimeseries(id, departAt, walkSpeedMs)] as const;
      } catch {
        return [id, null] as const;
      }
    }),
  );
  const next: Record<string, TimeseriesResponse> = {};
  for (const [id, series] of results) if (series) next[id] = series;
  set({ timeseries: next });
}

/** The route the interface is showing: the user's pick if they made one, the
 *  server's heat-profile pick otherwise. */
export function chosenRouteId(state: State): string | null {
  if (!state.route) return null;
  if (state.overrideRouteId && state.route.routes[state.overrideRouteId]) {
    return state.overrideRouteId;
  }
  return state.route.chosen_route_id;
}
