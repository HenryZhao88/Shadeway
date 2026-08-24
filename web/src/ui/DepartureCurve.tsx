/** "Wait 38 minutes, be 7 degrees cooler."
 *
 * One series — felt temperature against departure time — so there is no legend
 * box: the title names it. Two points are direct-labelled, `now` and `best`,
 * because those are the only two a reader needs off the line; a number on every
 * point would be noise. Crosshair and tooltip on hover, and a table view for
 * anyone who cannot use the line at all.
 *
 * Sequential encoding: the line is drawn in the heat ramp so its colour agrees
 * with the strip and the map. The axes and grid stay recessive.
 *
 * One honest constraint: the recommendation only ever points at a departure
 * while the sun is still up. The curve keeps falling after sunset — of course
 * it does — but "leave at half nine and it will be five degrees cooler" is not
 * a shade-routing insight, it is nightfall, and offering it as advice would
 * discredit the advice that is real. Sunset is marked on the chart and the
 * after-dark part of the curve is drawn as a dashed continuation.
 */

import { useMemo, useState } from 'react';

import { degrees, heatCss } from '../heat';
import { useStore } from '../state/store';
import { clock, daylightWindow } from '../sun/position';
import type { DeparturePoint } from '../api/types';

const WIDTH = 340;
const HEIGHT = 128;
const PAD = { top: 16, right: 14, bottom: 22, left: 34 };

export default function DepartureCurve() {
  const departure = useStore((s) => s.departure);
  const status = useStore((s) => s.departureStatus);
  const setScrubAt = useStore((s) => s.setScrubAt);
  const origin = useStore((s) => s.origin);
  const [hover, setHover] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);

  const points = departure?.points ?? [];
  const geometry = useMemo(() => layout(points), [points]);
  const sunset = useMemo(() => {
    if (!points.length) return null;
    const day = new Date(points[0]!.depart_iso);
    return daylightWindow(day, origin.lat, origin.lon)?.sunset ?? null;
  }, [points, origin.lat, origin.lon]);

  if (status === 'loading' && !points.length) {
    return (
      <section className="block">
        <p className="eyebrow">when to leave</p>
        <p className="hint" style={{ marginTop: 10 }}>
          <span className="spinner" aria-hidden="true" /> Sweeping the next four
          hours…
        </p>
      </section>
    );
  }
  if (!geometry || points.length < 2) {
    return (
      <section className="block">
        <p className="eyebrow">when to leave</p>
        <p className="hint" style={{ marginTop: 10 }}>
          {status === 'error'
            ? 'The departure sweep did not come back. The route above is unaffected.'
            : 'Not enough departures to draw a curve.'}
        </p>
      </section>
    );
  }

  const nowIndex = clampIndex(departure?.now_index ?? 0, points.length);
  // The server's best_index is the coldest departure in the window, full stop.
  // Re-pick it among departures that are still in daylight — see the note at
  // the top of this file for why that is the honest recommendation.
  const daylightCount = sunset
    ? points.filter((point) => new Date(point.depart_iso) <= sunset).length
    : points.length;
  const bestIndex = bestDaylightIndex(points, daylightCount, nowIndex);
  const coldestIndex = clampIndex(departure?.best_index ?? 0, points.length);
  const coldestIsAfterDark = coldestIndex >= daylightCount && daylightCount > 0;
  const now = points[nowIndex]!;
  const best = points[bestIndex]!;
  const saving = now.best_mean_feels_like_c - best.best_mean_feels_like_c;
  const wait = Math.round(
    (new Date(best.depart_iso).getTime() - new Date(now.depart_iso).getTime()) /
      60000,
  );
  const active = hover != null ? points[hover] : undefined;

  return (
    <section className="block">
      <div className="block-head">
        <p className="eyebrow">when to leave</p>
        <span className="hint">felt °C by departure</span>
      </div>

      <div className="chart">
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          role="img"
          aria-label={`Felt temperature by departure time. Leaving now feels like ${degrees(
            now.best_mean_feels_like_c,
          )} degrees; the coolest departure is ${clock(best.depart_iso)} at ${degrees(
            best.best_mean_feels_like_c,
          )} degrees.`}
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

          {sunset && daylightCount > 0 && daylightCount < points.length ? (
            <g>
              <line
                x1={geometry.x(daylightCount - 1)}
                x2={geometry.x(daylightCount - 1)}
                y1={PAD.top - 4}
                y2={HEIGHT - PAD.bottom}
                stroke="var(--rule-bright)"
                strokeWidth="1"
                strokeDasharray="2 3"
              />
              <text
                x={geometry.x(daylightCount - 1) + 4}
                y={PAD.top - 6}
                fill="var(--ink-3)"
                fontSize="8.5"
                fontFamily="var(--data)"
              >
                sunset
              </text>
            </g>
          ) : null}

          <path
            d={geometry.pathTo(daylightCount)}
            fill="none"
            stroke={heatCss(now.best_mean_feels_like_c)}
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          {daylightCount < points.length ? (
            <path
              d={geometry.pathFrom(daylightCount - 1)}
              fill="none"
              stroke="var(--ink-3)"
              strokeWidth="1.5"
              strokeDasharray="3 3"
              strokeLinecap="round"
            />
          ) : null}

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

          <Marker
            x={geometry.x(nowIndex)}
            y={geometry.y(now.best_mean_feels_like_c)}
            label="now"
            color="var(--ink-2)"
            /* the first point sits on the y-axis, so its label goes to the
               right of the dot instead of centred over the tick numbers */
            anchor={nowIndex === 0 ? 'start' : 'middle'}
          />
          {bestIndex !== nowIndex ? (
            <Marker
              x={geometry.x(bestIndex)}
              y={geometry.y(best.best_mean_feels_like_c)}
              label={clock(best.depart_iso)}
              color="var(--sun)"
              emphasis
            />
          ) : null}

          <text
            x={PAD.left}
            y={HEIGHT - 6}
            fill="var(--ink-3)"
            fontSize="9"
            fontFamily="var(--data)"
          >
            {clock(points[0]!.depart_iso)}
          </text>
          <text
            x={WIDTH - PAD.right}
            y={HEIGHT - 6}
            textAnchor="end"
            fill="var(--ink-3)"
            fontSize="9"
            fontFamily="var(--data)"
          >
            {clock(points[points.length - 1]!.depart_iso)}
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
            <span className="num">{clock(active.depart_iso)}</span> ·{' '}
            <span className="num">{degrees(active.best_mean_feels_like_c)}°</span> ·{' '}
            <span className="num">
              {Math.round(active.best_duration_s / 60)} min
            </span>
          </div>
        ) : null}
      </div>

      <p className="chart-note">
        {saving >= 0.5 && wait > 0 ? (
          <>
            Leave <b>{wait} minutes later</b> and it feels{' '}
            <b>{Math.round(saving)}°</b> cooler.
          </>
        ) : (
          <>Now is as good as it gets while the sun is up.</>
        )}
      </p>
      {coldestIsAfterDark ? (
        <p className="hint" style={{ marginTop: 6 }}>
          It keeps getting cooler after sunset, but that is nightfall rather
          than shade — so the suggestion above stays in daylight.
        </p>
      ) : null}

      {saving >= 0.5 && wait > 0 ? (
        <button
          type="button"
          className="ghost-button"
          style={{ marginTop: 10 }}
          onClick={() => setScrubAt(new Date(best.depart_iso))}
        >
          Plan for {clock(best.depart_iso)}
        </button>
      ) : null}

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
            Felt temperature and duration by departure time
          </caption>
          <thead>
            <tr>
              <th scope="col">leave</th>
              <th scope="col">feels</th>
              <th scope="col">min</th>
            </tr>
          </thead>
          <tbody>
            {points.map((point) => (
              <tr key={point.depart_iso}>
                <td>{clock(point.depart_iso)}</td>
                <td>{degrees(point.best_mean_feels_like_c)}°</td>
                <td>{Math.round(point.best_duration_s / 60)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}

function Marker({
  x,
  y,
  label,
  color,
  emphasis = false,
  anchor = 'middle',
}: {
  x: number;
  y: number;
  label: string;
  color: string;
  emphasis?: boolean;
  anchor?: 'start' | 'middle' | 'end';
}) {
  return (
    <g>
      <circle
        cx={x}
        cy={y}
        r={emphasis ? 4.5 : 3.5}
        fill={color}
        stroke="var(--panel)"
        strokeWidth="2"
      />
      <text
        x={anchor === 'start' ? x + 6 : x}
        y={y - 8}
        textAnchor={anchor}
        fill={color}
        fontSize="9.5"
        fontFamily="var(--data)"
        fontWeight={emphasis ? 600 : 400}
      >
        {label}
      </text>
    </g>
  );
}

/** The coolest departure that is still in daylight, never earlier than now. */
function bestDaylightIndex(
  points: DeparturePoint[],
  daylightCount: number,
  nowIndex: number,
): number {
  const last = Math.max(nowIndex, Math.min(daylightCount, points.length) - 1);
  let best = nowIndex;
  for (let i = nowIndex; i <= last; i += 1) {
    if (points[i]!.best_mean_feels_like_c < points[best]!.best_mean_feels_like_c) {
      best = i;
    }
  }
  return best;
}

function clampIndex(index: number, length: number): number {
  if (!Number.isFinite(index)) return 0;
  return Math.min(Math.max(0, Math.round(index)), Math.max(0, length - 1));
}

function layout(points: DeparturePoint[]) {
  if (points.length < 2) return null;
  const values = points.map((p) => p.best_mean_feels_like_c);
  const rawLo = Math.min(...values);
  const rawHi = Math.max(...values);
  // A degree of headroom, and never a flat axis: a curve that varies by 0.3 C
  // must not be stretched to look like a mountain range.
  const mid = (rawLo + rawHi) / 2;
  const span = Math.max(rawHi - rawLo, 2);
  const lo = Math.floor(mid - span * 0.75);
  const hi = Math.ceil(mid + span * 0.75);

  const plotW = WIDTH - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const x = (index: number) =>
    PAD.left + (index / (points.length - 1)) * plotW;
  const y = (value: number) =>
    PAD.top + plotH - ((value - lo) / (hi - lo)) * plotH;

  const segment = (from: number, to: number) =>
    points
      .slice(Math.max(0, from), Math.max(0, to))
      .map((point, offset) =>
        `${offset === 0 ? 'M' : 'L'}${x(Math.max(0, from) + offset).toFixed(1)},${y(
          point.best_mean_feels_like_c,
        ).toFixed(1)}`,
      )
      .join(' ');
  const pathTo = (count: number) => segment(0, count > 0 ? count : points.length);
  const pathFrom = (index: number) => segment(index, points.length);

  const steps = 3;
  const yTicks = Array.from({ length: steps + 1 }, (_, i) => {
    const value = Math.round(lo + ((hi - lo) * i) / steps);
    return { value, y: y(value) };
  });

  const nearest = (px: number) => {
    const t = (px - PAD.left) / plotW;
    return clampIndex(t * (points.length - 1), points.length);
  };

  return { x, y, pathTo, pathFrom, yTicks, nearest };
}
