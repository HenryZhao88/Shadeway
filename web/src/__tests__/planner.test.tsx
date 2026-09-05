import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { useStore } from '../state/store';
import Endpoints from '../ui/Endpoints';
import { ROUTE_RESPONSE, mockFetch } from './fixture';

const INITIAL = useStore.getState();
let success: PositionCallback;
let failure: PositionErrorCallback;
const clearWatch = vi.fn();

beforeEach(() => {
  useStore.setState({
    ...INITIAL,
    origin: null,
    destination: null,
    currentLocation: null,
    originMode: 'custom',
    locationStatus: 'idle',
    locationError: null,
    locationFocus: 0,
    pickMode: 'none',
    route: null,
    routeStatus: 'idle',
    routeError: null,
  });
  vi.stubGlobal('fetch', vi.fn(mockFetch()));
  Object.defineProperty(navigator, 'geolocation', {
    configurable: true,
    value: {
      clearWatch,
      getCurrentPosition: vi.fn(),
      watchPosition: vi.fn((next: PositionCallback, error: PositionErrorCallback) => {
        success = next;
        failure = error;
        return 17;
      }),
    } satisfies Geolocation,
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('on a phone, once a route exists', () => {
  function compact(matches: boolean) {
    vi.stubGlobal(
      'matchMedia',
      vi.fn().mockReturnValue({
        matches,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    );
  }

  test('the form folds to the one line that names the trip', () => {
    // The planner shares a sheet with the answer it produced, and at the
    // sheet's lowest detent the answer is what the reader wants to see.
    compact(true);
    useStore.setState({
      route: ROUTE_RESPONSE,
      origin: { lat: 40.758, lon: -73.9855, label: 'Times Square' },
      destination: { lat: 40.7527, lon: -73.9772, label: 'Grand Central' },
    });

    render(<Endpoints />);

    expect(screen.getByText('Times Square')).toBeInTheDocument();
    expect(screen.getByText('Grand Central')).toBeInTheDocument();
    expect(screen.queryByText('Plan your route')).not.toBeInTheDocument();
  });

  test('a tap unfolds it again, and the form kept its place', async () => {
    compact(true);
    useStore.setState({
      route: ROUTE_RESPONSE,
      origin: { lat: 40.758, lon: -73.9855, label: 'Times Square' },
      destination: { lat: 40.7527, lon: -73.9772, label: 'Grand Central' },
    });
    render(<Endpoints />);

    await userEvent.click(screen.getByRole('button', { expanded: false }));

    expect(screen.getByText('Plan your route')).toBeInTheDocument();
    expect(screen.getByLabelText('Starting point')).toHaveValue('Times Square');
  });

  test('leaves the full form alone on a wide screen', () => {
    compact(false);
    useStore.setState({
      route: ROUTE_RESPONSE,
      origin: { lat: 40.758, lon: -73.9855, label: 'Times Square' },
      destination: { lat: 40.7527, lon: -73.9772, label: 'Grand Central' },
    });

    render(<Endpoints />);

    expect(screen.getByText('Plan your route')).toBeInTheDocument();
  });
});

describe('route planner', () => {
  test('editing a pending search aborts its obsolete request', async () => {
    let signal: AbortSignal | null | undefined;
    vi.stubGlobal('fetch', vi.fn((_url: RequestInfo | URL, init?: RequestInit) => {
      signal = init?.signal;
      return new Promise<Response>(() => {});
    }));
    render(<Endpoints />);
    await userEvent.type(screen.getByLabelText('Starting point'), 'Times Square');
    await userEvent.click(screen.getByRole('button', { name: 'Search for starting point' }));
    expect(signal?.aborted).toBe(false);

    await userEvent.type(screen.getByLabelText('Starting point'), ' West');

    expect(signal?.aborted).toBe(true);
    expect(screen.queryByText('Searching Manhattan…')).not.toBeInTheDocument();
  });

  test('a superseded search failure cannot replace the current search status', async () => {
    const requests: { resolve: (response: Response) => void }[] = [];
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((resolve) => requests.push({ resolve }))));
    render(<Endpoints />);
    await userEvent.type(screen.getByLabelText('Starting point'), 'Times Square');
    await userEvent.click(screen.getByRole('button', { name: 'Search for starting point' }));
    await userEvent.type(screen.getByLabelText('Destination'), 'Bryant Park');
    await userEvent.click(screen.getByRole('button', { name: 'Search for destination' }));

    await act(async () => requests[0]!.resolve(new Response(JSON.stringify({ detail: 'Old search failed' }), { status: 500 })));

    expect(screen.getByText('Searching Manhattan…')).toBeInTheDocument();
    expect(screen.queryByText('Old search failed')).not.toBeInTheDocument();
  });

  test('opens without silently calculating a sample route', () => {
    render(<Endpoints />);

    expect(screen.getByText('Plan your route')).toBeInTheDocument();
    expect(screen.getByLabelText('Starting point')).toBeInTheDocument();
    expect(screen.getByLabelText('Destination')).toBeInTheDocument();
    expect(screen.getByText('Use my current location')).toBeInTheDocument();
    expect(useStore.getState().route).toBeNull();
  });

  test('makes route calculation visible with motion and status text', () => {
    useStore.setState({ routeStatus: 'loading' });
    const { container } = render(<Endpoints />);

    const button = screen.getByRole('button', { name: 'Calculating…' });
    expect(button).toHaveAttribute('aria-busy', 'true');
    expect(container.querySelector('.route-loader')).toBeInTheDocument();
  });

  test('the featured sample loads a visible afternoon shade detour', async () => {
    render(<Endpoints />);

    await userEvent.click(screen.getByText('or try a sample NYC trip'));
    await userEvent.click(screen.getByText(/1-min shade detour/i));

    await vi.waitFor(() => {
      expect(useStore.getState().routeStatus).toBe('ready');
    });
    const state = useStore.getState();
    expect(state.origin?.label).toBe('Penn Station');
    expect(state.destination?.label).toBe('Rockefeller Center');
    expect(state.departAt.getHours()).toBe(15);
    expect(state.scrubAt.getTime()).toBe(state.departAt.getTime());
  });

  test('does not search on every keystroke', async () => {
    const spy = vi.fn(mockFetch());
    vi.stubGlobal('fetch', spy);
    render(<Endpoints />);

    await userEvent.type(screen.getByLabelText('Starting point'), 'Bryant Park');

    expect(
      spy.mock.calls.filter(([url]) => String(url).includes('/api/geocode')),
    ).toHaveLength(0);
  });

  test('searches and selects both addresses before calculating the route', async () => {
    render(<Endpoints />);

    await userEvent.type(screen.getByLabelText('Starting point'), 'Times Square');
    await userEvent.click(
      screen.getByRole('button', { name: 'Search for starting point' }),
    );
    await userEvent.click(await screen.findByText('Times Square'));

    expect(useStore.getState().origin?.label).toMatch(/^Times Square/);
    await userEvent.type(screen.getByLabelText('Destination'), 'Grand Central');
    await userEvent.click(
      screen.getByRole('button', { name: 'Search for destination' }),
    );
    await userEvent.click(await screen.findByText('Grand Central Terminal'));

    await vi.waitFor(() => {
      expect(useStore.getState().routeStatus).toBe('ready');
    });
    expect(useStore.getState().destination?.label).toMatch(/^Grand Central/);
  });

  test('editing a selected address clears the stale endpoint', async () => {
    useStore.setState({ origin: { lat: 40.758, lon: -73.9855, label: 'Times Square' } });
    render(<Endpoints />);

    const input = screen.getByLabelText('Starting point');
    await userEvent.clear(input);
    await userEvent.type(input, 'Bryant Park');

    expect(useStore.getState().origin).toBeNull();
  });

  test('turns a browser location fix into the route start', async () => {
    render(<Endpoints />);
    await userEvent.click(screen.getByText('Use my current location'));

    act(() => {
      success({
        coords: {
          accuracy: 11,
          altitude: null,
          altitudeAccuracy: null,
          heading: null,
          latitude: 40.755,
          longitude: -73.98,
          speed: null,
          toJSON: () => ({}),
        },
        timestamp: Date.now(),
        toJSON: () => ({}),
      });
    });

    expect(screen.getByText('Using your live location')).toBeInTheDocument();
    expect(useStore.getState().origin?.label).toBe('Your location');
    expect(useStore.getState().pickMode).toBe('destination');
  });

  test('falls back to choosing the start on the map when permission is denied', async () => {
    render(<Endpoints />);
    await userEvent.click(screen.getByText('Use my current location'));

    act(() => {
      failure({
        code: 1,
        message: 'denied',
        PERMISSION_DENIED: 1,
        POSITION_UNAVAILABLE: 2,
        TIMEOUT: 3,
      });
    });

    expect(screen.getByText(/location is blocked/i)).toBeInTheDocument();
    expect(useStore.getState().pickMode).toBe('origin');
  });
});
