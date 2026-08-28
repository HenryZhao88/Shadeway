import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { useStore } from '../state/store';
import Endpoints from '../ui/Endpoints';
import { mockFetch } from './fixture';

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

describe('route planner', () => {
  test('opens without silently calculating a sample route', () => {
    render(<Endpoints />);

    expect(screen.getByText('Plan your route')).toBeInTheDocument();
    expect(screen.getByLabelText('Starting point')).toBeInTheDocument();
    expect(screen.getByLabelText('Destination')).toBeInTheDocument();
    expect(screen.getByText('Use my current location')).toBeInTheDocument();
    expect(useStore.getState().route).toBeNull();
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
