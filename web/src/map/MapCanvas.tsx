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
import type { UnitSystem } from '../units';
import { BASEMAP_URL, FALLBACK_STYLE, INITIAL_VIEW } from './basemapStyle';
import {
  bboxFor,
  buildingLevels,
  fitRoute,
  renderBudget,
  type ViewState,
} from './camera';
import {
  amenityLayer,
  buildingLayer,
  buildingOverviewLayer,
  currentLocationLayers,
  endpointLayer,
  routeLayers,
  shadowLayer,
  sunlitGroundLayer,
  waypointLayer,
  type EndpointDatum,
} from './layers';
import { shadowPolygons } from './shadows';

/** Refetching viewport data on every frame of a pan would hammer the server for
 *  no visual gain, so wait for the camera to settle. */
const VIEW_SETTLE_MS = 260;
const MAX_VIEW_RETRIES = 5;

export default function MapCanvas() {
  const [viewState, setViewState] = useState<ViewState>({ ...INITIAL_VIEW });
  const [basemapFailed, setBasemapFailed] = useState(false);
  const [isRotating, setIsRotating] = useState(false);
  const [tooltip, setTooltip] = useState<{
    x: number;
    y: number;
    lines: string[];
  } | null>(null);
  const settleTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const lastBbox = useRef<string>('');
  const retryBbox = useRef<string>('');
  const retryCount = useRef(0);
  const lastLocationFocus = useRef(0);
  const lastRouteGeneration = useRef(0);

  const scrubAt = useStore((s) => s.scrubAt);
  const route = useStore((s) => s.route);
  const routeGeneration = useStore((s) => s.routeGeneration);
  const unitSystem = useStore((s) => s.unitSystem);
  const buildings = useStore((s) => s.buildings);
  const buildingOverview = useStore((s) => s.buildingOverview);
  const amenities = useStore((s) => s.amenities);
  const showAmenities = useStore((s) => s.showAmenities);
  const origin = useStore((s) => s.origin);
  const destination = useStore((s) => s.destination);
  const currentLocation = useStore((s) => s.currentLocation);
  const locationFocus = useStore((s) => s.locationFocus);
  const pickMode = useStore((s) => s.pickMode);
  const hoveredLegIndex = useStore((s) => s.hoveredLegIndex);
  const chosenId = useStore(chosenRouteId);
  const setPlace = useStore((s) => s.setPlace);
  const plant = useStore((s) => s.plant);
  const hoverLeg = useStore((s) => s.hoverLeg);
  const fetchViewportData = useStore((s) => s.fetchViewportData);
  const fetchBuildingOverview = useStore((s) => s.fetchBuildingOverview);

  const bbox = useMemo<Bbox>(() => bboxFor(viewState), [viewState]);
  const budget = useMemo(() => renderBudget(viewState), [viewState]);
  const buildingLevelsForView = useMemo(
    () => buildingLevels(budget.showShadows, buildingOverview, buildings),
    [budget.showShadows, buildingOverview, buildings],
  );

  useEffect(() => {
    void fetchBuildingOverview();
  }, [fetchBuildingOverview]);

  useEffect(() => {
    if (
      !currentLocation ||
      locationFocus === 0 ||
      locationFocus === lastLocationFocus.current
    ) {
      return;
    }
    lastLocationFocus.current = locationFocus;
    setViewState((current) => ({
      ...current,
      longitude: currentLocation.lon,
      latitude: currentLocation.lat,
      zoom: Math.max(current.zoom, 15.4),
      pitch: 38,
      bearing: 0,
    }));
  }, [currentLocation, locationFocus]);

  useEffect(() => {
    if (
      !route ||
      !origin ||
      !destination ||
      routeGeneration === lastRouteGeneration.current
    ) {
      return;
    }
    lastRouteGeneration.current = routeGeneration;
    setViewState((current) => fitRoute(current, origin, destination));
  }, [destination, origin, route, routeGeneration]);

  // The sun, from the same client-side solar code the readouts use. Dragging
  // the scrubber recomputes this and the shadows below at frame rate, without
  // a single request.
  const sun = useMemo(
    () => sunPosition(scrubAt, viewState.latitude, viewState.longitude),
    [scrubAt, viewState.latitude, viewState.longitude],
  );
  const shadows = useMemo(
    () => (budget.showShadows ? shadowPolygons(buildings, sun, viewState.latitude) : []),
    [budget.showShadows, buildings, sun, viewState.latitude],
  );

  const requestViewportData = useCallback(
    (next: ViewState) => {
      clearTimeout(settleTimer.current);
      settleTimer.current = setTimeout(() => {
        const box = bboxFor(next);
        const load = renderBudget(next).buildingLoad;
        // A tiny zoom can cross the detail threshold without changing any
        // rounded bounds. That still needs a different building request.
        const key = `${box.map((v) => v.toFixed(3)).join(',')}:${load.maxFeatures}:${load.complete}`;
        if (key === lastBbox.current) return;
        if (key !== retryBbox.current) {
          retryBbox.current = key;
          retryCount.current = 0;
        }
        lastBbox.current = key;
        void fetchViewportData(box, load).then((ok) => {
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

  // The camera, for the listeners below to read without being rebuilt around
  // it. onViewStateChange already asks for data on every frame it moves.
  const latestView = useRef(viewState);
  latestView.current = viewState;

  // A camera that never moves still needs data after the window resizes: the
  // visible bbox grew, and nothing else would ask for the newly exposed blocks.
  //
  // Mounted once. With viewState in the dependency array this whole effect tore
  // down and rebuilt on every frame of every pan — a listener swap and two
  // timers per frame, plus a second call to requestViewportData alongside the
  // one onViewStateChange was already making. The retry interval in particular
  // was recreated faster than its own 2 s period, so it could never fire at
  // all while anyone was touching the map.
  // A camera move the reader did not make — fitting a new route, centring on
  // their location — never reaches onViewStateChange, which only fires for
  // interaction. Without this the map keeps whatever geometry it had before the
  // move: after a route auto-zoomed, the buildings were still the ones fetched
  // for the opening view, so most of what was on screen had none.
  //
  // Cheap enough to run per frame: it resets one timer, and the settle callback
  // drops any bbox it has already asked for.
  useEffect(() => {
    requestViewportData(viewState);
  }, [requestViewportData, viewState]);

  useEffect(() => {
    requestViewportData(latestView.current);
    const onResize = () => requestViewportData(latestView.current);
    window.addEventListener('resize', onResize);
    // A slow-starting server is the common first-load failure. Retry a bounded
    // number of times; a permanent failure must not poll the endpoint forever.
    const retry = setInterval(() => {
      if (!lastBbox.current && retryCount.current < MAX_VIEW_RETRIES) {
        requestViewportData(latestView.current);
      }
    }, 2000);
    const settle = settleTimer;
    return () => {
      window.removeEventListener('resize', onResize);
      clearInterval(retry);
      clearTimeout(settle.current);
    };
  }, [requestViewportData]);

  const layers = useMemo(() => {
    const routes = route ? Object.values(route.routes) : [];
    const chosen = chosenId ? route?.routes[chosenId] : undefined;
    const endpoints: EndpointDatum[] = [];
    if (origin) {
      endpoints.push({
        position: [origin.lon, origin.lat],
        kind: 'origin',
        label: origin.label,
      });
    }
    if (destination) {
      endpoints.push({
        position: [destination.lon, destination.lat],
        kind: 'destination',
        label: destination.label,
      });
    }
    return [
      sunlitGroundLayer(bbox, sun.elevationDeg),
      ...(budget.showShadows ? [shadowLayer(shadows)] : []),
      buildingOverviewLayer(buildingLevelsForView.overview),
      buildingLayer(buildingLevelsForView.detail),
      ...(showAmenities ? [amenityLayer(amenities)] : []),
      ...routeLayers(routes, chosenId, hoveredLegIndex),
      ...(chosen?.waypoints.length ? [waypointLayer(chosen.waypoints)] : []),
      endpointLayer(endpoints),
      ...currentLocationLayers(
        currentLocation
          ? {
              position: [currentLocation.lon, currentLocation.lat],
              accuracyM: currentLocation.accuracyM,
            }
          : null,
      ),
    ];
  }, [
    amenities,
    budget.showShadows,
    bbox,
    chosenId,
    currentLocation,
    destination,
    hoveredLegIndex,
    origin,
    buildingLevelsForView,
    route,
    shadows,
    showAmenities,
    sun.elevationDeg,
  ]);

  const onHover = useCallback(
    (info: PickingInfo) => {
      const lines = describe(info, unitSystem);
      if (!lines) {
        setTooltip(null);
        if (hoveredLegIndex !== null) hoverLeg(null);
        return;
      }
      setTooltip({ x: info.x, y: info.y, lines });
      const leg = info.object as { legIndex?: number; chosen?: boolean } | null;
      // Leg indexes belong to their route, while the linked strip shows only
      // the chosen route. An alternative's index must not highlight that strip.
      hoverLeg(leg?.chosen && typeof leg.legIndex === 'number' ? leg.legIndex : null);
    },
    [hoverLeg, hoveredLegIndex, unitSystem],
  );

  const onClick = useCallback(
    (info: PickingInfo) => {
      if (!info.coordinate) return;
      const [lon, lat] = info.coordinate as [number, number];
      if (pickMode === 'plant') {
        void plant([{ lat, lon }]);
        return;
      }
      const mode =
        pickMode !== 'none'
          ? pickMode
          : !origin
            ? 'origin'
            : !destination
              ? 'destination'
              : null;
      if (!mode) return;
      setPlace(mode, {
        lat,
        lon,
        label: pickedLabel(info),
      });
    },
    [destination, origin, pickMode, plant, setPlace],
  );

  const restingCursor =
    pickMode === 'none' && origin && destination ? 'grab' : 'crosshair';

  return (
    <div
      className="map-viewport"
      onContextMenu={(event) => event.preventDefault()}
    >
      <DeckGL
        viewState={viewState}
        controller={{
          dragPan: true,
          dragRotate: true,
          touchRotate: true,
          inertia: 180,
        }}
        layers={layers}
        onViewStateChange={({ viewState: next }) => {
          const view = next as ViewState;
          setViewState(view);
          requestViewportData(view);
        }}
        onHover={onHover}
        onClick={onClick}
        onInteractionStateChange={(state) => {
          setIsRotating(Boolean(state.isRotating));
        }}
        getCursor={({ isDragging }) => (isDragging ? 'grabbing' : restingCursor)}
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
          <b>
            {buildingLevelsForView.detail.length ||
              buildingLevelsForView.overview.length}
          </b>
        </div>
        <div>
          <span>pins</span>
          <b>{showAmenities ? amenities.length : 0}</b>
        </div>
      </div>

      <div className="map-overlay map-context" aria-hidden="true">
        <span className="eyebrow">New York City</span>
        <b>{budget.showShadows ? 'street shade' : 'city overview'}</b>
        <span>
          {budget.showShadows
            ? 'exact 3D buildings and live shadows'
            : 'continuous 3D building overview'}
        </span>
        <span className={isRotating ? 'is-active' : undefined}>
          {isRotating ? 'rotating and tilting' : 'right-drag to rotate and tilt'}
        </span>
      </div>
    </div>
  );
}

function describe(info: PickingInfo, unitSystem: UnitSystem): string[] | null {
  if (!info.object || !info.layer) return null;
  const id = info.layer.id;
  if (id.startsWith('route-')) {
    const leg = info.object as { feels: number; streetName: string };
    return [
      `${leg.streetName} · ${degrees(leg.feels, unitSystem)}°`,
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
  if (id === 'current-location') return ['Your location', 'live GPS position'];
  return null;
}

function pickedLabel(info: PickingInfo): string {
  if (info.layer?.id === 'amenities') {
    const amenity = info.object as Amenity;
    return amenity.name || AMENITY_LABEL[amenity.kind] || 'Selected place';
  }
  return 'Dropped pin';
}
