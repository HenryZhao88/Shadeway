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
 *
 * It is driven by pointer events rather than by the range input's own
 * behaviour, because a range input can only tell you where the finger ended up.
 * This control needs the whole gesture: the press (which sets the time on the
 * way down, not on release), the drag (which tracks 1:1, at minute resolution
 * rather than the five-minute steps the keyboard uses), the edges (which give
 * rather than freeze) and the throw (which lands where the flick was going and
 * settles on a clean five). The range input is still there, still the thing
 * screen readers and arrow keys talk to — it just no longer owns the pointer.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { project, rubberband, VelocityTracker } from '../motion/gesture';
import { createSpring, SPRING, type Spring } from '../motion/spring';
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
const LAST_MINUTE = DAY_MINUTES - 1;
/** What a departure time is allowed to be once you let go of it. */
const STEP_MINUTES = 5;

/** A control whose entire domain is already on screen wants far less coast than
 *  a scroll view whose content runs off the end of it. 0.998 is the scroll
 *  value and it throws a comfortable flick most of a day, which is not a
 *  decision anybody meant to make. 0.985 throws the same flick about two and a
 *  half hours — the size of question this control is actually for. */
const DECELERATION = 0.985;
/** Above this the release reads as a throw, and the landing is allowed to
 *  overshoot because the gesture carried real momentum. Below it the same
 *  landing arrives quietly: bounce nobody asked for reads as a toy.
 *
 *  Only the bounce is conditional. The coast is not — gating that on a
 *  threshold would put a cliff in the middle of the response curve, where one
 *  hair more speed suddenly buys a quarter of an hour. A finger that stopped
 *  before it lifted already reports no velocity (see VelocityTracker), which is
 *  the honest way to say "this was placed, not thrown". */
const FLICK_MIN_PER_S = 240;
/** No single flick may cross more of the day than this. */
const MAX_THROW_MINUTES = 240;
/** Press within this of the handle and you have grabbed the handle: the drag
 *  keeps your offset from it instead of snapping it under your finger. Press
 *  anywhere else and the press itself is the value. */
const GRAB_SLOP_PX = 18;
/** Quarter of a minute — an order of magnitude below anything this can show, so
 *  the spring is called home the frame it stops mattering. */
const REST_MINUTES = 0.25;

const clamp = (value: number, low: number, high: number) =>
  Math.min(high, Math.max(low, value));

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

  const trackRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [grabbing, setGrabbing] = useState(false);
  /** How far the track has been pushed past an end of the day, in pixels. It is
   *  purely visual: the time itself stops at midnight. */
  const [give, setGive] = useState(0);
  /** The gesture's own position, in fractional minutes, and free to sit outside
   *  the day. The store only ever sees this clamped and rounded. */
  const position = useRef(minutesNow);
  const gesture = useRef<{
    id: number;
    /** minutes to add to the pointer's position — how far from the handle the
     *  finger landed, preserved for the life of the drag */
    offset: number;
    left: number;
    width: number;
  } | null>(null);
  const velocity = useRef(new VelocityTracker()).current;

  /** Whole minutes are the finest thing this interface can show, and at this
   *  width one minute is two thirds of a pixel — below the point of seeing.
   *  Rounding here keeps a drag from re-rendering the map for a difference
   *  nobody can perceive. */
  const commit = useCallback((minute: number) => {
    // A track measured mid-layout has zero width, and a zero width turns a
    // pointer position into NaN. Nothing non-finite may reach a Date.
    if (!Number.isFinite(minute)) return;
    const state = useStore.getState();
    const whole = Math.round(clamp(minute, 0, LAST_MINUTE));
    if (whole === minutesIntoDay(state.scrubAt)) return;
    state.setScrubAt(withMinutesIntoDay(state.scrubAt, whole));
  }, []);

  const settle = useRef<Spring | null>(null);
  if (!settle.current) {
    settle.current = createSpring(
      minutesNow,
      (minute) => {
        position.current = minute;
        commit(minute);
      },
      { restDelta: REST_MINUTES },
    );
  }
  const slack = useRef<Spring | null>(null);
  if (!slack.current) {
    // X and the give are separate springs on purpose: one settles on a time,
    // the other unwinds a boundary, and a single spring across both would drag
    // whichever finished first back into the other's timeline.
    slack.current = createSpring(0, setGive, {
      config: SPRING.momentum,
      restDelta: 0.05,
    });
  }

  // Stop, rather than dispose, so StrictMode's effect replay can reuse them.
  useEffect(() => () => {
    settle.current?.stop();
    slack.current?.stop();
  }, []);

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    if (gesture.current) return;
    const element = trackRef.current;
    if (!element) return;

    // Interrupted, not queued. A handle still settling from the last throw is
    // simply grabbed again, and carries on from wherever it is on screen.
    settle.current!.stop();
    slack.current!.stop();

    const rect = element.getBoundingClientRect();
    if (rect.width <= 0) return;
    const current = minutesIntoDay(useStore.getState().scrubAt);
    const pressed = ((event.clientX - rect.left) / rect.width) * DAY_MINUTES;
    const handleX = rect.left + (current / DAY_MINUTES) * rect.width;
    const onHandle = Math.abs(event.clientX - handleX) <= GRAB_SLOP_PX;

    // No movement threshold before committing to the drag. Hysteresis is for
    // surfaces where two gestures are still competing; here there is only one,
    // and a threshold would only be latency.
    gesture.current = {
      id: event.pointerId,
      offset: onHandle ? current - pressed : 0,
      left: rect.left,
      width: rect.width,
    };
    position.current = pressed + gesture.current.offset;
    velocity.reset(position.current);
    element.setPointerCapture(event.pointerId);
    setGrabbing(true);
    // So the arrow keys carry on from where the finger left off.
    inputRef.current?.focus({ preventScroll: true });
    if (!onHandle) commit(position.current);
  };

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = gesture.current;
    if (!drag || drag.id !== event.pointerId) return;
    const raw =
      ((event.clientX - drag.left) / drag.width) * DAY_MINUTES + drag.offset;
    position.current = raw;
    velocity.add(raw);
    commit(raw);

    const past = raw < 0 ? raw : raw > LAST_MINUTE ? raw - LAST_MINUTE : 0;
    slack.current!.set(rubberband((past / DAY_MINUTES) * drag.width, drag.width));
  };

  const endGesture = (event: React.PointerEvent<HTMLDivElement>, thrown = true) => {
    const drag = gesture.current;
    if (!drag || drag.id !== event.pointerId) return;
    gesture.current = null;
    setGrabbing(false);
    if (trackRef.current?.hasPointerCapture(event.pointerId)) {
      trackRef.current.releasePointerCapture(event.pointerId);
    }

    const released = clamp(position.current, 0, LAST_MINUTE);
    const speed = thrown ? velocity.velocity : 0;
    const flicked = Math.abs(speed) > FLICK_MIN_PER_S;
    // Land where the gesture was going, not where the finger happened to stop.
    const coast = clamp(
      project(speed, DECELERATION),
      -MAX_THROW_MINUTES,
      MAX_THROW_MINUTES,
    );
    const projected = clamp(released + coast, 0, LAST_MINUTE);
    const target = clamp(
      Math.round(projected / STEP_MINUTES) * STEP_MINUTES,
      0,
      LAST_MINUTE,
    );

    // Start from the release position carrying the release velocity, so there
    // is no seam between the finger and the animation that follows it.
    settle.current!.set(released);
    settle.current!.to(target, {
      velocity: speed,
      config: flicked ? SPRING.momentum : SPRING.ui,
    });
    slack.current!.to(0, { config: SPRING.momentum });
  };

  return (
    <div className="scrub-inner">
      <div>
        <p className="eyebrow">leaving at</p>
        <p className="scrub-clock" style={{ color: 'var(--accent)' }}>
          {clock(scrubAt)}
        </p>
      </div>

      <div
        className="scrub-track"
        ref={trackRef}
        data-grabbing={grabbing ? 'true' : undefined}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={(event) => endGesture(event)}
        onPointerCancel={(event) => endGesture(event, false)}
      >
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} aria-hidden="true" preserveAspectRatio="none">
          <line
            x1="0"
            x2={WIDTH}
            y1={geometry.horizonY}
            y2={geometry.horizonY}
            stroke="var(--rule)"
            strokeWidth="1"
          />
          <path d={geometry.fill} fill="var(--accent-wash)" />
          <path
            d={geometry.line}
            fill="none"
            stroke="var(--accent-line)"
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
        </svg>

        {/* The handle, and riding on it the sun itself, sitting on the elevation
            curve at exactly this minute. The reading and the thing it describes
            are the same object, so there is nothing to correlate. */}
        <div
          className="scrub-handle"
          style={{
            left: `${(minutesNow / DAY_MINUTES) * 100}%`,
            transform: `translate3d(${give.toFixed(2)}px, 0, 0)`,
          }}
          aria-hidden="true"
        >
          <span className="scrub-handle-stem" />
          <span
            className="scrub-handle-sun"
            style={{ top: `${geometry.yAt(minutesNow).toFixed(1)}px` }}
          />
        </div>

        <input
          ref={inputRef}
          type="range"
          min={0}
          max={DAY_MINUTES - 1}
          step={STEP_MINUTES}
          value={minutesNow}
          onChange={(event) => {
            settle.current!.stop();
            slack.current!.set(0);
            const minute = Number(event.target.value);
            position.current = minute;
            setScrubAt(withMinutesIntoDay(scrubAt, minute));
          }}
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
    /** The curve's height at any minute of the day. The viewBox is the track's
     *  own pixel height, so this is already a CSS offset. */
    yAt(minute: number) {
      if (!Number.isFinite(minute)) return horizonY;
      const span = track.length - 1;
      const t = (clamp(minute, 0, DAY_MINUTES) / DAY_MINUTES) * span;
      const index = Math.min(span - 1, Math.floor(t));
      const fraction = t - index;
      return (
        toY(track[index]!.elevationDeg) * (1 - fraction) +
        toY(track[index + 1]!.elevationDeg) * fraction
      );
    },
  };
}
