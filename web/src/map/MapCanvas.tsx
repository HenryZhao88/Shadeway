/** The map: a MapLibre basemap with deck.gl on top.
 *
 * deck.gl owns the camera so the shadow projection and the basemap can never
 * drift apart. The basemap is decoration; the buildings, routes and pins are
 * ours, and they survive the basemap failing to load.
 */

import DeckGL from '@deck.gl/react';
import type { PickingInfo } from '@deck.gl/core';
import maplibregl from 'maplibre-gl';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Map as MapLibreMap } from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';

import { AMENITY_LABEL, type Amenity, type Bbox } from '../api/client';
import { degrees, heatCategory } from '../heat';
import { chosenRouteId, useStore } from '../state/store';
import { clock, sunPosition } from '../sun/position';
import { BASEMAP_URL, FALLBACK_STYLE, INITIAL_VIEW } from './basemapStyle';
import {
  amenityLayer,
  buildingLayer,
  endpointLayer,
  routeLayers,
  shadowLayer,
  sunlitGroundLayer,
  waypointLayer,
  type EndpointDatum,
} from './layers';
import { shadowPolygons } from './shadows';

interface ViewState {
  longitude: number;
  latitude: number;
  zoom: number;
  pitch: number;
  bearing: number;
}

/** Refetching viewport data on every frame of a pan would hammer the server for
 *  no visual gain, so wait for the camera to settle. */
const VIEW_SETTLE_MS = 260;
const MAX_VIEW_RETRIES = 5;

export default function MapCanvas() {
  const [viewState, setViewState] = useState<ViewState>({ ...INITIAL_VIEW });
  const [basemapFailed, setBasemapFailed] = useState(false);
  const [tooltip, setTooltip] = useState<{
    x: number;
    y: number;
    lines: string[];
  } | null>(null);
  const settleTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const lastBbox = useRef<string>('');
  const retryBbox = useRef<string>('');
  const retryCount = useRef(0);

  const scrubAt = useStore((s) => s.scrubAt);
  const route = useStore((s) => s.route);
  const buildings = useStore((s) => s.buildings);
  const amenities = useStore((s) => s.amenities);
  const showAmenities = useStore((s) => s.showAmenities);
  const origin = useStore((s) => s.origin);
  const destination = useStore((s) => s.destination);
  const pickMode = useStore((s) => s.pickMode);
  const hoveredLegIndex = useStore((s) => s.hoveredLegIndex);
  const chosenId = useStore(chosenRouteId);
  const setPlace = useStore((s) => s.setPlace);
  const plant = useStore((s) => s.plant);
  const hoverLeg = useStore((s) => s.hoverLeg);
  const fetchViewportData = useStore((s) => s.fetchViewportData);

  const bbox = useMemo<Bbox>(() => bboxFor(viewState), [viewState]);

  // The sun, from the same client-side solar code the readouts use. Dragging
  // the scrubber recomputes this and the shadows below at frame rate, without
  // a single request.
  const sun = useMemo(
    () => sunPosition(scrubAt, viewState.latitude, viewState.longitude),
    [scrubAt, viewState.latitude, viewState.longitude],
  );
  const shadows = useMemo(
    () => shadowPolygons(buildings, sun, viewState.latitude),
    [buildings, sun, viewState.latitude],
  );

  const requestViewportData = useCallback(
    (next: ViewState) => {
      clearTimeout(settleTimer.current);
      settleTimer.current = setTimeout(() => {
        const box = bboxFor(next);
        const key = box.map((v) => v.toFixed(3)).join(',');
        if (key === lastBbox.current) return;
        if (key !== retryBbox.current) {
          retryBbox.current = key;
          retryCount.current = 0;
        }
        lastBbox.current = key;
        void fetchViewportData(box).then((ok) => {
          if (ok) {
            retryCount.current = 0;
            return;
          }
          // forget a bbox we failed on, so the next tick tries it again
          if (lastBbox.current === key) {
            lastBbox.current = '';
            retryCount.current += 1;
          }
        });
      }, VIEW_SETTLE_MS);
    },
    [fetchViewportData],
  );

  // A camera that never moves still needs data after the window resizes: the
  // visible bbox grew, and nothing else would ask for the newly exposed blocks.
  useEffect(() => {
    requestViewportData(viewState);
    const onResize = () => requestViewportData(viewState);
    window.addEventListener('resize', onResize);
    // A slow-starting server is the common first-load failure. Retry a bounded
    // number of times; a permanent failure must not poll the endpoint forever.
    const retry = setInterval(() => {
      if (!lastBbox.current && retryCount.current < MAX_VIEW_RETRIES) {
        requestViewportData(viewState);
      }
    }, 2000);
    return () => {
      window.removeEventListener('resize', onResize);
      clearInterval(retry);
      clearTimeout(settleTimer.current);
    };
  }, [requestViewportData, viewState]);

  const layers = useMemo(() => {
    const routes = route ? Object.values(route.routes) : [];
    const chosen = chosenId ? route?.routes[chosenId] : undefined;
    const endpoints: EndpointDatum[] = [
      {
        position: [origin.lon, origin.lat],
        kind: 'origin',
        label: origin.label,
      },
      {
        position: [destination.lon, destination.lat],
        kind: 'destination',
        label: destination.label,
      },
    ];
    return [
      sunlitGroundLayer(bbox, sun.elevationDeg),
      shadowLayer(shadows),
      buildingLayer(buildings),
      ...(showAmenities ? [amenityLayer(amenities)] : []),
      ...routeLayers(routes, chosenId, hoveredLegIndex),
      ...(chosen?.waypoints.length ? [waypointLayer(chosen.waypoints)] : []),
      endpointLayer(endpoints),
    ];
  }, [
    amenities,
    bbox,
    buildings,
    chosenId,
    destination,
    hoveredLegIndex,
    origin,
    route,
    shadows,
    showAmenities,
    sun.elevationDeg,
  ]);

  const onHover = useCallback(
    (info: PickingInfo) => {
      const lines = describe(info);
      if (!lines) {
        setTooltip(null);
        if (hoveredLegIndex !== null) hoverLeg(null);
        return;
      }
      setTooltip({ x: info.x, y: info.y, lines });
      const legIndex = (info.object as { legIndex?: number } | null)?.legIndex;
      hoverLeg(typeof legIndex === 'number' ? legIndex : null);
    },
    [hoverLeg, hoveredLegIndex],
  );

  const onClick = useCallback(
    (info: PickingInfo) => {
      if (pickMode === 'none' || !info.coordinate) return;
      const [lon, lat] = info.coordinate as [number, number];
      if (pickMode === 'plant') {
        void plant([{ lat, lon }]);
        return;
      }
      setPlace(pickMode, {
        lat,
        lon,
        label: `${lat.toFixed(4)}, ${lon.toFixed(4)}`,
      });
    },
    [pickMode, plant, setPlace],
  );

  const cursor = pickMode === 'none' ? 'grab' : 'crosshair';

  return (
    <>
      <DeckGL
        viewState={viewState}
        controller={{ dragRotate: true, touchRotate: true }}
        layers={layers}
        onViewStateChange={({ viewState: next }) => {
          const view = next as ViewState;
          setViewState(view);
          requestViewportData(view);
        }}
        onHover={onHover}
        onClick={onClick}
        getCursor={() => cursor}
        style={{ position: 'absolute', inset: '0' }}
      >
        <MapLibreMap
          mapLib={maplibregl}
          mapStyle={basemapFailed ? FALLBACK_STYLE : BASEMAP_URL}
          onError={() => setBasemapFailed(true)}
          attributionControl={false}
        />
      </DeckGL>

      {tooltip ? (
        <div
          className="map-tooltip"
          style={{ left: tooltip.x, top: tooltip.y }}
          role="presentation"
        >
          {tooltip.lines.map((line) => (
            <div key={line}>{line}</div>
          ))}
        </div>
      ) : null}

      <div className="map-overlay map-readout num" aria-hidden="true">
        <div>
          <span>sun</span>
          <b>{clock(scrubAt)}</b>
        </div>
        <div>
          <span>elevation</span>
          <b>
            {sun.elevationDeg > 0 ? `${sun.elevationDeg.toFixed(0)}°` : 'below'}
          </b>
        </div>
        <div>
          <span>azimuth</span>
          <b>{sun.azimuthDeg.toFixed(0)}°</b>
        </div>
        <div>
          <span>buildings</span>
          <b>{buildings.length}</b>
        </div>
        <div>
          <span>pins</span>
          <b>{showAmenities ? amenities.length : 0}</b>
        </div>
      </div>
    </>
  );
}

function describe(info: PickingInfo): string[] | null {
  if (!info.object || !info.layer) return null;
  const id = info.layer.id;
  if (id.startsWith('route-')) {
    const leg = info.object as { feels: number; streetName: string };
    return [
      `${leg.streetName} · ${degrees(leg.feels)}°`,
      heatCategory(leg.feels),
    ];
  }
  if (id === 'amenities') {
    const amenity = info.object as Amenity;
    return [amenity.name || 'Unnamed', AMENITY_LABEL[amenity.kind] ?? 'amenity'];
  }
  if (id === 'waypoints') {
    const waypoint = info.object as { name: string; detour_s: number };
    return [
      waypoint.name,
      `rest stop · ${Math.round(waypoint.detour_s / 60)} min detour`,
    ];
  }
  if (id === 'endpoints') {
    const endpoint = info.object as EndpointDatum;
    return [endpoint.label, endpoint.kind === 'origin' ? 'start' : 'finish'];
  }
  return null;
}

/** Approximate viewport bounds from the camera. Exact bounds would need the
 *  unprojected corners of a pitched frustum; this is a data-fetch window, and
 *  a generous one costs a few extra pins, not correctness. */
function bboxFor(view: ViewState): Bbox {
  const spanLon = 360 / 2 ** view.zoom;
  const spanLat = spanLon * 0.62;
  // A pitched camera sees further toward the horizon than a flat one, but only
  // a little further is worth fetching: the rest is a haze of rooftops that
  // costs a thousand footprints and shows nothing.
  const reach = 1 + view.pitch / 110;
  return [
    view.longitude - spanLon * reach,
    view.latitude - spanLat * reach,
    view.longitude + spanLon * reach,
    view.latitude + spanLat * reach,
  ];
}
