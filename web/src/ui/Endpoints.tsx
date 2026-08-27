/** The route planner that sits on the map.
 *
 * The happy path is deliberately only two decisions: use the browser's live
 * location, then click a destination. Selecting the second point starts the
 * route automatically. A map-picked origin and sample trip remain available
 * when location permission is unavailable or the demo is not physically in
 * New York.
 */

import { useEffect, useRef } from 'react';

import { DEFAULT_DESTINATION, DEFAULT_ORIGIN, useStore } from '../state/store';

const PRESETS: {
  label: string;
  from: typeof DEFAULT_ORIGIN;
  to: typeof DEFAULT_ORIGIN;
}[] = [
  {
    label: 'Times Sq → Grand Central',
    from: DEFAULT_ORIGIN,
    to: DEFAULT_DESTINATION,
  },
  {
    label: 'Bryant Park → Herald Sq',
    from: { lat: 40.7536, lon: -73.984, label: 'Bryant Park' },
    to: { lat: 40.7497, lon: -73.9881, label: 'Herald Square' },
  },
];

export default function Endpoints() {
  const watchId = useRef<number | null>(null);
  const origin = useStore((s) => s.origin);
  const destination = useStore((s) => s.destination);
  const originMode = useStore((s) => s.originMode);
  const currentLocation = useStore((s) => s.currentLocation);
  const locationStatus = useStore((s) => s.locationStatus);
  const locationError = useStore((s) => s.locationError);
  const pickMode = useStore((s) => s.pickMode);
  const routeStatus = useStore((s) => s.routeStatus);
  const routeError = useStore((s) => s.routeError);
  const setPickMode = useStore((s) => s.setPickMode);
  const setTrip = useStore((s) => s.setTrip);
  const selectCurrentLocation = useStore((s) => s.selectCurrentLocation);
  const updateCurrentLocation = useStore((s) => s.updateCurrentLocation);
  const setLocationStatus = useStore((s) => s.setLocationStatus);
  const focusCurrentLocation = useStore((s) => s.focusCurrentLocation);
  const fetchRoute = useStore((s) => s.fetchRoute);
  const swapEnds = useStore((s) => s.swapEnds);

  useEffect(
    () => () => {
      if (watchId.current !== null && navigator.geolocation) {
        navigator.geolocation.clearWatch(watchId.current);
      }
    },
    [],
  );

  const trackLocation = () => {
    selectCurrentLocation();
    if (currentLocation) focusCurrentLocation();
    if (watchId.current !== null) return;
    if (!navigator.geolocation) {
      setLocationStatus(
        'unavailable',
        'Location is unavailable here so choose your start on the map',
      );
      setPickMode('origin');
      return;
    }

    setLocationStatus('requesting');
    watchId.current = navigator.geolocation.watchPosition(
      (position) => {
        updateCurrentLocation({
          lat: position.coords.latitude,
          lon: position.coords.longitude,
          accuracyM: position.coords.accuracy,
          label: 'Your location',
        });
      },
      (error) => {
        watchId.current = null;
        const denied = error.code === error.PERMISSION_DENIED;
        setLocationStatus(
          denied ? 'denied' : 'unavailable',
          denied
            ? 'Location is blocked so choose your start on the map'
            : 'We could not find your location so choose your start on the map',
        );
        setPickMode('origin');
      },
      { enableHighAccuracy: true, maximumAge: 10_000, timeout: 12_000 },
    );
  };

  const prompt = routePrompt({
    origin: Boolean(origin),
    destination: Boolean(destination),
    routeStatus,
  });

  return (
    <section className="route-planner" aria-label="Plan a walking route">
      <div className="planner-head">
        <div>
          <p className="eyebrow">plan a cooler walk</p>
          <h1>Where are you going?</h1>
        </div>
        {origin && destination ? (
          <button type="button" className="planner-swap" onClick={swapEnds}>
            Swap
          </button>
        ) : null}
      </div>

      <button
        type="button"
        className="location-button"
        aria-pressed={originMode === 'current'}
        onClick={trackLocation}
      >
        <span className="location-target" aria-hidden="true" />
        <span>
          <b>
            {locationStatus === 'requesting'
              ? 'Finding your location…'
              : locationStatus === 'tracking'
                ? 'Using your live location'
                : 'Use my current location'}
          </b>
          <small>
            {locationStatus === 'tracking' && currentLocation
              ? `accurate to about ${Math.round(currentLocation.accuracyM)} m`
              : 'your browser will ask for permission'}
          </small>
        </span>
        {locationStatus === 'requesting' ? (
          <span className="spinner" aria-hidden="true" />
        ) : null}
      </button>

      <div className="planner-fields">
        <button
          type="button"
          className="field"
          aria-pressed={pickMode === 'origin'}
          onClick={() => setPickMode(pickMode === 'origin' ? 'none' : 'origin')}
        >
          <span
            className={`field-dot ${originMode === 'current' ? 'is-location' : ''}`}
          />
          <span className={`field-label ${origin ? '' : 'placeholder'}`}>
            {origin?.label ?? 'Choose a starting point'}
          </span>
          <span className="field-coord num">
            {pickMode === 'origin' ? 'click map' : 'start'}
          </span>
        </button>

        <button
          type="button"
          className="field"
          aria-pressed={pickMode === 'destination'}
          onClick={() =>
            setPickMode(pickMode === 'destination' ? 'none' : 'destination')
          }
        >
          <span className="field-dot is-destination" />
          <span className={`field-label ${destination ? '' : 'placeholder'}`}>
            {destination?.label ?? 'Choose destination on the map'}
          </span>
          <span className="field-coord num">
            {pickMode === 'destination' ? 'click map' : 'finish'}
          </span>
        </button>
      </div>

      <div className="planner-action-row">
        <p className="planner-prompt" aria-live="polite">
          {prompt}
        </p>
        <button
          type="button"
          className="route-button"
          disabled={!origin || !destination || routeStatus === 'loading'}
          onClick={() => void fetchRoute()}
        >
          {routeStatus === 'loading' ? 'Calculating…' : 'Get route'}
        </button>
      </div>

      {locationError ? (
        <p className="planner-error" role="status">
          {locationError}
        </p>
      ) : null}
      {routeError ? (
        <p className="planner-error" role="alert">
          {routeError}
        </p>
      ) : null}

      <details className="sample-trips">
        <summary>or try a sample NYC trip</summary>
        <div className="chip-row">
          {PRESETS.map((preset) => (
            <button
              type="button"
              key={preset.label}
              className="chip"
              onClick={() => setTrip(preset.from, preset.to)}
            >
              {preset.label}
            </button>
          ))}
        </div>
      </details>
    </section>
  );
}

function routePrompt({
  origin,
  destination,
  routeStatus,
}: {
  origin: boolean;
  destination: boolean;
  routeStatus: 'idle' | 'loading' | 'ready' | 'error';
}) {
  if (routeStatus === 'loading') return 'Comparing the fastest and coolest walks';
  if (routeStatus === 'ready') return 'Route ready';
  if (!origin) return 'Start with your location or a point on the map';
  if (!destination) return 'Now click your destination on the map';
  return 'Ready to calculate';
}
