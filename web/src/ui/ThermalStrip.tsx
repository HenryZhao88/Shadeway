/** The walk, unrolled.
 *
 * One horizontal band per route: x is distance travelled, colour is felt
 * temperature. Stacked, the two strips are the entire route comparison in a
 * glance — you can see that the fast way has three blocks of exposed avenue in
 * it and the cool way does not, without reading a number.
 *
 * This is the interface's signature element, so it carries the discipline that
 * goes with the heat ramp: a labelled degree axis underneath, the UTCI category
 * names in the legend, and a per-block tooltip. Colour is never asked to carry
 * the meaning by itself.
 */

import { useState } from 'react';

import { HEAT_CATEGORIES, degrees, heatCategory, heatCss } from '../heat';
import { chosenRouteId, useStore } from '../state/store';
import type { Route } from '../api/types';
import { minutes } from '../sun/position';

export default function ThermalStrip() {
  const route = useStore((s) => s.route);
  const generation = useStore((s) => s.routeGeneration);
  const chosenId = useStore(chosenRouteId);
  const hoverLeg = useStore((s) => s.hoverLeg);
  const selectRoute = useStore((s) => s.selectRoute);

  if (!route) return null;
  const ordered = orderRoutes(route.routes, chosenId);
  if (!ordered.length) return null;

  return (
    <section className="block">
      <div className="block-head">
        <p className="eyebrow">the walk, unrolled</p>
        <span className="hint">distance →</span>
      </div>

      {ordered.map((entry) => (
        <Strip
          key={entry.route_id}
          route={entry}
          isChosen={entry.route_id === chosenId}
          generation={generation}
          onHoverLeg={(index) =>
            hoverLeg(entry.route_id === chosenId ? index : null)
          }
          onSelect={() => selectRoute(entry.route_id)}
        />
      ))}

      <ul className="legend" aria-label="UTCI heat stress categories">
        {HEAT_CATEGORIES.filter((c) => c.label !== 'extreme').map((category) => (
          <li className="legend-item" key={category.label}>
            <span
              className="legend-swatch"
              style={{ background: category.hex }}
              aria-hidden="true"
            />
            {category.label}
            {Number.isFinite(category.from) ? (
              <span className="num"> {category.from}°+</span>
            ) : null}
          </li>
        ))}
      </ul>
      <p className="hint" style={{ marginTop: 8 }}>
        Bands are UTCI assessment categories. Every block's own number is in its
        tooltip and in the turn list below.
      </p>
    </section>
  );
}

interface StripProps {
  route: Route;
  isChosen: boolean;
  generation: number;
  onHoverLeg: (index: number | null) => void;
  onSelect: () => void;
}

function Strip({ route, isChosen, generation, onHoverLeg, onSelect }: StripProps) {
  const [hover, setHover] = useState<{ index: number; left: number } | null>(null);
  const total = route.legs.reduce((sum, leg) => sum + leg.length_m, 0) || 1;

  // Crossings are where the side-of-street call happens, so they get a tick:
  // the strip should show you that the cool stretch is on the other side.
  let cursor = 0;
  const ticks: number[] = [];
  for (const leg of route.legs) {
    cursor += leg.length_m;
    if (leg.kind === 1) ticks.push((cursor / total) * 100);
  }

  const hovered = hover ? route.legs[hover.index] : undefined;

  return (
    <div className="strip-row">
      <div className="strip-label">
        <span className="strip-name">
          {isChosen ? `${route.label} · recommended` : route.label}
        </span>
        <span className="strip-stats">
          {degrees(route.feels_like_c.mean_c)}° avg ·{' '}
          {degrees(route.feels_like_c.max_c)}° max · {minutes(route.duration_s)} min
        </span>
      </div>

      <div
        className={`strip${isChosen ? ' animate' : ''}`}
        key={`${route.route_id}-${generation}`}
        style={{ opacity: isChosen ? 1 : 0.55 }}
        onMouseLeave={() => {
          setHover(null);
          onHoverLeg(null);
        }}
        role="img"
        aria-label={`${route.label}: felt temperature along the route, averaging ${degrees(
          route.feels_like_c.mean_c,
        )} degrees, peaking at ${degrees(route.feels_like_c.max_c)}`}
      >
        {route.legs.map((leg, index) => (
          <div
            key={`${leg.edge_id}-${index}`}
            className="strip-seg"
            style={{
              width: `${(leg.length_m / total) * 100}%`,
              background: heatCss(leg.feels_like_c),
              animationDelay: `${(index / route.legs.length) * 260}ms`,
            }}
            onMouseEnter={(event) => {
              setHover({
                index,
                left: event.currentTarget.offsetLeft,
              });
              onHoverLeg(index);
            }}
          />
        ))}
        {ticks.map((left, i) => (
          <span
            key={`${left}-${i}`}
            className="strip-tick"
            style={{ left: `${left}%` }}
            aria-hidden="true"
          />
        ))}
      </div>

      <div className="strip-axis eyebrow">
        <span>start</span>
        <span>
          {(total / 1000).toFixed(2)} km · ticks are crossings
        </span>
        <span>finish</span>
      </div>

      {hovered ? (
        <div className="tooltip" style={{ left: hover?.left ?? 0, bottom: 44 }}>
          <b>{hovered.street_name.replace(/\s+/g, ' ').trim()}</b> ·{' '}
          <span className="num">{degrees(hovered.feels_like_c)}°</span> ·{' '}
          {heatCategory(hovered.feels_like_c)}
        </div>
      ) : null}

      {!isChosen ? (
        <button type="button" className="table-toggle" onClick={onSelect}>
          Show {route.label} instead
        </button>
      ) : null}
    </div>
  );
}

/** Recommended first, then the rest by duration. The reader should meet the
 *  answer before the alternatives. */
function orderRoutes(
  routes: Record<string, Route>,
  chosenId: string | null,
): Route[] {
  const all = Object.values(routes);
  return all.sort((a, b) => {
    if (a.route_id === chosenId) return -1;
    if (b.route_id === chosenId) return 1;
    return a.duration_s - b.duration_s;
  });
}
