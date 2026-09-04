/** The hero is the degrees. Everything else on this rail is evidence for it.
 *
 * When a route lands, the number counts down from what the fast way would have
 * felt like to what the recommended way feels like. That single animation is
 * the product's whole argument — you watch the temperature drop — so it is the
 * one place motion is spent.
 */

import { useEffect, useRef } from 'react';

import { degrees, deltaDegrees, heatCategory, heatCss } from '../heat';
import { prefersReducedMotion, SPRING } from '../motion/spring';
import { useSpringValue } from '../motion/useSpringValue';
import { chosenRouteId, useStore } from '../state/store';
import { minutes } from '../sun/position';
import { temperatureName, temperatureUnit } from '../units';

export default function Hero() {
  const route = useStore((s) => s.route);
  const status = useStore((s) => s.routeStatus);
  const generation = useStore((s) => s.routeGeneration);
  const chosenId = useStore(chosenRouteId);
  const unitSystem = useStore((s) => s.unitSystem);

  const chosen = route && chosenId ? route.routes[chosenId] : undefined;
  const fastest = route?.routes['fastest'];

  const target = chosen?.feels_like_c.mean_c ?? null;
  const from = fastest?.feels_like_c.mean_c ?? null;
  const shown = useCountdown(from, target, generation);

  if (!chosen || target == null) {
    return (
      <section className="hero">
        <p className="eyebrow">what the walk feels like</p>
        <p className="hero-empty">
          {status === 'loading' ? 'Working it out…' : 'Pick two points.'}
        </p>
        <p className="hero-caption">
          shadeway prices a walk in degrees, not minutes, and moves the sun while
          you walk.
        </p>
      </section>
    );
  }

  const delta =
    fastest && chosen.route_id !== 'fastest'
      ? fastest.feels_like_c.mean_c - chosen.feels_like_c.mean_c
      : 0;
  const extraMinutes =
    fastest && chosen.route_id !== 'fastest'
      ? (chosen.duration_s - fastest.duration_s) / 60
      : 0;

  return (
    <section className="hero">
      <p className="eyebrow">what the walk feels like</p>
      <p
        className="hero-degrees"
        style={{ color: heatCss(shown ?? target) }}
        aria-label={`Feels like ${degrees(target, unitSystem)} degrees ${temperatureName(unitSystem)}, ${heatCategory(target)}`}
      >
        {degrees(shown ?? target, unitSystem)}
        <span className="hero-unit">{temperatureUnit(unitSystem)}</span>
      </p>
      <p className="hero-caption">
        {heatCategory(target)} over {minutes(chosen.duration_s)} minutes.{' '}
        {delta >= 0.5 ? (
          <>
            <b>
              {Math.round(extraMinutes) <= 0
                ? 'No extra walking'
                : `${Math.round(extraMinutes)} extra ${Math.round(extraMinutes) === 1 ? 'minute' : 'minutes'}`}
            </b>{' '}
            buys you <b>{deltaDegrees(delta, unitSystem)}°</b>.
          </>
        ) : (
          <>The fast way is already the cool way on this one.</>
        )}
      </p>
    </section>
  );
}

/** Counts from `from` to `to` once per route, on a spring rather than a clock.
 *
 *  The difference shows up when the reader picks the other option while the
 *  count is still running: a keyframed count would restart from a number that
 *  is no longer on screen, and jump. A spring is only ever told a new target,
 *  so it carries its own velocity into the new direction and the digits stay
 *  continuous. Critically damped — a temperature that overshot and came back
 *  would be reading out a value that was never true.
 */
function useCountdown(from: number | null, to: number | null, key: number) {
  const [value, spring] = useSpringValue(to ?? 0, SPRING.readout);
  const seen = useRef<number | null>(null);

  useEffect(() => {
    if (to == null) return;
    const fresh = key !== seen.current;
    seen.current = key;

    if (!fresh) {
      // Same route, different option chosen. Re-aim from wherever it is.
      spring.to(to);
      return;
    }
    // A new route. Start the number at what the fast way would have felt like
    // and let it fall — that one motion is the product's whole argument.
    const worthCounting =
      from != null && Math.abs(from - to) >= 1 && !prefersReducedMotion();
    if (worthCounting) {
      spring.set(from);
      spring.to(to);
    } else {
      spring.set(to);
    }
  }, [from, to, key, spring]);

  return to == null ? null : value;
}
