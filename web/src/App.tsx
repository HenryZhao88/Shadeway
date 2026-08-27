import { lazy, Suspense, useEffect } from 'react';

import { useStore } from './state/store';
import './theme.css';
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
import Weather from './ui/Weather';
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

  useEffect(() => {
    void fetchHealth();
  }, [fetchHealth]);

  return (
    <div className={`app ${route ? 'has-route' : 'planning'}`}>
      <header className="topbar">
        <p className="wordmark">
          shade<span>way</span>
        </p>
        <p className="eyebrow">what the walk feels like</p>
        <div className="topbar-meta eyebrow">
          <span>{DAY.format(scrubAt)}</span>
          <span className="num">{clock(scrubAt)}</span>
          <span className={health ? 'scene-status' : 'scene-status offline'}>
            {health ? 'NYC scene' : 'offline'}
          </span>
        </div>
      </header>

      <aside className="rail" aria-label="Route details">
        {health && !health.cache_warm ? (
          <p className="banner calm">
            The horizon cache is {Math.round(health.warm_fraction * 100)}% warm.
            The first route through a block will be slow. Run{' '}
            <span className="num">make warm</span> before a demo.
          </p>
        ) : null}
        <Hero />
        <ThermalStrip />
        <RouteCompare />
        <HeatProfile />
        <TurnList />
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
      </aside>

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
        <Endpoints />
        <MapTools />
      </main>

      <div className="scrubber">
        <TimeScrubber />
      </div>
    </div>
  );
}
