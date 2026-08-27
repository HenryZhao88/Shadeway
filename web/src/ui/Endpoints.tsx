/** Navigation-style route planning with address search, map picking and GPS. */

import { useEffect, useRef, useState, type FormEvent } from 'react';

import { searchPlaces, type GeocodeResult } from '../api/client';
import { DEFAULT_DESTINATION, DEFAULT_ORIGIN, useStore } from '../state/store';
import { formatAccuracy } from '../units';

type EndpointKind = 'origin' | 'destination';
type SearchStatus = 'idle' | 'loading' | 'ready' | 'error';

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
  const searchAbort = useRef<AbortController | null>(null);
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
  const setPlace = useStore((s) => s.setPlace);
  const clearPlace = useStore((s) => s.clearPlace);
  const setTrip = useStore((s) => s.setTrip);
  const selectCurrentLocation = useStore((s) => s.selectCurrentLocation);
  const updateCurrentLocation = useStore((s) => s.updateCurrentLocation);
  const setLocationStatus = useStore((s) => s.setLocationStatus);
  const focusCurrentLocation = useStore((s) => s.focusCurrentLocation);
  const fetchRoute = useStore((s) => s.fetchRoute);
  const swapEnds = useStore((s) => s.swapEnds);
  const unitSystem = useStore((s) => s.unitSystem);
  const [draft, setDraft] = useState({ origin: '', destination: '' });
  const [activeSearch, setActiveSearch] = useState<EndpointKind | null>(null);
  const [searchStatus, setSearchStatus] = useState<SearchStatus>('idle');
  const [results, setResults] = useState<GeocodeResult[]>([]);
  const [searchMessage, setSearchMessage] = useState<string | null>(null);
  const [attribution, setAttribution] = useState('');

  useEffect(() => {
    setDraft((current) => ({ ...current, origin: origin?.label ?? '' }));
  }, [origin]);

  useEffect(() => {
    setDraft((current) => ({
      ...current,
      destination: destination?.label ?? '',
    }));
  }, [destination]);

  useEffect(
    () => () => {
      searchAbort.current?.abort();
      if (watchId.current !== null && navigator.geolocation) {
        navigator.geolocation.clearWatch(watchId.current);
      }
    },
    [],
  );

  const trackLocation = () => {
    selectCurrentLocation();
    setActiveSearch(null);
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

  const changeDraft = (which: EndpointKind, value: string) => {
    setDraft((current) => ({ ...current, [which]: value }));
    const selected = which === 'origin' ? origin : destination;
    if (selected && value !== selected.label) clearPlace(which);
    if (activeSearch === which) {
      setActiveSearch(null);
      setResults([]);
      setSearchMessage(null);
      setSearchStatus('idle');
    }
  };

  const submitSearch = async (which: EndpointKind, event?: FormEvent) => {
    event?.preventDefault();
    const query = draft[which].trim();
    setActiveSearch(which);
    setResults([]);
    setSearchMessage(null);
    if (query.length < 2) {
      setSearchStatus('error');
      setSearchMessage('Enter at least two characters to search.');
      return;
    }
    searchAbort.current?.abort();
    const controller = new AbortController();
    searchAbort.current = controller;
    setSearchStatus('loading');
    try {
      const response = await searchPlaces(query, controller.signal);
      if (controller.signal.aborted) return;
      setResults(response.results);
      setAttribution(response.attribution);
      setSearchStatus('ready');
      if (!response.results.length) {
        setSearchMessage('No NYC places found. Try a street address or landmark.');
      }
    } catch (error) {
      if ((error as Error)?.name === 'AbortError') return;
      setSearchStatus('error');
      setSearchMessage(
        error instanceof Error ? error.message : 'Place search failed. Try again.',
      );
    }
  };

  const chooseResult = (which: EndpointKind, result: GeocodeResult) => {
    setDraft((current) => ({ ...current, [which]: result.label }));
    setPlace(which, { label: result.label, lat: result.lat, lon: result.lon });
    setActiveSearch(null);
    setResults([]);
    setSearchStatus('idle');
    setSearchMessage(null);
  };

  const chooseOnMap = (which: EndpointKind) => {
    setActiveSearch(null);
    setPickMode(pickMode === which ? 'none' : which);
  };

  const swap = () => {
    setActiveSearch(null);
    swapEnds();
  };

  const prompt = routePrompt({
    origin: Boolean(origin),
    destination: Boolean(destination),
    routeStatus,
    pickMode,
  });

  return (
    <section className="route-planner" aria-label="Plan a walking route">
      <div className="planner-head">
        <div>
          <p className="eyebrow">walking directions</p>
          <h1>Plan your route</h1>
        </div>
        {origin && destination ? (
          <button type="button" className="planner-swap" onClick={swap}>
            Swap
          </button>
        ) : null}
      </div>

      <div className="planner-fields">
        <AddressField
          which="origin"
          label="Starting point"
          value={draft.origin}
          placeholder="Enter starting address"
          selected={Boolean(origin)}
          current={originMode === 'current'}
          picking={pickMode === 'origin'}
          searching={activeSearch === 'origin' && searchStatus === 'loading'}
          onChange={(value) => changeDraft('origin', value)}
          onSubmit={(event) => void submitSearch('origin', event)}
          onPickMap={() => chooseOnMap('origin')}
        />
        <AddressField
          which="destination"
          label="Destination"
          value={draft.destination}
          placeholder="Enter destination address"
          selected={Boolean(destination)}
          picking={pickMode === 'destination'}
          searching={activeSearch === 'destination' && searchStatus === 'loading'}
          onChange={(value) => changeDraft('destination', value)}
          onSubmit={(event) => void submitSearch('destination', event)}
          onPickMap={() => chooseOnMap('destination')}
        />
      </div>

      {activeSearch ? (
        <SearchResults
          status={searchStatus}
          message={searchMessage}
          results={results}
          attribution={attribution}
          onChoose={(result) => chooseResult(activeSearch, result)}
        />
      ) : null}

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
              ? `accurate to about ${formatAccuracy(currentLocation.accuracyM, unitSystem)}`
              : 'set as starting point'}
          </small>
        </span>
        {locationStatus === 'requesting' ? (
          <span className="spinner" aria-hidden="true" />
        ) : null}
      </button>

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
          {routeStatus === 'loading' ? 'Calculating…' : 'Directions'}
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

function AddressField({
  which,
  label,
  value,
  placeholder,
  selected,
  current = false,
  picking,
  searching,
  onChange,
  onSubmit,
  onPickMap,
}: {
  which: EndpointKind;
  label: string;
  value: string;
  placeholder: string;
  selected: boolean;
  current?: boolean;
  picking: boolean;
  searching: boolean;
  onChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onPickMap: () => void;
}) {
  return (
    <form className="address-form" onSubmit={onSubmit}>
      <label htmlFor={`${which}-address`}>{label}</label>
      <div className={`address-field ${picking ? 'is-picking' : ''}`}>
        <span
          className={`field-dot ${current ? 'is-location' : ''} ${
            which === 'destination' ? 'is-destination' : ''
          }`}
          aria-hidden="true"
        />
        <input
          id={`${which}-address`}
          type="search"
          autoComplete="street-address"
          enterKeyHint="search"
          value={value}
          placeholder={placeholder}
          aria-describedby={`${which}-hint`}
          onChange={(event) => onChange(event.target.value)}
        />
        <button
          type="button"
          className="field-map-button"
          aria-pressed={picking}
          aria-label={`Choose ${label.toLowerCase()} on map`}
          onClick={onPickMap}
        >
          {picking ? 'Cancel' : 'Map'}
        </button>
        <button
          type="submit"
          className="field-search-button"
          disabled={searching || value.trim().length < 2}
          aria-label={`Search for ${label.toLowerCase()}`}
        >
          {searching ? <span className="spinner" aria-hidden="true" /> : 'Search'}
        </button>
      </div>
      <small id={`${which}-hint`} className="field-hint">
        {picking
          ? `Click the map to set your ${which === 'origin' ? 'start' : 'destination'}`
          : selected
            ? 'Selected'
            : 'Search an address or choose it on the map'}
      </small>
    </form>
  );
}

function SearchResults({
  status,
  message,
  results,
  attribution,
  onChoose,
}: {
  status: SearchStatus;
  message: string | null;
  results: GeocodeResult[];
  attribution: string;
  onChoose: (result: GeocodeResult) => void;
}) {
  return (
    <div className="search-results" aria-live="polite">
      {status === 'loading' ? (
        <p className="search-state">
          <span className="spinner" aria-hidden="true" /> Searching NYC…
        </p>
      ) : null}
      {message ? <p className="search-state">{message}</p> : null}
      {results.length ? (
        <ul aria-label="Place search results">
          {results.map((result) => {
            const [name, ...rest] = result.label.split(',');
            return (
              <li key={`${result.lat},${result.lon},${result.label}`}>
                <button type="button" onClick={() => onChoose(result)}>
                  <span className="result-pin" aria-hidden="true" />
                  <span>
                    <b>{name}</b>
                    <small>{rest.join(',').trim() || result.kind}</small>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
      {attribution && status === 'ready' ? (
        <p className="search-attribution">Search {attribution}</p>
      ) : null}
    </div>
  );
}

function routePrompt({
  origin,
  destination,
  routeStatus,
  pickMode,
}: {
  origin: boolean;
  destination: boolean;
  routeStatus: 'idle' | 'loading' | 'ready' | 'error';
  pickMode: string;
}) {
  if (routeStatus === 'loading') return 'Comparing the fastest and coolest walks';
  if (routeStatus === 'ready') return 'Route ready';
  if (pickMode === 'origin') return 'Click the map to choose your starting point';
  if (pickMode === 'destination') return 'Click the map to choose your destination';
  if (!origin) return 'Enter your starting point';
  if (!destination) return 'Enter where you want to go';
  return 'Ready for directions';
}
