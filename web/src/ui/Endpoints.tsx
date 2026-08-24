/** Where you are walking from and to.
 *
 * No geocoder: this project has no API keys anywhere, and a keyless geocoder
 * would be one more thing to fail on stage. You click the map instead, which is
 * also the fastest way to put a route on a specific block — which is what the
 * demo actually needs.
 */

import { DEFAULT_DESTINATION, DEFAULT_ORIGIN, useStore } from '../state/store';

const PRESETS: { label: string; from: typeof DEFAULT_ORIGIN; to: typeof DEFAULT_ORIGIN }[] = [
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
  {
    label: 'Union Sq → Washington Sq',
    from: { lat: 40.7359, lon: -73.9911, label: 'Union Square' },
    to: { lat: 40.7308, lon: -73.9973, label: 'Washington Square' },
  },
];

export default function Endpoints() {
  const origin = useStore((s) => s.origin);
  const destination = useStore((s) => s.destination);
  const pickMode = useStore((s) => s.pickMode);
  const setPickMode = useStore((s) => s.setPickMode);
  const setPlace = useStore((s) => s.setPlace);
  const swapEnds = useStore((s) => s.swapEnds);

  return (
    <section className="block">
      <div className="block-head">
        <p className="eyebrow">the route</p>
        <button type="button" className="table-toggle" onClick={swapEnds}>
          Reverse it
        </button>
      </div>

      <button
        type="button"
        className="field"
        style={{ width: '100%' }}
        aria-pressed={pickMode === 'origin'}
        onClick={() => setPickMode(pickMode === 'origin' ? 'none' : 'origin')}
      >
        <span className="field-dot" style={{ background: 'var(--sun)' }} />
        <span className="field-label">{origin.label}</span>
        <span className="field-coord num">
          {pickMode === 'origin' ? 'click the map' : 'start'}
        </span>
      </button>

      <button
        type="button"
        className="field"
        style={{ width: '100%' }}
        aria-pressed={pickMode === 'destination'}
        onClick={() =>
          setPickMode(pickMode === 'destination' ? 'none' : 'destination')
        }
      >
        <span className="field-dot" style={{ background: 'var(--ink)' }} />
        <span className="field-label">{destination.label}</span>
        <span className="field-coord num">
          {pickMode === 'destination' ? 'click the map' : 'finish'}
        </span>
      </button>

      <div className="chip-row" style={{ marginTop: 10, flexWrap: 'wrap' }}>
        {PRESETS.map((preset) => (
          <button
            type="button"
            key={preset.label}
            className="chip"
            style={{ flex: '1 1 100%' }}
            onClick={() => {
              setPlace('origin', preset.from);
              setPlace('destination', preset.to);
            }}
          >
            {preset.label}
          </button>
        ))}
      </div>
    </section>
  );
}
