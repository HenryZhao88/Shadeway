/** The store, and in particular the split that makes the scrubber feel instant:
 *  scrubAt moves synchronously, departAt follows after a debounce and is the
 *  only thing that costs a round trip. */

import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { chosenRouteId, useStore, DEFAULT_ORIGIN, DEFAULT_DESTINATION } from '../state/store';
import { ROUTE_RESPONSE, mockFetch } from './fixture';

const INITIAL = useStore.getState();

function reset() {
  useStore.setState({
    ...INITIAL,
    origin: DEFAULT_ORIGIN,
    destination: DEFAULT_DESTINATION,
    currentLocation: null,
    originMode: 'custom',
    locationStatus: 'idle',
    locationError: null,
    locationFocus: 0,
    route: null,
    routeStatus: 'idle',
    routeError: null,
    routeGeneration: 0,
    overrideRouteId: null,
    timeseries: {},
    timeseriesStatus: 'idle',
    departure: null,
    departureStatus: 'idle',
    scrubAt: new Date('2026-08-24T19:00:00Z'),
    departAt: new Date('2026-08-24T19:00:00Z'),
  });
}

beforeEach(() => {
  reset();
  vi.stubGlobal('fetch', vi.fn(mockFetch()));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('fetchRoute', () => {
  test('waits for a real start and destination instead of routing a preset', async () => {
    const spy = vi.fn(mockFetch());
    vi.stubGlobal('fetch', spy);
    useStore.setState({ origin: null, destination: null });

    await useStore.getState().fetchRoute();

    expect(spy).not.toHaveBeenCalled();
    expect(useStore.getState().route).toBeNull();
    expect(useStore.getState().routeError).toMatch(/starting point/i);
  });

  test('stores the response and marks itself ready', async () => {
    await useStore.getState().fetchRoute();
    const state = useStore.getState();
    expect(state.routeStatus).toBe('ready');
    expect(state.route?.chosen_route_id).toBe('shadeway');
    expect(state.routeError).toBeNull();
  });

  test('bumps the generation so the strip can replay its wipe', async () => {
    const before = useStore.getState().routeGeneration;
    await useStore.getState().fetchRoute();
    expect(useStore.getState().routeGeneration).toBe(before + 1);
  });

  test('drops the previous route timeseries, because route ids are reused', async () => {
    useStore.setState({
      timeseries: { shadeway: { route_id: 'stale', points: [] } },
    });
    await useStore.getState().fetchRoute();
    expect(useStore.getState().timeseries['shadeway']?.route_id).not.toBe('stale');
  });

  test('turns an unreachable server into a sentence a person can act on', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    await useStore.getState().fetchRoute();
    const state = useStore.getState();
    expect(state.routeStatus).toBe('error');
    expect(state.routeError).toMatch(/check your connection/i);
  });

  test('surfaces the server\'s own explanation for a rejected request', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              detail: 'origin and destination resolve to the same node',
            }),
            { status: 400 },
          ),
      ),
    );
    await useStore.getState().fetchRoute();
    expect(useStore.getState().routeError).toBe(
      'origin and destination resolve to the same node',
    );
  });

  test('sends the selected profile and pace to the server', async () => {
    const spy = vi.fn(mockFetch());
    vi.stubGlobal('fetch', spy);
    useStore.setState({ profileKey: 'high_risk', walkSpeedMs: 1.1 });
    await useStore.getState().fetchRoute();

    const call = spy.mock.calls.find(([url]) =>
      String(url).endsWith('/api/route'),
    );
    expect(call).toBeDefined();
    const body = JSON.parse(String(call![1]?.body));
    expect(body.profile.minutes_per_degree).toBe(6);
    expect(body.walk_speed_ms).toBe(1.1);
    expect(body.time_dependent).toBe(true);
  });

  test('namespaces timeseries requests with the route request id', async () => {
    const spy = vi.fn(mockFetch());
    vi.stubGlobal('fetch', spy);
    await useStore.getState().fetchRoute();
    await vi.waitFor(() => {
      expect(useStore.getState().timeseriesStatus).toBe('ready');
    });
    const calls = spy.mock.calls.filter(([url]) =>
      String(url).includes('/timeseries'),
    );
    expect(calls.length).toBeGreaterThan(0);
    for (const [url] of calls) {
      expect(String(url)).toContain('request_id=test-request');
    }
  });

  test('calculates automatically when the destination completes the trip', async () => {
    const spy = vi.fn(mockFetch());
    vi.stubGlobal('fetch', spy);
    useStore.setState({ origin: DEFAULT_ORIGIN, destination: null });

    useStore.getState().setPlace('destination', DEFAULT_DESTINATION);

    await vi.waitFor(() => {
      expect(useStore.getState().routeStatus).toBe('ready');
    });
    expect(
      spy.mock.calls.filter(([url]) => String(url).endsWith('/api/route')),
    ).toHaveLength(1);
  });
});

describe('current location', () => {
  test('uses the first live fix as the start and asks for a destination', () => {
    useStore.setState({
      origin: null,
      destination: null,
      currentLocation: null,
      originMode: 'current',
      pickMode: 'none',
    });

    useStore.getState().updateCurrentLocation({
      lat: 40.756,
      lon: -73.982,
      accuracyM: 14,
      label: 'Your location',
    });

    expect(useStore.getState().origin?.label).toBe('Your location');
    expect(useStore.getState().locationStatus).toBe('tracking');
    expect(useStore.getState().pickMode).toBe('destination');
  });

  test('routes from the latest fix when the user recalculates', async () => {
    const spy = vi.fn(mockFetch());
    vi.stubGlobal('fetch', spy);
    useStore.setState({
      origin: DEFAULT_ORIGIN,
      destination: DEFAULT_DESTINATION,
      currentLocation: {
        lat: 40.761,
        lon: -73.981,
        accuracyM: 8,
        label: 'Your location',
      },
      originMode: 'current',
    });

    await useStore.getState().fetchRoute();

    const call = spy.mock.calls.find(([url]) =>
      String(url).endsWith('/api/route'),
    );
    const body = JSON.parse(String(call?.[1]?.body));
    expect(body.origin).toEqual({ lat: 40.761, lon: -73.981 });
  });
});

describe('the scrubber split', () => {
  test('setScrubAt moves the sun immediately without touching departAt', () => {
    vi.useFakeTimers();
    const before = useStore.getState().departAt.getTime();
    const later = new Date(useStore.getState().scrubAt.getTime() + 45 * 60_000);

    useStore.getState().setScrubAt(later);

    expect(useStore.getState().scrubAt.getTime()).toBe(later.getTime());
    expect(useStore.getState().departAt.getTime()).toBe(before);
  });

  test('departAt follows once the drag stops', async () => {
    vi.useFakeTimers();
    const later = new Date(useStore.getState().scrubAt.getTime() + 45 * 60_000);
    useStore.getState().setScrubAt(later);

    await vi.advanceTimersByTimeAsync(200);

    expect(useStore.getState().departAt.getTime()).toBe(later.getTime());
  });

  test('a drag across many values re-routes once, not once per pixel', async () => {
    vi.useFakeTimers();
    const spy = vi.fn(mockFetch());
    vi.stubGlobal('fetch', spy);
    const base = useStore.getState().scrubAt.getTime();

    for (let step = 1; step <= 20; step += 1) {
      useStore.getState().setScrubAt(new Date(base + step * 5 * 60_000));
      await vi.advanceTimersByTimeAsync(20);
    }
    await vi.advanceTimersByTimeAsync(400);

    const routeCalls = spy.mock.calls.filter(([url]) =>
      String(url).endsWith('/api/route'),
    );
    expect(routeCalls).toHaveLength(1);
  });

  test('a nudge smaller than half a minute does not re-route at all', async () => {
    vi.useFakeTimers();
    const spy = vi.fn(mockFetch());
    vi.stubGlobal('fetch', spy);

    useStore
      .getState()
      .setScrubAt(new Date(useStore.getState().scrubAt.getTime() + 5_000));
    await vi.advanceTimersByTimeAsync(400);

    expect(
      spy.mock.calls.filter(([url]) => String(url).endsWith('/api/route')),
    ).toHaveLength(0);
  });
});

describe('choosing a route', () => {
  test('follows the server heat-profile pick by default', async () => {
    await useStore.getState().fetchRoute();
    expect(chosenRouteId(useStore.getState())).toBe('shadeway');
  });

  test('honours an explicit pick', async () => {
    await useStore.getState().fetchRoute();
    useStore.getState().selectRoute('fastest');
    expect(chosenRouteId(useStore.getState())).toBe('fastest');
  });

  test('ignores a pick that is not in the response', async () => {
    await useStore.getState().fetchRoute();
    useStore.getState().selectRoute('does-not-exist');
    expect(chosenRouteId(useStore.getState())).toBe('shadeway');
  });

  test('a new profile clears a stale manual pick', async () => {
    await useStore.getState().fetchRoute();
    useStore.getState().selectRoute('fastest');
    useStore.getState().setProfile('high_risk');
    expect(useStore.getState().overrideRouteId).toBeNull();
  });

  test('a profile change reselects the existing frontier without a request', async () => {
    await useStore.getState().fetchRoute();
    const spy = vi.fn(mockFetch());
    vi.stubGlobal('fetch', spy);
    useStore.getState().setProfile('high_risk');
    expect(
      spy.mock.calls.filter(([url]) => String(url).endsWith('/api/route')),
    ).toHaveLength(0);
    expect(chosenRouteId(useStore.getState())).toBe('shadeway');
  });
});

describe('viewport data', () => {
  test('loads a persistent whole-city overview independently of detail zoom', async () => {
    const spy = vi.fn(mockFetch());
    vi.stubGlobal('fetch', spy);

    await useStore.getState().fetchBuildingOverview();

    expect(useStore.getState().buildingOverviewStatus).toBe('ready');
    expect(
      spy.mock.calls.filter(([url]) =>
        String(url).includes('/buildings-overview-v2.bin'),
      ),
    ).toHaveLength(1);
  });

  test('skips custom building requests at city overview zoom', async () => {
    const spy = vi.fn(mockFetch());
    vi.stubGlobal('fetch', spy);

    const ok = await useStore.getState().fetchViewportData(
      [-74.1, 40.65, -73.85, 40.85],
      { maxFeatures: 0, complete: false },
    );

    expect(ok).toBe(true);
    expect(
      spy.mock.calls.filter(([url]) => String(url).includes('/buildings')),
    ).toHaveLength(0);
    expect(useStore.getState().buildings).toEqual([]);
  });

  test('uses one packed request for a complete street viewport', async () => {
    const spy = vi.fn(mockFetch());
    vi.stubGlobal('fetch', spy);

    const ok = await useStore.getState().fetchViewportData(
      [-74, 40.74, -73.97, 40.76],
      { maxFeatures: 450, complete: true },
    );

    expect(ok).toBe(true);
    const buildingCalls = spy.mock.calls.filter(([url]) =>
      String(url).includes('/buildings'),
    );
    expect(buildingCalls).toHaveLength(1);
    expect(String(buildingCalls[0]![0])).toContain('/buildings.bin?bbox=');
  });

  test('a failed amenity fetch does not disturb the route', async () => {
    await useStore.getState().fetchRoute();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    await useStore.getState().fetchViewportData([-74, 40.7, -73.9, 40.8]);

    const state = useStore.getState();
    expect(state.route).not.toBeNull();
    expect(state.routeStatus).toBe('ready');
    expect(state.routeError).toBeNull();
  });
});

describe('swapping the ends', () => {
  test('exchanges origin and destination', async () => {
    const { origin, destination } = useStore.getState();
    expect(origin).not.toBeNull();
    expect(destination).not.toBeNull();
    useStore.getState().swapEnds();
    expect(useStore.getState().origin?.label).toBe(destination!.label);
    expect(useStore.getState().destination?.label).toBe(origin!.label);
  });
});

describe('the fixture matches the contract', () => {
  test('every route in the response carries the fields the UI reads', () => {
    for (const route of Object.values(ROUTE_RESPONSE.routes)) {
      expect(route.legs.length).toBeGreaterThan(0);
      expect(route.instructions.length).toBeGreaterThan(0);
      expect(Number.isFinite(route.feels_like_c.mean_c)).toBe(true);
      expect(Array.isArray(route.waypoints)).toBe(true);
    }
  });
});

describe('viewport data retries', () => {
  test('reports success so the caller can remember the bbox', async () => {
    const ok = await useStore
      .getState()
      .fetchViewportData([-74, 40.7, -73.9, 40.8]);
    expect(ok).toBe(true);
  });

  test('reports failure so the caller can forget it and try again', async () => {
    // The common first-load failure is a server that has not finished starting.
    // Latching on the bbox there leaves the map empty until someone pans.
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    const ok = await useStore
      .getState()
      .fetchViewportData([-74, 40.7, -73.9, 40.8]);
    expect(ok).toBe(false);
  });
});
