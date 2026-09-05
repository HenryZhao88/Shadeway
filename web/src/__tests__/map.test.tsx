import { act, cleanup, render } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import MapCanvas from '../map/MapCanvas';
import { bboxFor, BUILDING_DETAIL_ZOOM, type ViewState } from '../map/camera';
import { useStore } from '../state/store';

const deck = vi.hoisted(() => ({
  props: {} as {
    viewState: ViewState;
    onViewStateChange: (event: { viewState: ViewState }) => void;
    onHover: (event: unknown) => void;
  },
}));

vi.mock('@deck.gl/react', () => ({
  default: (props: typeof deck.props) => {
    deck.props = props;
    return <div />;
  },
}));
vi.mock('react-map-gl/maplibre', () => ({ Map: () => null }));
vi.mock('maplibre-gl', () => ({ default: {} }));

const INITIAL = useStore.getState();
const fetchViewportData = vi.fn().mockResolvedValue(true);

beforeEach(() => {
  vi.useFakeTimers();
  fetchViewportData.mockClear();
  useStore.setState({
    ...INITIAL,
    fetchViewportData,
    fetchBuildingOverview: vi.fn().mockResolvedValue(undefined),
  });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  useStore.setState(INITIAL);
});

async function moveTo(viewState: ViewState) {
  act(() => deck.props.onViewStateChange({ viewState }));
  await act(async () => vi.advanceTimersByTimeAsync(300));
}

test('crossing into street detail fetches buildings even when the rounded bbox is unchanged', async () => {
  render(<MapCanvas />);
  const overview = { ...deck.props.viewState, zoom: BUILDING_DETAIL_ZOOM - 0.00001 };
  const detail = { ...overview, zoom: BUILDING_DETAIL_ZOOM };
  expect(bboxFor(overview).map((value) => value.toFixed(3))).toEqual(
    bboxFor(detail).map((value) => value.toFixed(3)),
  );
  await moveTo(overview);
  expect(fetchViewportData).toHaveBeenLastCalledWith(expect.any(Array), {
    maxFeatures: 0,
    complete: false,
  });

  await moveTo(detail);

  expect(fetchViewportData).toHaveBeenLastCalledWith(expect.any(Array), {
    maxFeatures: 450,
    complete: true,
  });
});

test('hovering another route does not highlight a same-numbered leg on the chosen route', () => {
  render(<MapCanvas />);
  act(() => deck.props.onHover({
    layer: { id: 'route-alternative' },
    object: { legIndex: 2, chosen: false, streetName: 'Broadway', feels: 30 },
    x: 20,
    y: 40,
  }));
  expect(useStore.getState().hoveredLegIndex).toBeNull();
});
