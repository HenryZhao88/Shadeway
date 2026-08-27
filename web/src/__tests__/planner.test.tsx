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

    expect(screen.getByText('Where are you going?')).toBeInTheDocument();
    expect(screen.getByText('Use my current location')).toBeInTheDocument();
    expect(screen.getByText('Choose destination on the map')).toBeInTheDocument();
    expect(useStore.getState().route).toBeNull();
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
