/** The rail. These assert on the sentences a judge will read out loud, because
 *  those sentences are the product: the hero degrees, the trade, and the
 *  side-of-street evidence. */

import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import DepartureCurve from '../ui/DepartureCurve';
import HeatProfile from '../ui/HeatProfile';
import Hero from '../ui/Hero';
import RouteCompare from '../ui/RouteCompare';
import ThermalStrip from '../ui/ThermalStrip';
import TurnList from '../ui/TurnList';
import Weather from '../ui/Weather';
import { useStore } from '../state/store';
import {
  DEPARTURE_CURVE,
  FASTEST,
  HEALTH,
  ROUTE_RESPONSE,
  SHADEWAY,
  mockFetch,
} from './fixture';

const INITIAL = useStore.getState();

function loadRoute(overrides: Partial<typeof INITIAL> = {}) {
  useStore.setState({
    ...INITIAL,
    route: ROUTE_RESPONSE,
    routeStatus: 'ready',
    routeError: null,
    routeGeneration: 1,
    overrideRouteId: null,
    departure: DEPARTURE_CURVE,
    departureStatus: 'ready',
    health: HEALTH,
    ...overrides,
  });
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(mockFetch()));
  // jsdom has no rAF budget worth respecting; run the count-up instantly.
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  );
  useStore.setState({ ...INITIAL, route: null, routeStatus: 'idle' });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Hero', () => {
  test('invites the reader to act before any route exists', () => {
    render(<Hero />);
    expect(screen.getByText('Pick two points.')).toBeInTheDocument();
  });

  test('says it is working while a route is in flight', () => {
    useStore.setState({ routeStatus: 'loading' });
    render(<Hero />);
    expect(screen.getByText('Working it out…')).toBeInTheDocument();
  });

  test('the hero number is the chosen route degrees, rounded', () => {
    loadRoute();
    render(<Hero />);
    expect(
      screen.getByLabelText(/Feels like 33 degrees Celsius/i),
    ).toBeInTheDocument();
  });

  test('states the trade in the caption', () => {
    loadRoute();
    render(<Hero />);
    // shadeway is 5 minutes longer and 8 degrees cooler in the fixture
    expect(screen.getByText(/5 extra minutes/)).toBeInTheDocument();
    expect(screen.getByText('8°')).toBeInTheDocument();
  });

  test('does not invent a trade when the fast way is already the cool way', () => {
    loadRoute({ overrideRouteId: 'fastest' });
    render(<Hero />);
    expect(
      screen.getByText(/already the cool way/i),
    ).toBeInTheDocument();
  });
});

describe('RouteCompare', () => {
  test('lists both options with their own degrees', () => {
    loadRoute();
    render(<RouteCompare />);
    const options = screen.getAllByRole('button', { pressed: false });
    expect(options.length).toBeGreaterThan(0);
    expect(screen.getByText('41°')).toBeInTheDocument();
    expect(screen.getByText('33°')).toBeInTheDocument();
  });

  test('marks the recommended option as selected', () => {
    loadRoute();
    render(<RouteCompare />);
    const chosen = screen.getByRole('button', { pressed: true });
    expect(within(chosen).getByText('shadeway')).toBeInTheDocument();
  });

  test('the verdict is the demo sentence', () => {
    loadRoute();
    render(<RouteCompare />);
    const verdict = screen.getByText(/extra/i, { selector: '.verdict' });
    expect(verdict.textContent).toMatch(/5 extra minutes buys you 8°/);
  });

  test('clicking an option changes what the interface shows', async () => {
    loadRoute();
    render(<RouteCompare />);
    await userEvent.click(screen.getByText('fastest'));
    expect(useStore.getState().overrideRouteId).toBe('fastest');
  });

  test('says there is nothing to trade when only one route came back', () => {
    useStore.setState({
      ...INITIAL,
      routeStatus: 'ready',
      route: {
        ...ROUTE_RESPONSE,
        routes: { fastest: FASTEST },
        chosen_route_id: 'fastest',
        frontier: [ROUTE_RESPONSE.frontier[0]!],
      },
    });
    render(<RouteCompare />);
    expect(screen.getByText(/Nothing to trade/i)).toBeInTheDocument();
  });
});

describe('ThermalStrip', () => {
  test('draws one segment per leg for each route', () => {
    loadRoute();
    const { container } = render(<ThermalStrip />);
    const segments = container.querySelectorAll('.strip-seg');
    expect(segments).toHaveLength(FASTEST.legs.length + SHADEWAY.legs.length);
  });

  test('the strip is described for a reader who cannot see it', () => {
    loadRoute();
    render(<ThermalStrip />);
    expect(
      screen.getByLabelText(/shadeway: felt temperature along the route/i),
    ).toBeInTheDocument();
  });

  test('ticks mark the crossings, which is where the side changes', () => {
    loadRoute();
    const { container } = render(<ThermalStrip />);
    const crossings = [...FASTEST.legs, ...SHADEWAY.legs].filter(
      (leg) => leg.kind === 1,
    ).length;
    expect(container.querySelectorAll('.strip-tick')).toHaveLength(crossings);
  });

  test('the legend names every category, so colour is never the only channel', () => {
    loadRoute();
    render(<ThermalStrip />);
    const legend = screen.getByLabelText('UTCI heat stress categories');
    for (const label of ['no stress', 'moderate', 'strong', 'very strong']) {
      expect(within(legend).getByText(label)).toBeInTheDocument();
    }
  });

  test('offers a way back to the route that is not shown', async () => {
    loadRoute();
    render(<ThermalStrip />);
    await userEvent.click(screen.getByText('Show fastest instead'));
    expect(useStore.getState().overrideRouteId).toBe('fastest');
  });
});

describe('TurnList', () => {
  test('gives the side-of-street instruction Google Maps cannot', () => {
    loadRoute();
    render(<TurnList />);
    expect(
      screen.getByText('Cross to the east side of W 45 St'),
    ).toBeInTheDocument();
  });

  test('shows how long the side you are leaving stays sunlit', () => {
    loadRoute();
    render(<TurnList />);
    expect(
      screen.getByText(/the side you are leaving stays sunlit until/i),
    ).toBeInTheDocument();
  });

  test('names the building doing the shading', () => {
    loadRoute();
    render(<TurnList />);
    expect(
      screen.getByText('shaded by the 226 m tower on Broadway'),
    ).toBeInTheDocument();
  });

  test('calls canopy shade dappled rather than pretending it is full shade', () => {
    loadRoute();
    render(<TurnList />);
    expect(
      screen.getByText(/honey locusts overhead — dappled light, not full shade/i),
    ).toBeInTheDocument();
  });

  test('states the delta in the direction the reader is moving', () => {
    loadRoute();
    render(<TurnList />);
    expect(screen.getByText('4.2° cooler')).toBeInTheDocument();
  });

  test('counts the side changes', () => {
    loadRoute();
    render(<TurnList />);
    expect(screen.getByText('1 side change')).toBeInTheDocument();
  });
});

describe('HeatProfile', () => {
  test('offers the three preset profiles', () => {
    loadRoute();
    render(<HeatProfile />);
    for (const label of ['standard', 'sensitive', 'high risk']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  test('shows the one number the profile actually is', () => {
    loadRoute();
    render(<HeatProfile />);
    expect(screen.getByText('1 min per degree')).toBeInTheDocument();
  });

  test('switching profile changes the number, and says who it is for', async () => {
    loadRoute();
    render(<HeatProfile />);
    await userEvent.click(screen.getByText('high risk'));
    expect(useStore.getState().profileKey).toBe('high_risk');
    expect(screen.getByText('6 min per degree')).toBeInTheDocument();
    expect(screen.getByText(/Over 65, pregnant/)).toBeInTheDocument();
  });

  test('pace is selectable and reported in the units the model uses', async () => {
    loadRoute();
    render(<HeatProfile />);
    await userEvent.click(screen.getByText('brisk'));
    expect(useStore.getState().walkSpeedMs).toBeCloseTo(1.6);
    expect(screen.getByText('1.60 m/s')).toBeInTheDocument();
  });
});

describe('DepartureCurve', () => {
  test('states the wait and the saving in words', () => {
    loadRoute();
    render(<DepartureCurve />);
    const note = document.querySelector('.chart-note');
    expect(note?.textContent).toMatch(/Leave 45 minutes later/);
    expect(note?.textContent).toMatch(/7° cooler/);
  });

  test('describes the curve for a screen reader', () => {
    loadRoute();
    render(<DepartureCurve />);
    expect(
      screen.getByLabelText(/coolest departure is .* at 26 degrees/i),
    ).toBeInTheDocument();
  });

  test('offers a table view of the same numbers', async () => {
    loadRoute();
    render(<DepartureCurve />);
    await userEvent.click(screen.getByText('Show the numbers'));
    const table = screen.getByRole('table');
    expect(within(table).getAllByRole('row')).toHaveLength(
      DEPARTURE_CURVE.points.length + 1,
    );
  });

  test('can hand the best departure back to the scrubber', async () => {
    loadRoute();
    render(<DepartureCurve />);
    const before = useStore.getState().scrubAt.getTime();
    await userEvent.click(screen.getByText(/^Plan for/));
    expect(useStore.getState().scrubAt.getTime()).not.toBe(before);
  });

  test('says so plainly when waiting will not help', () => {
    loadRoute({
      departure: {
        points: DEPARTURE_CURVE.points.map((point) => ({
          ...point,
          best_mean_feels_like_c: 33,
        })),
        now_index: 0,
        best_index: 0,
      },
    });
    render(<DepartureCurve />);
    expect(
      screen.getByText(/as good as it gets while the sun is up/i),
    ).toBeInTheDocument();
  });

  test('never recommends a departure after dark', () => {
    // Late August in New York: the sun sets around 19:40, so the 21:00 and
    // 22:00 departures below are night. They are genuinely cooler and the curve
    // must still show them -- but "leave at ten" is nightfall, not shade.
    loadRoute({
      departure: {
        points: [
          { depart_iso: '2026-08-24T18:00:00-04:00', best_mean_feels_like_c: 30, best_duration_s: 1200 },
          { depart_iso: '2026-08-24T19:00:00-04:00', best_mean_feels_like_c: 28, best_duration_s: 1200 },
          { depart_iso: '2026-08-24T21:00:00-04:00', best_mean_feels_like_c: 22, best_duration_s: 1200 },
          { depart_iso: '2026-08-24T22:00:00-04:00', best_mean_feels_like_c: 20, best_duration_s: 1200 },
        ],
        now_index: 0,
        best_index: 3,
      },
    });
    render(<DepartureCurve />);
    const note = document.querySelector('.chart-note');
    // 19:00 is the coolest departure still in daylight: 60 minutes, 2 degrees.
    expect(note?.textContent).toMatch(/Leave 60 minutes later/);
    expect(note?.textContent).toMatch(/2° cooler/);
    expect(
      screen.getByText(/that is nightfall rather than shade/i),
    ).toBeInTheDocument();
  });

  test('marks sunset on the curve when the window crosses it', () => {
    loadRoute({
      departure: {
        points: [
          { depart_iso: '2026-08-24T18:00:00-04:00', best_mean_feels_like_c: 30, best_duration_s: 1200 },
          { depart_iso: '2026-08-24T19:00:00-04:00', best_mean_feels_like_c: 28, best_duration_s: 1200 },
          { depart_iso: '2026-08-24T21:00:00-04:00', best_mean_feels_like_c: 22, best_duration_s: 1200 },
        ],
        now_index: 0,
        best_index: 2,
      },
    });
    render(<DepartureCurve />);
    expect(screen.getByText('sunset')).toBeInTheDocument();
  });

  test('a failed sweep does not pretend to have a curve', () => {
    loadRoute({ departure: null, departureStatus: 'error' });
    render(<DepartureCurve />);
    expect(
      screen.getByText(/The route above is unaffected/i),
    ).toBeInTheDocument();
  });
});

describe('Weather', () => {
  test('shows the radiation the model was actually fed', () => {
    loadRoute();
    render(<Weather />);
    expect(screen.getByText('799 W/m²')).toBeInTheDocument();
    expect(screen.getByText('148 W/m²')).toBeInTheDocument();
  });

  test('flags stand-in weather instead of presenting it as an observation', () => {
    loadRoute({
      route: {
        ...ROUTE_RESPONSE,
        weather: {
          ...ROUTE_RESPONSE.weather,
          source: 'fallback (network unavailable)',
        },
      },
    });
    render(<Weather />);
    expect(screen.getByText(/not an observation/i)).toBeInTheDocument();
  });
});
