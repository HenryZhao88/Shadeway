import { useEffect } from 'react';

import MapCanvas from './map/MapCanvas';
import { useStore } from './state/store';
import './theme.css';
import DepartureCurve from './ui/DepartureCurve';
import Endpoints from './ui/Endpoints';
import HeatProfile from './ui/HeatProfile';
import Hero from './ui/Hero';
import MapTools from './ui/MapTools';
import RouteCompare from './ui/RouteCompare';
import ThermalStrip from './ui/ThermalStrip';
import TimeScrubber from './ui/TimeScrubber';
import TurnList from './ui/TurnList';
import Weather from './ui/Weather';
import { clock } from './sun/position';

const DAY = new Intl.DateTimeFormat(undefined, {
  weekday: 'short',
  day: 'numeric',
  month: 'short',
});

export default function App() {
  const scrubAt = useStore((s) => s.scrubAt);
  const routeError = useStore((s) => s.routeError);
  const health = useStore((s) => s.health);
  const fetchRoute = useStore((s) => s.fetchRoute);
  const fetchHealth = useStore((s) => s.fetchHealth);

  useEffect(() => {
    void fetchHealth();
    void fetchRoute();
  }, [fetchHealth, fetchRoute]);

  return (
    <div className="app">
      <header className="topbar">
        <p className="wordmark">
          shade<span>way</span>
        </p>
        <p className="eyebrow">what the walk feels like</p>
        <div className="topbar-meta eyebrow">
          <span>{DAY.format(scrubAt)}</span>
          <span className="num">{clock(scrubAt)}</span>
          <span>{health ? 'manhattan' : 'offline'}</span>
        </div>
      </header>

      <aside className="rail" aria-label="Route details">
        {routeError ? (
          <p className="banner" role="alert">
            {routeError}
          </p>
        ) : null}
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
        <Endpoints />
        <HeatProfile />
        <TurnList />
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
        <MapCanvas />
        <MapTools />
      </main>

      <div className="scrubber">
        <TimeScrubber />
      </div>
    </div>
  );
}
