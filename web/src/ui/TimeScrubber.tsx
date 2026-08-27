/** The scrubber. One control, one meaning: when you are leaving.
 *
 * Dragging it moves the sun on the map immediately, because the shadows come
 * from a client-side sun position and never touch the server. The re-route
 * follows 150 ms after you stop, which is the only part that needs a round
 * trip. So the city responds at frame rate and the route responds when you have
 * finished asking.
 *
 * The shape behind the handle is the sun's elevation across the day. It is not
 * a chart to read values off — it is the track, telling you where in the day
 * you are and where the light runs out, without spending a second axis on it.
 */

import { useMemo } from 'react';

import { DEFAULT_ORIGIN, useStore } from '../state/store';
import {
  clock,
  daylightWindow,
  elevationTrack,
  minutesIntoDay,
  sunPosition,
  withMinutesIntoDay,
} from '../sun/position';

const WIDTH = 1000;
const HEIGHT = 52;
const DAY_MINUTES = 24 * 60;

export default function TimeScrubber() {
  const scrubAt = useStore((s) => s.scrubAt);
  const departAt = useStore((s) => s.departAt);
  const setScrubAt = useStore((s) => s.setScrubAt);
  const selectedOrigin = useStore((s) => s.origin);
  const origin = selectedOrigin ?? DEFAULT_ORIGIN;
  const status = useStore((s) => s.routeStatus);

  const track = useMemo(
    () => elevationTrack(scrubAt, origin.lat, origin.lon),
    // one shape per calendar day and location, not per drag
    [scrubAt.toDateString(), origin.lat, origin.lon],
  );
  const daylight = useMemo(
    () => daylightWindow(scrubAt, origin.lat, origin.lon),
    [scrubAt.toDateString(), origin.lat, origin.lon],
  );
  const sun = sunPosition(scrubAt, origin.lat, origin.lon);

  const minutesNow = minutesIntoDay(scrubAt);
  const pending = Math.abs(scrubAt.getTime() - departAt.getTime()) > 30_000;

  const geometry = useMemo(() => shape(track), [track]);

  return (
    <div className="scrub-inner">
      <div>
        <p className="eyebrow">leaving at</p>
        <p className="scrub-clock" style={{ color: 'var(--sun)' }}>
          {clock(scrubAt)}
        </p>
      </div>

      <div className="scrub-track">
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} aria-hidden="true" preserveAspectRatio="none">
          <line
            x1="0"
            x2={WIDTH}
            y1={geometry.horizonY}
            y2={geometry.horizonY}
            stroke="var(--rule)"
            strokeWidth="1"
          />
          <path d={geometry.fill} fill="rgba(255, 217, 121, 0.10)" />
          <path
            d={geometry.line}
            fill="none"
            stroke="rgba(255, 217, 121, 0.55)"
            strokeWidth="1.5"
          />
          {[6, 9, 12, 15, 18, 21].map((hour) => (
            <g key={hour}>
              <line
                x1={(hour / 24) * WIDTH}
                x2={(hour / 24) * WIDTH}
                y1={HEIGHT - 12}
                y2={HEIGHT}
                stroke="var(--rule)"
                strokeWidth="1"
              />
              <text
                x={(hour / 24) * WIDTH + 5}
                y={HEIGHT - 3}
                fill="var(--ink-3)"
                fontSize="9"
                fontFamily="var(--data)"
              >
                {hour}
              </text>
            </g>
          ))}
          <line
            x1={(minutesNow / DAY_MINUTES) * WIDTH}
            x2={(minutesNow / DAY_MINUTES) * WIDTH}
            y1="0"
            y2={HEIGHT}
            stroke="var(--sun)"
            strokeWidth="1"
            opacity="0.45"
          />
        </svg>

        <input
          type="range"
          min={0}
          max={DAY_MINUTES - 1}
          step={5}
          value={minutesNow}
          onChange={(event) =>
            setScrubAt(withMinutesIntoDay(scrubAt, Number(event.target.value)))
          }
          aria-label="Departure time"
          aria-valuetext={`${clock(scrubAt)}, sun ${sun.elevationDeg.toFixed(
            0,
          )} degrees above the horizon`}
        />
      </div>

      <div className="scrub-status num">
        {status === 'loading' || pending ? (
          <>
            <span className="spinner" aria-hidden="true" /> re-routing
          </>
        ) : (
          <>
            <div>
              sun {sun.elevationDeg > 0 ? `${sun.elevationDeg.toFixed(0)}° up` : 'down'}
            </div>
            <div>az {sun.azimuthDeg.toFixed(0)}°</div>
            {daylight ? <div>sets {clock(daylight.sunset)}</div> : null}
          </>
        )}
      </div>
    </div>
  );
}

/** The sun-elevation silhouette. Elevation is clamped at the horizon: how far
 *  below the horizon the sun is does not matter to a pedestrian, only that it
 *  is gone. */
function shape(track: { at: Date; elevationDeg: number }[]) {
  const horizonY = HEIGHT - 14;
  const peak = Math.max(12, ...track.map((point) => point.elevationDeg));
  const toY = (elevation: number) =>
    horizonY - (Math.max(0, elevation) / peak) * (horizonY - 6);
  const points = track.map((point, index) => {
    const x = (index / (track.length - 1)) * WIDTH;
    return `${x.toFixed(1)},${toY(point.elevationDeg).toFixed(1)}`;
  });
  return {
    horizonY,
    line: `M${points.join(' L')}`,
    fill: `M0,${horizonY} L${points.join(' L')} L${WIDTH},${horizonY} Z`,
  };
}
