/** Fastest against shadeway, with the trade stated in one sentence.
 *
 * The options come from the pareto frontier the router already returned, so
 * picking between them is a display change and costs nothing.
 */

import { degrees, heatCss, signedDegrees } from '../heat';
import { chosenRouteId, useStore } from '../state/store';
import { clock, minutes } from '../sun/position';
import type { Route } from '../api/types';

export default function RouteCompare() {
  const route = useStore((s) => s.route);
  const chosenId = useStore(chosenRouteId);
  const selectRoute = useStore((s) => s.selectRoute);

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
            onSelect={() => selectRoute(option.route_id)}
          />
        ))}
      </div>

      <Verdict chosen={chosen} fastest={fastest} />

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
  onSelect,
}: {
  option: Route;
  fastest: Route;
  selected: boolean;
  onSelect: () => void;
}) {
  const deltaC = option.feels_like_c.mean_c - fastest.feels_like_c.mean_c;
  const deltaMin = (option.duration_s - fastest.duration_s) / 60;
  const isFastest = option.route_id === fastest.route_id;
  // "+0 min, the same" reads like a bug rather than a fact. If neither number
  // moves once rounded, this option simply has nothing to say about the other.
  const differs = Math.round(Math.abs(deltaMin)) > 0 || Math.round(Math.abs(deltaC)) > 0;

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
            : ` · ${deltaMin >= 0 ? '+' : '−'}${Math.abs(Math.round(deltaMin))} min, ${signedDegrees(deltaC)}`}
        </span>
      </span>
      <span
        className="option-temp"
        style={{ color: heatCss(option.feels_like_c.mean_c) }}
      >
        {degrees(option.feels_like_c.mean_c)}°
      </span>
    </button>
  );
}

function Verdict({ chosen, fastest }: { chosen: Route; fastest: Route }) {
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
          {chosen.label} is <b>{Math.round(cooler)}°</b> cooler for no extra
          walking.
        </>
      ) : (
        <>
          <b>{extra}</b> extra {extra === 1 ? 'minute' : 'minutes'} buys you{' '}
          <b>{Math.round(cooler)}°</b>.
        </>
      )}
    </p>
  );
}
