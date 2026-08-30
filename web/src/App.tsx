import { lazy, Suspense, useEffect, useRef, useState } from 'react';

import { useStore } from './state/store';
import './theme.css';
import BottomSheet, { type Detent } from './ui/BottomSheet';
import DepartureCurve from './ui/DepartureCurve';
import Endpoints from './ui/Endpoints';
import HeatProfile from './ui/HeatProfile';
import Hero from './ui/Hero';
import MapTools from './ui/MapTools';
import RouteCompare from './ui/RouteCompare';
import RouteTimeseries from './ui/RouteTimeseries';
import ThermalStrip from './ui/ThermalStrip';
import TimeScrubber from './ui/TimeScrubber';
import TurnList from './ui/TurnList';
import UnitToggle from './ui/UnitToggle';
import Weather from './ui/Weather';
import { useCompactLayout } from './ui/useCompactLayout';
import { clock } from './sun/position';

// MapLibre + deck.gl account for nearly the entire JavaScript payload. Let the
// route rail become interactive while that independent rendering stack loads.
const MapCanvas = lazy(() => import('./map/MapCanvas'));

const DAY = new Intl.DateTimeFormat(undefined, {
  weekday: 'short',
  day: 'numeric',
  month: 'short',
});

export default function App() {
  const scrubAt = useStore((s) => s.scrubAt);
  const route = useStore((s) => s.route);
  const health = useStore((s) => s.health);
  const fetchHealth = useStore((s) => s.fetchHealth);
  const routeGeneration = useStore((s) => s.routeGeneration);
  const pickMode = useStore((s) => s.pickMode);

  // On a phone there is no room for a map and a column of evidence at once, so
  // the evidence rides over the map in a sheet the reader can pull up and push
  // down. On anything wider the two sit side by side and the sheet is not
  // built at all.
  const compact = useCompactLayout();
  const [detent, setDetent] = useState<Detent>('half');

  useEffect(() => {
    void fetchHealth();
  }, [fetchHealth]);

  // The sheet answers the two moments where the reader's attention obviously
  // moved: a route just landed (show it), and they are about to touch the map
  // to place a point (get out of the way).
  const lastGeneration = useRef(routeGeneration);
  useEffect(() => {
    if (routeGeneration === lastGeneration.current) return;
    lastGeneration.current = routeGeneration;
    setDetent('half');
  }, [routeGeneration]);

  useEffect(() => {
    if (pickMode !== 'none') setDetent('peek');
  }, [pickMode]);

  const details = (
    <>
      {health && !health.cache_warm ? (
        <p className="banner calm">
          The horizon cache is {Math.round(health.warm_fraction * 100)}% warm.
          The first route through a block will be slow. Run{' '}
          <span className="num">make warm</span> before a demo.
        </p>
      ) : null}
      <Hero />
      <RouteCompare />
      <TurnList />
      <ThermalStrip />
      <HeatProfile />
      <RouteTimeseries />
      <DepartureCurve />
      <Weather />
      <footer className="block" style={{ borderBottom: 'none' }}>
        <p className="hint">
          Felt temperature is UTCI computed from mean radiant temperature, with
          shade cast by real building heights and modelled tree crowns. The
          physics, with citations, is in <span className="num">docs/model.md</span>.
        </p>
      </footer>
    </>
  );

  return (
    <div
      className={`app ${route ? 'has-route' : 'planning'} ${
        compact ? 'is-compact' : 'is-wide'
      }`}
    >
      <header className="topbar">
        <p className="wordmark">
          shade<span>way</span>
        </p>
        <p className="eyebrow topbar-tagline">what the walk feels like</p>
        <div className="topbar-meta eyebrow">
          <UnitToggle />
          <span className="topbar-date">{DAY.format(scrubAt)}</span>
          <span className="num">{clock(scrubAt)}</span>
          <span className={health ? 'scene-status' : 'scene-status offline'}>
            {health ? 'NYC scene' : 'offline'}
          </span>
        </div>
      </header>

      {compact ? null : (
        <aside className="rail" aria-label="Route details">
          {details}
        </aside>
      )}

      <main className="map-area">
        <Suspense
          fallback={
            <div className="map-loading" role="status">
              <span className="spinner" aria-hidden="true" /> Loading the map…
            </div>
          }
        >
          <MapCanvas />
        </Suspense>
        {compact ? null : <Endpoints />}
        <MapTools />
        {compact ? (
          <BottomSheet
            detent={detent}
            onDetentChange={setDetent}
            label="Route planner and details"
          >
            <Endpoints />
            {details}
          </BottomSheet>
        ) : null}
      </main>

      <div className="scrubber">
        <TimeScrubber />
      </div>
    </div>
  );
}
