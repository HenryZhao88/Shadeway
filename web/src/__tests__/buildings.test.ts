import { afterEach, describe, expect, test, vi } from 'vitest';

import {
  clearBuildingTileCache,
  getCompleteBuildings,
  type Bbox,
} from '../api/client';

afterEach(() => {
  vi.unstubAllGlobals();
  clearBuildingTileCache();
});

function response(buildingId: number, truncated = false) {
  return new Response(
    JSON.stringify({
      buildings: truncated
        ? []
        : [
            {
              building_id: buildingId,
              height_m: 20,
              base_m: 0,
              polygon: [
                [-74, 40.7],
                [-73.999, 40.7],
                [-73.999, 40.701],
              ],
            },
          ],
      truncated,
    }),
    { status: 200, headers: { 'content-type': 'application/json' } },
  );
}

function requestedBbox(input: RequestInfo | URL): Bbox {
  const url = new URL(String(input), 'https://shadeway.test');
  return url.searchParams.get('bbox')!.split(',').map(Number) as Bbox;
}

describe('complete building loading', () => {
  test('starts with bounded tiles instead of one viewport-sized response', async () => {
    const requested: Bbox[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        requested.push(requestedBbox(input));
        return response(requested.length);
      }),
    );

    const result = await getCompleteBuildings([-74, 40.7, -73.97, 40.72]);

    expect(requested.length).toBeGreaterThan(1);
    expect(
      Math.max(...requested.map(([west, , east]) => east - west)),
    ).toBeLessThanOrEqual(0.0075 + 1e-9);
    expect(
      Math.max(...requested.map(([, south, , north]) => north - south)),
    ).toBeLessThanOrEqual(0.005 + 1e-9);
    expect(result.buildings).toHaveLength(requested.length);
    expect(result.truncated).toBe(false);
  });

  test('falls back to one bounded response if completeness is requested at city scale', async () => {
    const spy = vi.fn(async () => response(1, true));
    vi.stubGlobal('fetch', spy);

    const result = await getCompleteBuildings([-74.2, 40.6, -73.7, 40.95]);

    expect(spy).toHaveBeenCalledTimes(1);
    expect(result.truncated).toBe(true);
  });

  test('subdivides a dense tile and discards its incomplete parent result', async () => {
    let calls = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        calls += 1;
        const [west, , east] = requestedBbox(input);
        return response(calls, east - west > 0.005);
      }),
    );

    const result = await getCompleteBuildings([-74.002, 40.701, -73.996, 40.704]);

    expect(calls).toBe(5);
    expect(result.buildings).toHaveLength(4);
    expect(result.truncated).toBe(false);
  });

  test('deduplicates footprints that intersect adjacent tile boundaries', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => response(42)),
    );

    const result = await getCompleteBuildings([-74, 40.7, -73.97, 40.72]);

    expect(result.buildings.map((building) => building.building_id)).toEqual([42]);
  });

  test('reuses fixed tiles when the viewport pans slightly', async () => {
    let calls = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        calls += 1;
        return response(calls);
      }),
    );

    await getCompleteBuildings([-74, 40.7, -73.99, 40.705]);
    const afterFirstView = calls;
    await getCompleteBuildings([-73.999, 40.701, -73.991, 40.704]);

    expect(calls).toBe(afterFirstView);
  });
});
