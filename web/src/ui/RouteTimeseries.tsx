/** How THIS walk feels as the afternoon goes on.
 *
 * A different question from the departure curve, and the reason both exist:
 *
 *   DepartureCurve   "when should I leave?" — re-routes at each departure, so
 *                    every point is a different walk.
 *   RouteTimeseries  "what happens to the walk I am looking at?" — the same
 *                    sample points, the same turns, evaluated at N times. The
 *                    route never changes; only the sun does.
 *
 * That second one is nearly free on the server (the horizon cache makes it an
 * array lookup per time), which is why the contract returns the whole series in
 * one call — and it is the honest way to show that a route which is fine now
 * bakes at five.
 *
 * Two series on one axis, so it carries a legend: mean and worst-block felt
 * temperature. Both are degrees on the same scale, which is what makes them
 * legitimately shareable — a second axis would not be.
 */

import { useMemo, useState } from 'react';

import { degrees, heatCss } from '../heat';
import { chosenRouteId, useStore } from '../state/store';
import { clock } from '../sun/position';
import type { TimeseriesPoint } from '../api/types';

const WIDTH = 340;
const HEIGHT = 122;
const PAD = { top: 14, right: 14, bottom: 22, left: 34 };

export default function RouteTimeseries() {
  const series = useStore((s) => s.timeseries);
  const status = useStore((s) => s.timeseriesStatus);
  const retry = useStore((s) => s.fetchTimeseries);
  const chosenId = useStore(chosenRouteId);
  const departAt = useStore((s) => s.departAt);
  const setScrubAt = useStore((s) => s.setScrubAt);
  const [hover, setHover] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);

  const points = (chosenId && series[chosenId]?.points) || [];
  const geometry = useMemo(() => layout(points), [points]);

  if (!chosenId) return null;
  if (!geometry || points.length < 2) {
    return (
      <section className="block">
        <p className="eyebrow">this route, hour by hour</p>
        {status === 'error' || status === 'ready' ? (
          <>
            <p className="hint" role="alert" style={{ marginTop: 10 }}>
              The hour-by-hour curve is temporarily unavailable.
            </p>
            <button
              type="button"
              className="table-toggle"
              onClick={() => void retry()}
            >
              Try again
            </button>
          </>
        ) : (
          <p className="hint" style={{ marginTop: 10 }}>
            <span className="spinner" aria-hidden="true" /> Walking the route
            forward through the afternoon…
          </p>
        )}
      </section>
    );
  }

  const first = points[0]!;
  const worst = points.reduce((a, b) =>
    b.max_feels_like_c > a.max_feels_like_c ? b : a,
  );
  const active = hover != null ? points[hover] : undefined;
  const meanColor = heatCss(first.mean_feels_like_c);
  const maxColor = heatCss(worst.max_feels_like_c);

  return (
    <section className="block">
      <div className="block-head">
        <p className="eyebrow">this route, hour by hour</p>
        <span className="hint">same turns, moving sun</span>
      </div>

      <ul className="legend" style={{ marginTop: 0, marginBottom: 10 }}>
        <li className="legend-item">
          <span
            className="legend-swatch"
            style={{ background: meanColor }}
            aria-hidden="true"
          />
          average over the walk
        </li>
        <li className="legend-item">
          {/* dashed, not just paler: on a mild day the mean and the worst block
              land on adjacent stops of the heat ramp and the two swatches come
              out the same colour, so the difference has to be a shape */}
          <span
            className="legend-swatch legend-swatch-dashed"
            style={{ borderColor: maxColor }}
            aria-hidden="true"
          />
          worst block
        </li>
      </ul>

      <div className="chart">
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          role="img"
          aria-label={`Felt temperature along this route by time of day. Setting off at ${clock(
            first.at_iso,
          )} it averages ${degrees(first.mean_feels_like_c)} degrees; the worst block
            peaks at ${degrees(worst.max_feels_like_c)} degrees around ${clock(
              worst.at_iso,
            )}.`}
          onMouseLeave={() => setHover(null)}
          onMouseMove={(event) => {
            const box = event.currentTarget.getBoundingClientRect();
            const x = ((event.clientX - box.left) / box.width) * WIDTH;
            setHover(geometry.nearest(x));
          }}
        >
          {geometry.yTicks.map((tick) => (
            <g key={tick.value}>
              <line
                x1={PAD.left}
                x2={WIDTH - PAD.right}
                y1={tick.y}
                y2={tick.y}
                stroke="var(--rule)"
                strokeWidth="1"
              />
              <text
                x={PAD.left - 6}
                y={tick.y + 3}
                textAnchor="end"
                fill="var(--ink-3)"
                fontSize="9"
                fontFamily="var(--data)"
              >
                {tick.value}
              </text>
            </g>
          ))}

          {/* worst block first, so the average reads on top of it */}
          <path
            d={geometry.maxPath}
            fill="none"
            stroke={maxColor}
            strokeWidth="1.5"
            strokeDasharray="4 3"
            strokeOpacity="0.85"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d={geometry.meanPath}
            fill="none"
            stroke={meanColor}
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {active ? (
            <line
              x1={geometry.x(hover!)}
              x2={geometry.x(hover!)}
              y1={PAD.top}
              y2={HEIGHT - PAD.bottom}
              stroke="var(--rule-bright)"
              strokeWidth="1"
            />
          ) : null}

          <circle
            cx={geometry.x(0)}
            cy={geometry.y(first.mean_feels_like_c)}
            r="3.5"
            fill={meanColor}
            stroke="var(--panel)"
            strokeWidth="2"
          />
          <text
            x={geometry.x(0) + 6}
            y={geometry.y(first.mean_feels_like_c) - 8}
            fill="var(--ink-2)"
            fontSize="9.5"
            fontFamily="var(--data)"
          >
            you
          </text>

          <text
            x={PAD.left}
            y={HEIGHT - 6}
            fill="var(--ink-3)"
            fontSize="9"
            fontFamily="var(--data)"
          >
            {clock(first.at_iso)}
          </text>
          <text
            x={WIDTH - PAD.right}
            y={HEIGHT - 6}
            textAnchor="end"
            fill="var(--ink-3)"
            fontSize="9"
            fontFamily="var(--data)"
          >
            {clock(points[points.length - 1]!.at_iso)}
          </text>
        </svg>

        {active ? (
          <div
            className="tooltip"
            style={{
              left: `${(geometry.x(hover!) / WIDTH) * 100}%`,
              top: 0,
              transform: 'translate(-50%, -4px)',
            }}
          >
            <span className="num">{clock(active.at_iso)}</span> ·{' '}
            <span className="num">{degrees(active.mean_feels_like_c)}°</span> avg ·{' '}
            <span className="num">{degrees(active.max_feels_like_c)}°</span> worst ·{' '}
            <span className="num">{Math.round(active.sun_fraction * 100)}%</span> sun
          </div>
        ) : null}
      </div>

      <p className="chart-note">
        <Verdict points={points} />
      </p>

      <button
        type="button"
        className="table-toggle"
        onClick={() => setShowTable((open) => !open)}
        aria-expanded={showTable}
      >
        {showTable ? 'Hide the numbers' : 'Show the numbers'}
      </button>
      {showTable ? (
        <table className="data-table">
          <caption className="sr-only">
            Felt temperature and sun exposure along this route by time of day
          </caption>
          <thead>
            <tr>
              <th scope="col">at</th>
              <th scope="col">avg</th>
              <th scope="col">worst</th>
              <th scope="col">sun</th>
            </tr>
          </thead>
          <tbody>
            {points.map((point) => (
              <tr key={point.at_iso}>
                <td>{clock(point.at_iso)}</td>
                <td>{degrees(point.mean_feels_like_c)}°</td>
                <td>{degrees(point.max_feels_like_c)}°</td>
                <td>{Math.round(point.sun_fraction * 100)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      {points.length > 1 ? (
        <button
          type="button"
          className="ghost-button"
          style={{ marginTop: 10 }}
          onClick={() => setScrubAt(new Date(worst.at_iso))}
          disabled={
            Math.abs(new Date(worst.at_iso).getTime() - departAt.getTime()) < 60_000
          }
        >
          Jump to its worst hour, {clock(worst.at_iso)}
        </button>
      ) : null}
    </section>
  );
}

function Verdict({ points }: { points: TimeseriesPoint[] }) {
  const first = points[0]!;
  const last = points[points.length - 1]!;
  const swing = last.mean_feels_like_c - first.mean_feels_like_c;
  const peak = points.reduce((a, b) =>
    b.mean_feels_like_c > a.mean_feels_like_c ? b : a,
  );

  if (Math.abs(swing) < 0.5 && peak.mean_feels_like_c - first.mean_feels_like_c < 0.5) {
    return (
      <>This route holds steady across the window — its shade does not depend much
      on when you set off.</>
    );
  }
  if (peak.at_iso !== first.at_iso && peak.at_iso !== last.at_iso) {
    return (
      <>
        It peaks at <b>{degrees(peak.mean_feels_like_c)}°</b> around{' '}
        <b>{clock(peak.at_iso)}</b>, then eases off.
      </>
    );
  }
  return swing < 0 ? (
    <>
      Setting off later helps: <b>{Math.round(Math.abs(swing))}°</b> cooler by{' '}
      <b>{clock(last.at_iso)}</b>.
    </>
  ) : (
    <>
      It gets worse from here — <b>{Math.round(swing)}°</b> hotter by{' '}
      <b>{clock(last.at_iso)}</b>.
    </>
  );
}

function layout(points: TimeseriesPoint[]) {
  if (points.length < 2) return null;
  const values = points.flatMap((p) => [p.mean_feels_like_c, p.max_feels_like_c]);
  const rawLo = Math.min(...values);
  const rawHi = Math.max(...values);
  const mid = (rawLo + rawHi) / 2;
  // Never a flat axis: a route that varies by a third of a degree must not be
  // stretched into a mountain range.
  const span = Math.max(rawHi - rawLo, 2);
  const lo = Math.floor(mid - span * 0.7);
  const hi = Math.ceil(mid + span * 0.7);

  const plotW = WIDTH - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const x = (index: number) => PAD.left + (index / (points.length - 1)) * plotW;
  const y = (value: number) =>
    PAD.top + plotH - ((value - lo) / (hi - lo)) * plotH;

  const line = (pick: (p: TimeseriesPoint) => number) =>
    points
      .map(
        (point, index) =>
          `${index === 0 ? 'M' : 'L'}${x(index).toFixed(1)},${y(pick(point)).toFixed(1)}`,
      )
      .join(' ');

  const steps = 3;
  const yTicks = Array.from({ length: steps + 1 }, (_, i) => {
    const value = Math.round(lo + ((hi - lo) * i) / steps);
    return { value, y: y(value) };
  });

  const nearest = (px: number) => {
    const t = (px - PAD.left) / plotW;
    return Math.min(
      points.length - 1,
      Math.max(0, Math.round(t * (points.length - 1))),
    );
  };

  return {
    x,
    y,
    meanPath: line((p) => p.mean_feels_like_c),
    maxPath: line((p) => p.max_feels_like_c),
    yTicks,
    nearest,
  };
}
