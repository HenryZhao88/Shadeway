/** The hero is the degrees. Everything else on this rail is evidence for it.
 *
 * When a route lands, the number counts down from what the fast way would have
 * felt like to what the recommended way feels like. That single animation is
 * the product's whole argument — you watch the temperature drop — so it is the
 * one place motion is spent.
 */

import { useEffect, useRef, useState } from 'react';

import { degrees, heatCategory, heatCss } from '../heat';
import { chosenRouteId, useStore } from '../state/store';
import { minutes } from '../sun/position';

const COUNT_MS = 620;

export default function Hero() {
  const route = useStore((s) => s.route);
  const status = useStore((s) => s.routeStatus);
  const generation = useStore((s) => s.routeGeneration);
  const chosenId = useStore(chosenRouteId);

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
        aria-label={`Feels like ${degrees(target)} degrees Celsius, ${heatCategory(target)}`}
      >
        {degrees(shown ?? target)}
        <span className="hero-unit">°C</span>
      </p>
      <p className="hero-caption">
        {heatCategory(target)} over {minutes(chosen.duration_s)} minutes.{' '}
        {delta >= 0.5 ? (
          <>
            <b>
              {Math.round(extraMinutes) <= 0
                ? 'No extra walking'
                : `${Math.round(extraMinutes)} extra minutes`}
            </b>{' '}
            buys you <b>{Math.round(delta)}°</b>.
          </>
        ) : (
          <>The fast way is already the cool way on this one.</>
        )}
      </p>
    </section>
  );
}

/** Counts from `from` to `to` once per route. Returns `to` immediately when the
 *  reader has asked for reduced motion, or when there is nothing to count
 *  from. */
function useCountdown(from: number | null, to: number | null, key: number) {
  const [value, setValue] = useState<number | null>(to);
  const frame = useRef<number>(0);

  useEffect(() => {
    if (to == null) {
      setValue(null);
      return undefined;
    }
    const reduced =
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const start = from == null || Math.abs(from - to) < 1 ? to : from;
    if (reduced || start === to) {
      setValue(to);
      return undefined;
    }

    const began = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - began) / COUNT_MS);
      // ease-out: the number decelerates into its final value
      const eased = 1 - (1 - t) ** 3;
      setValue(start + (to - start) * eased);
      if (t < 1) frame.current = requestAnimationFrame(step);
    };
    frame.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame.current);
    // `key` is the route generation: re-run once per completed route
  }, [from, to, key]);

  return value;
}
