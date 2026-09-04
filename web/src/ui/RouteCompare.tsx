/** Fastest against shadeway, with the trade stated in one sentence.
 *
 * The options come from the pareto frontier the router already returned, so
 * picking between them is a display change and costs nothing.
 */

import { degrees, deltaDegrees, heatCss, signedDegrees } from '../heat';
import { chosenRouteId, useStore } from '../state/store';
import { clock, minutes } from '../sun/position';
import type { Route } from '../api/types';
import {
  temperatureDeltaValue,
  temperatureUnit,
  type UnitSystem,
} from '../units';

export default function RouteCompare() {
  const route = useStore((s) => s.route);
  const chosenId = useStore(chosenRouteId);
  const selectRoute = useStore((s) => s.selectRoute);
  const unitSystem = useStore((s) => s.unitSystem);

  if (!route) return null;
  const options = Object.values(route.routes).sort(
    (a, b) => a.duration_s - b.duration_s,
  );
  if (options.length < 1) return null;

  const fastest = options[0]!;
  const chosen = (chosenId && route.routes[chosenId]) || fastest;

  return (
    <section className="block">
      <div className="block-head">
        <p className="eyebrow">your options</p>
        <span className="hint num">{route.compute_ms.toFixed(0)} ms</span>
      </div>

      <div className="compare" role="group" aria-label="Route options">
        {options.map((option) => (
          <Option
            key={option.route_id}
            option={option}
            fastest={fastest}
            selected={option.route_id === chosen.route_id}
            unitSystem={unitSystem}
            onSelect={() => selectRoute(option.route_id)}
          />
        ))}
      </div>

      <Verdict chosen={chosen} fastest={fastest} unitSystem={unitSystem} />
      <details className="route-details">
        <summary>More details</summary>
        <Exposure route={chosen} unitSystem={unitSystem} />
      </details>

      {options.length === 1 ? (
        <p className="hint" style={{ marginTop: 10 }}>
          Only one route came back on the frontier — on this pair there is no
          cooler way that is worth the extra walking.
        </p>
      ) : null}
    </section>
  );
}

function Option({
  option,
  fastest,
  selected,
  unitSystem,
  onSelect,
}: {
  option: Route;
  fastest: Route;
  selected: boolean;
  unitSystem: UnitSystem;
  onSelect: () => void;
}) {
  const deltaC = option.feels_like_c.mean_c - fastest.feels_like_c.mean_c;
  const deltaMin = (option.duration_s - fastest.duration_s) / 60;
  const isFastest = option.route_id === fastest.route_id;
  // "+0 min, the same" reads like a bug rather than a fact. If neither number
  // moves once rounded, this option simply has nothing to say about the other.
  const roundedDeltaMin = Math.round(deltaMin);
  const differs =
    roundedDeltaMin !== 0 ||
    Math.round(Math.abs(temperatureDeltaValue(deltaC, unitSystem))) > 0;

  return (
    <button
      type="button"
      className="option"
      aria-pressed={selected}
      onClick={onSelect}
      style={{ borderLeftColor: heatCss(option.feels_like_c.mean_c) }}
    >
      <span
        className="option-mark"
        style={{ background: heatCss(option.feels_like_c.mean_c) }}
        aria-hidden="true"
      />
      <span>
        <span className="option-name">{option.label}</span>
        <span className="option-sub num" style={{ display: 'block' }}>
          {minutes(option.duration_s)} min · arrive {clock(option.arrive_iso)}
          {isFastest || !differs
            ? ''
            : ` · ${roundedDeltaMin < 0 ? '−' : '+'}${Math.abs(roundedDeltaMin)} min, ${signedDegrees(deltaC, unitSystem)}`}
        </span>
      </span>
      <span
        className="option-temp"
        style={{ color: heatCss(option.feels_like_c.mean_c) }}
      >
        {degrees(option.feels_like_c.mean_c, unitSystem)}°
      </span>
    </button>
  );
}

/** What the recommendation is made of.
 *
 *  All of these come back on every route and none of them were on screen. The
 *  canopy share is the one that earns its place: "shaded, but by honey locusts"
 *  is the claim no other shade router can make, and the interface only ever
 *  made it one turn at a time. */
function Exposure({ route, unitSystem }: { route: Route; unitSystem: UnitSystem }) {
  const { sun_fraction, mean_svf, canopy_fraction } = route.exposure;
  return (
    <dl className="exposure">
      {/* Four, not five: distance is already under both thermal strips, and a
          fifth stat wrapped the row for a number the reader has just read. */}
      <Stat
        label="in sun"
        value={`${Math.round(sun_fraction * 100)}%`}
        hint="share of the walk with the direct beam on you"
      />
      <Stat
        label="canopy"
        value={`${Math.round(canopy_fraction * 100)}%`}
        hint="dappled, not opaque — leaves let some of the beam through"
      />
      <Stat
        label="sky view"
        value={`${Math.round(mean_svf * 100)}%`}
        hint="how much sky the street sees; low means deep canyon"
      />
      <Stat
        label="p90 block"
        value={`${degrees(route.feels_like_c.p90_c, unitSystem)}${temperatureUnit(unitSystem)}`}
        hint="the 90th-percentile block, not the single worst one"
      />
    </dl>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="exposure-stat" title={hint}>
      <dt className="eyebrow">{label}</dt>
      <dd className="num">{value}</dd>
    </div>
  );
}

function Verdict({
  chosen,
  fastest,
  unitSystem,
}: {
  chosen: Route;
  fastest: Route;
  unitSystem: UnitSystem;
}) {
  if (chosen.route_id === fastest.route_id) {
    return (
      <p className="verdict">
        The quickest way is also the coolest one here. Nothing to trade.
      </p>
    );
  }
  const cooler = fastest.feels_like_c.mean_c - chosen.feels_like_c.mean_c;
  const extra = Math.round((chosen.duration_s - fastest.duration_s) / 60);
  if (cooler < 0.5) {
    return (
      <p className="verdict">
        {chosen.label} costs <b>{extra} min</b> and feels about the same. Take the
        fast one.
      </p>
    );
  }
  return (
    <p className="verdict">
      {extra <= 0 ? (
        <>
          {chosen.label} is <b>{deltaDegrees(cooler, unitSystem)}°</b> cooler for no extra
          walking.
        </>
      ) : (
        <>
          <b>{extra}</b> extra {extra === 1 ? 'minute' : 'minutes'} buys you{' '}
          <b>{deltaDegrees(cooler, unitSystem)}°</b>.
        </>
      )}
    </p>
  );
}
