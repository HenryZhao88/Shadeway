import { afterEach, describe, expect, test, vi } from 'vitest';

import {
  clearBuildingTileCache,
  getBuildingOverview,
  getCompleteBuildings,
  getPackedBuildings,
  getViewportBuildings,
  type Bbox,
  type BuildingFootprint,
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

function packedResponse(
  buildings: BuildingFootprint[],
  truncated = false,
): Response {
  const coordinateCount = buildings.reduce(
    (total, building) => total + building.polygon.length,
    0,
  );
  const buildingCount = buildings.length;
  const offsetsStart = 12 + buildingCount * 12;
  const coordinatesStart = offsetsStart + (buildingCount + 1) * 4;
  const buffer = new ArrayBuffer(coordinatesStart + coordinateCount * 8);
  new Uint8Array(buffer, 0, 4).set([0x53, 0x57, 0x42, 0x31]);
  const header = new DataView(buffer);
  header.setUint32(4, buildingCount, true);
  header.setUint32(8, coordinateCount, true);
  const ids = new Int32Array(buffer, 12, buildingCount);
  const heights = new Float32Array(buffer, 12 + buildingCount * 4, buildingCount);
  const bases = new Float32Array(buffer, 12 + buildingCount * 8, buildingCount);
  const offsets = new Uint32Array(buffer, offsetsStart, buildingCount + 1);
  const coordinates = new Int32Array(
    buffer,
    coordinatesStart,
    coordinateCount * 2,
  );
  let coordinateIndex = 0;
  buildings.forEach((building, buildingIndex) => {
    ids[buildingIndex] = building.building_id;
    heights[buildingIndex] = building.height_m;
    bases[buildingIndex] = building.base_m;
    offsets[buildingIndex] = coordinateIndex;
    for (const [lon, lat] of building.polygon) {
      coordinates[coordinateIndex * 2] = Math.round(lon * 1_000_000);
      coordinates[coordinateIndex * 2 + 1] = Math.round(lat * 1_000_000);
      coordinateIndex += 1;
    }
  });
  offsets[buildingCount] = coordinateIndex;
  return new Response(buffer, {
    status: 200,
    headers: {
      'content-type': 'application/vnd.shadeway.buildings',
      'x-shadeway-truncated': truncated ? '1' : '0',
    },
  });
}

const PACKED_BUILDING: BuildingFootprint = {
  building_id: 71,
  height_m: 37.5,
  base_m: 2,
  polygon: [
    [-74, 40.7],
    [-73.999, 40.7],
    [-73.999, 40.701],
    [-74, 40.7],
  ],
};

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

describe('packed building loading', () => {
  test('loads and reuses the whole-city overview once', async () => {
    const spy = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      packedResponse([PACKED_BUILDING]),
    );
    vi.stubGlobal('fetch', spy);

    const first = await getBuildingOverview();
    const second = await getBuildingOverview();

    expect(spy).toHaveBeenCalledTimes(1);
    expect(String(spy.mock.calls[0]![0])).toContain('/buildings-overview-v2.bin');
    expect(first).toBe(second);
    expect(first.buildings).toEqual([PACKED_BUILDING]);
  });

  test('decodes typed arrays without losing geometry or height precision', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => packedResponse([PACKED_BUILDING])));

    const result = await getPackedBuildings([-74.01, 40.69, -73.99, 40.71]);

    expect(result).toEqual({ buildings: [PACKED_BUILDING], truncated: false });
  });

  test('loads a complete street viewport in one request', async () => {
    const spy = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      packedResponse([PACKED_BUILDING]),
    );
    vi.stubGlobal('fetch', spy);

    const result = await getViewportBuildings([
      -74.001,
      40.699,
      -73.998,
      40.702,
    ]);

    expect(spy).toHaveBeenCalledTimes(1);
    expect(String(spy.mock.calls[0]![0])).toContain('/buildings.bin?bbox=');
    expect(result.buildings).toEqual([PACKED_BUILDING]);
  });

  test('reuses a padded packed viewport during a small pan', async () => {
    const spy = vi.fn(async () => packedResponse([PACKED_BUILDING]));
    vi.stubGlobal('fetch', spy);

    await getViewportBuildings([-74.001, 40.699, -73.998, 40.702]);
    await getViewportBuildings([-74.0008, 40.6992, -73.9982, 40.7018]);

    expect(spy).toHaveBeenCalledTimes(1);
  });

  test('falls back to bounded tiles when the packed safety cap is reached', async () => {
    const spy = vi.fn(async (input: RequestInfo | URL) =>
      String(input).includes('/buildings.bin')
        ? packedResponse([], true)
        : response(42),
    );
    vi.stubGlobal('fetch', spy);

    const result = await getViewportBuildings([-74, 40.7, -73.99, 40.705]);

    expect(spy.mock.calls.length).toBeGreaterThan(1);
    expect(result.buildings.map((building) => building.building_id)).toEqual([42]);
  });
});
