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
  getBuildingOverview,
  getBuildings,
  getDepartureCurve,
  getHealth,
  getTimeseries,
  getViewportBuildings,
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
import type { UnitSystem } from '../units';

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

export interface CurrentLocation extends Place {
  accuracyM: number;
}

/** Named points for the optional sample trip and the pre-route solar display. */
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
export type LocationStatus =
  | 'idle'
  | 'requesting'
  | 'tracking'
  | 'denied'
  | 'unavailable';
export type OriginMode = 'custom' | 'current';

export interface BuildingLoadOptions {
  maxFeatures: number;
  complete: boolean;
}

interface State {
  origin: Place | null;
  destination: Place | null;
  currentLocation: CurrentLocation | null;
  originMode: OriginMode;
  locationStatus: LocationStatus;
  locationError: string | null;
  /** Incremented when the map should move back to the live location. */
  locationFocus: number;
  scrubAt: Date;
  departAt: Date;
  profileKey: ProfileKey;
  walkSpeedMs: number;
  unitSystem: UnitSystem;

  route: RouteResponse | null;
  routeStatus: Status;
  routeError: string | null;
  /** Bumped on every completed route, so the strip can replay its wipe. */
  routeGeneration: number;
  /** null means "follow the server's heat-profile pick". */
  overrideRouteId: string | null;

  timeseries: Record<string, TimeseriesResponse>;
  timeseriesStatus: Status;
  departure: DepartureCurveResponse | null;
  departureStatus: Status;

  amenities: Amenity[];
  showAmenities: boolean;
  buildings: BuildingFootprint[];
  buildingsTruncated: boolean;
  buildingOverview: BuildingFootprint[];
  buildingOverviewStatus: Status;

  health: Health | null;
  pickMode: PickMode;
  plantedCount: number;
  /** What the last plant invalidated — the cache story, in one number. */
  lastPlant: { planted: number; invalidated: number } | null;
  hoveredLegIndex: number | null;

  setScrubAt: (when: Date) => void;
  commitDeparture: () => void;
  setPlace: (which: 'origin' | 'destination', place: Place) => void;
  clearPlace: (which: 'origin' | 'destination') => void;
  setTrip: (origin: Place, destination: Place, departAt?: Date) => void;
  selectCurrentLocation: () => void;
  updateCurrentLocation: (place: CurrentLocation) => void;
  setLocationStatus: (status: LocationStatus, error?: string | null) => void;
  focusCurrentLocation: () => void;
  swapEnds: () => void;
  setProfile: (key: ProfileKey) => void;
  setWalkSpeed: (ms: number) => void;
  setUnitSystem: (system: UnitSystem) => void;
  setPickMode: (mode: PickMode) => void;
  selectRoute: (routeId: string | null) => void;
  hoverLeg: (index: number | null) => void;
  toggleAmenities: () => void;

  fetchRoute: () => Promise<void>;
  fetchTimeseries: () => Promise<void>;
  fetchDeparture: () => Promise<void>;
  /** Resolves false when the fetch failed, so the caller can retry. */
  fetchViewportData: (
    bbox: Bbox,
    buildingLoad?: BuildingLoadOptions,
  ) => Promise<boolean>;
  fetchBuildingOverview: () => Promise<void>;
  fetchHealth: () => Promise<void>;
  plant: (positions: LatLon[]) => Promise<void>;
}

/** The re-route is the only thing here that genuinely needs a round trip, so
 *  it is the only thing debounced. 150 ms per the design notes: long enough to
 *  swallow a drag, short enough that the lag reads as thinking. */
const REROUTE_DEBOUNCE_MS = 150;

let debounceTimer: ReturnType<typeof setTimeout> | undefined;
let routeAbort: AbortController | undefined;
let timeseriesAbort: AbortController | undefined;
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

const INITIAL_DEPARTURE = initialDeparture();

function message(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return 'Something went wrong.';
}

function aborted(error: unknown): boolean {
  return (error as Error)?.name === 'AbortError';
}

export const useStore = create<State>((set, get) => ({
  origin: null,
  destination: null,
  currentLocation: null,
  originMode: 'custom',
  locationStatus: 'idle',
  locationError: null,
  locationFocus: 0,
  // One reading of the clock, shared. Calling initialDeparture() twice meant
  // two `new Date()` calls that could straddle a minute boundary, leaving
  // scrubAt and departAt 60 s apart at boot — past commitDeparture's 30 s
  // threshold, so the app opened with a re-routing spinner that never resolved
  // until the reader touched the scrubber.
  scrubAt: new Date(INITIAL_DEPARTURE),
  departAt: new Date(INITIAL_DEPARTURE),
  profileKey: 'standard',
  walkSpeedMs: 1.35,
  unitSystem: 'imperial',

  route: null,
  routeStatus: 'idle',
  routeError: null,
  routeGeneration: 0,
  overrideRouteId: null,

  timeseries: {},
  timeseriesStatus: 'idle',
  departure: null,
  departureStatus: 'idle',

  amenities: [],
  showAmenities: true,
  buildings: [],
  buildingsTruncated: false,
  buildingOverview: [],
  buildingOverviewStatus: 'idle',

  health: null,
  pickMode: 'none',
  plantedCount: 0,
  lastPlant: null,
  hoveredLegIndex: null,

  setScrubAt: (when) => {
    set({ scrubAt: when });
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => get().commitDeparture(), REROUTE_DEBOUNCE_MS);
  },

  commitDeparture: () => {
    const { scrubAt, departAt } = get();
    if (Math.abs(scrubAt.getTime() - departAt.getTime()) < 30_000) return;
    set({ departAt: new Date(scrubAt) });
    if (get().origin && get().destination) void get().fetchRoute();
  },

  setPlace: (which, place) => {
    set({
      [which]: place,
      ...(which === 'origin' ? { originMode: 'custom' as const } : {}),
      pickMode: 'none',
      route: null,
      routeStatus: 'idle',
      routeError: null,
      timeseries: {},
      timeseriesStatus: 'idle',
      departure: null,
      departureStatus: 'idle',
      overrideRouteId: null,
    } as Partial<State>);
    set({ scrubAt: get().departAt });
    if (get().origin && get().destination) void get().fetchRoute();
  },

  clearPlace: (which) =>
    set({
      [which]: null,
      ...(which === 'origin' ? { originMode: 'custom' as const } : {}),
      route: null,
      routeStatus: 'idle',
      routeError: null,
      timeseries: {},
      timeseriesStatus: 'idle',
      departure: null,
      departureStatus: 'idle',
      overrideRouteId: null,
    } as Partial<State>),

  setTrip: (origin, destination, departAt) => {
    clearTimeout(debounceTimer);
    set({
      origin,
      destination,
      ...(departAt
        ? {
            scrubAt: new Date(departAt),
            departAt: new Date(departAt),
          }
        : {}),
      originMode: 'custom',
      pickMode: 'none',
      route: null,
      routeStatus: 'idle',
      routeError: null,
      timeseries: {},
      timeseriesStatus: 'idle',
      departure: null,
      departureStatus: 'idle',
      overrideRouteId: null,
    });
    void get().fetchRoute();
  },

  selectCurrentLocation: () => {
    const current = get().currentLocation;
    set({
      origin: current,
      originMode: 'current',
      pickMode: current && !get().destination ? 'destination' : 'none',
      route: null,
      routeStatus: 'idle',
      routeError: null,
      timeseries: {},
      timeseriesStatus: 'idle',
      departure: null,
      departureStatus: 'idle',
      overrideRouteId: null,
      locationFocus: get().locationFocus + (current ? 1 : 0),
    });
    if (current && get().destination) void get().fetchRoute();
  },

  updateCurrentLocation: (place) => {
    const state = get();
    const firstFix = state.currentLocation === null;
    const adoptAsOrigin = state.originMode === 'current' && !state.route;
    set({
      currentLocation: place,
      locationStatus: 'tracking',
      locationError: null,
      ...(adoptAsOrigin ? { origin: place } : {}),
      ...(adoptAsOrigin && !state.destination
        ? { pickMode: 'destination' as const }
        : {}),
      locationFocus: state.locationFocus + (firstFix ? 1 : 0),
    });
    if (
      adoptAsOrigin &&
      state.destination &&
      state.routeStatus !== 'loading'
    ) {
      void get().fetchRoute();
    }
  },

  setLocationStatus: (status, error = null) =>
    set({ locationStatus: status, locationError: error }),

  focusCurrentLocation: () =>
    set({ locationFocus: get().locationFocus + 1 }),

  swapEnds: () => {
    const { origin, destination } = get();
    if (!origin || !destination) return;
    set({ origin: destination, destination: origin, originMode: 'custom' });
    void get().fetchRoute();
  },

  setProfile: (key) => {
    // The server already returned the whole Pareto frontier. Reapplying its
    // small, deterministic selection formula locally avoids another route plus
    // 16 background departure searches for a pure preference change.
    set((state) => ({
      profileKey: key,
      overrideRouteId: null,
      route: state.route
        ? {
            ...state.route,
            chosen_route_id: chooseForProfile(state.route, PROFILES[key]!),
          }
        : null,
    }));
  },

  setWalkSpeed: (ms) => {
    set({ walkSpeedMs: ms });
    if (get().origin && get().destination) void get().fetchRoute();
  },

  setUnitSystem: (system) => set({ unitSystem: system }),

  setPickMode: (mode) => set({ pickMode: mode }),
  selectRoute: (routeId) => set({ overrideRouteId: routeId }),
  hoverLeg: (index) => set({ hoveredLegIndex: index }),
  toggleAmenities: () => set({ showAmenities: !get().showAmenities }),

  fetchRoute: async () => {
    routeAbort?.abort();
    timeseriesAbort?.abort();
    routeAbort = new AbortController();
    const signal = routeAbort.signal;
    const {
      origin,
      destination,
      currentLocation,
      originMode,
      departAt,
      profileKey,
      walkSpeedMs,
    } = get();
    const routeOrigin =
      originMode === 'current' && currentLocation ? currentLocation : origin;
    if (!routeOrigin || !destination) {
      set({
        routeStatus: 'idle',
        routeError: !routeOrigin
          ? 'Use your location or choose a starting point.'
          : 'Choose a destination on the map.',
      });
      return;
    }
    if (routeOrigin !== origin) set({ origin: routeOrigin });
    const profile = PROFILES[profileKey]!;
    set({ routeStatus: 'loading', routeError: null });
    try {
      const response = await postRoute({
        origin: { lat: routeOrigin.lat, lon: routeOrigin.lon },
        destination: { lat: destination.lat, lon: destination.lon },
        departAt,
        profile: {
          name: profile.name,
          minutes_per_degree: profile.minutes_per_degree,
        },
        walkSpeedMs,
        signal,
      });
      if (signal.aborted) return;
      set((state) => ({
        route: response,
        routeStatus: 'ready',
        routeError: null,
        routeGeneration: state.routeGeneration + 1,
        // route ids are labels and get reused, so the old curves are stale
        timeseries: {},
        timeseriesStatus: 'loading',
      }));
      void get().fetchTimeseries();
      void get().fetchDeparture();
    } catch (error) {
      if (aborted(error)) return;
      set({ routeStatus: 'error', routeError: message(error) });
    }
  },

  fetchTimeseries: async () => {
    const { route, departAt, walkSpeedMs } = get();
    if (!route) return;
    timeseriesAbort?.abort();
    timeseriesAbort = new AbortController();
    const signal = timeseriesAbort.signal;
    const requestId = route.request_id;
    set({ timeseriesStatus: 'loading' });
    const next = await loadTimeseries(route, departAt, walkSpeedMs, signal);
    if (signal.aborted || get().route?.request_id !== requestId) return;
    set({
      timeseries: next,
      timeseriesStatus: Object.keys(next).length ? 'ready' : 'error',
    });
  },

  fetchDeparture: async () => {
    departureAbort?.abort();
    departureAbort = new AbortController();
    const signal = departureAbort.signal;
    const { origin, destination, departAt, walkSpeedMs } = get();
    if (!origin || !destination) return;
    set({ departureStatus: 'loading' });
    try {
      const response = await getDepartureCurve(
        { lat: origin.lat, lon: origin.lon },
        { lat: destination.lat, lon: destination.lon },
        departAt,
        walkSpeedMs,
        4,
        signal,
      );
      if (signal.aborted) return;
      set({ departure: response, departureStatus: 'ready' });
    } catch (error) {
      if (aborted(error)) return;
      set({ departureStatus: 'error' });
    }
  },

  fetchViewportData: async (
    bbox,
    buildingLoad = { maxFeatures: 600, complete: false },
  ) => {
    viewportAbort?.abort();
    viewportAbort = new AbortController();
    const signal = viewportAbort.signal;
    try {
      const buildingRequest =
        buildingLoad.maxFeatures > 0
          ? buildingLoad.complete
            ? getViewportBuildings(bbox, buildingLoad.maxFeatures, signal)
            : getBuildings(bbox, buildingLoad.maxFeatures, signal)
          : Promise.resolve({ buildings: [], truncated: false });
      const [amenities, buildings] = await Promise.all([
        getAmenities(bbox, signal),
        buildingRequest,
      ]);
      if (signal.aborted) return true;
      set({
        amenities,
        buildings: buildings.buildings,
        buildingsTruncated: buildings.truncated,
      });
      return true;
    } catch (error) {
      // Map furniture. A failure here must not take the route down with it —
      // but it must not leave the map permanently empty either, which is what
      // happens if the caller remembers the bbox it just failed on. The most
      // likely failure is the very first load racing a server that is still
      // starting, and that map never repaints until someone pans.
      //
      // An abort is not a failure: a newer viewport superseded this one and is
      // already in flight. Reporting it as one made the caller count it against
      // its retry budget. Both branches returned false, so the abort check
      // above it was dead — this is what it was written to say.
      if (aborted(error)) return true;
      return false;
    }
  },

  fetchBuildingOverview: async () => {
    const status = get().buildingOverviewStatus;
    if (status === 'ready' || status === 'loading') return;
    set({ buildingOverviewStatus: 'loading' });
    try {
      const response = await getBuildingOverview();
      set({
        buildingOverview: response.buildings,
        buildingOverviewStatus: 'ready',
      });
    } catch {
      // Overview is progressive map furniture. Exact street buildings and the
      // route still work if an older server is briefly active during rollout.
      set({ buildingOverviewStatus: 'error' });
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
      // Only if there is a trip to re-run. Planting a tree before picking one
      // used to fall into fetchRoute's "choose a destination" branch and put
      // that in the planner's error slot, as though the planting had failed.
      if (get().origin && get().destination) await get().fetchRoute();
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
  signal: AbortSignal,
): Promise<Record<string, TimeseriesResponse>> {
  const ids = Object.keys(response.routes);
  const results = await Promise.all(
    ids.map(async (id) => {
      try {
        return [
          id,
          await getTimeseries(
            id,
            response.request_id,
            departAt,
            walkSpeedMs,
            6,
            signal,
          ),
        ] as const;
      } catch {
        return [id, null] as const;
      }
    }),
  );
  const next: Record<string, TimeseriesResponse> = {};
  for (const [id, series] of results) if (series) next[id] = series;
  return next;
}


function chooseForProfile(
  response: RouteResponse,
  profile: HeatProfile,
): string {
  const frontier = [...response.frontier].sort(
    (a, b) => a.duration_s - b.duration_s,
  );
  const baseline = frontier[0];
  if (!baseline) return response.chosen_route_id;
  const budgetS = profile.minutes_per_degree * 60;
  return frontier.reduce((best, point) => {
    const score =
      point.duration_s -
      baseline.duration_s -
      budgetS * (baseline.mean_feels_like_c - point.mean_feels_like_c);
    const bestScore =
      best.duration_s -
      baseline.duration_s -
      budgetS * (baseline.mean_feels_like_c - best.mean_feels_like_c);
    return score < bestScore ? point : best;
  }, baseline).route_id;
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
