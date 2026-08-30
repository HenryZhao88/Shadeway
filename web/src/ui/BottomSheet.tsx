/** The phone layout's one structural idea: the map owns the screen, and
 *  everything else rides over it in a sheet you can pull up and push down.
 *
 * This is the pattern every maps app converged on for the same reason — on a
 * phone the map and its explanation cannot both have a fixed share of the
 * screen, because which one you want changes second to second. A sheet lets the
 * reader make that call continuously instead of the layout making it once.
 *
 * Three detents: peek (the headline), half (the recommendation and its
 * evidence) and full (everything). A drag tracks the finger 1:1, a throw lands
 * on the detent the gesture was going toward rather than the one it started
 * next to, and either end of the travel gives rather than stopping dead. The
 * arithmetic is the same motion/ code the scrubber uses.
 *
 * Nothing here moves through React state. The transform is written straight to
 * the node on each frame, so dragging a sheet that contains eight sections and
 * a map does not re-render any of them.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';

import { project, rubberband, VelocityTracker } from '../motion/gesture';
import { createSpring, SPRING, type Spring } from '../motion/spring';

export type Detent = 'peek' | 'half' | 'full';

/** Enough for the grip and one line of headline. */
const PEEK_PX = 136;
/** The sheet's own height, as a share of the space it floats in. Never the
 *  whole thing: a sheet that reaches the top edge stops reading as a sheet. */
const FULL_SHARE = 0.92;
const HALF_SHARE = 0.52;
/** A sheet is thrown, not nudged, so it gets the scroll-view deceleration
 *  rather than the scrubber's deliberately shortened one. Over-projection is
 *  harmless here: the landing is snapped to a detent either way, so a hard
 *  flick simply means "all the way", which is what a hard flick should mean. */
const DECELERATION = 0.998;
/** Below this a release is a placement, not a throw, and gets no bounce. */
const FLICK_PX_PER_S = 320;

const clamp = (value: number, low: number, high: number) =>
  Math.min(high, Math.max(low, value));

export default function BottomSheet({
  detent,
  onDetentChange,
  label,
  children,
}: {
  detent: Detent;
  onDetentChange: (next: Detent) => void;
  label: string;
  children: React.ReactNode;
}) {
  const sheet = useRef<HTMLElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);

  /** Container and sheet heights in pixels, measured rather than assumed. */
  const size = useRef({ container: 0, sheet: 0 });
  /** How far the sheet is pushed down from fully open. 0 is full. */
  const offset = useRef(0);
  const gesture = useRef<{ id: number; grabbedAt: number; from: number } | null>(
    null,
  );
  const velocity = useRef(new VelocityTracker()).current;
  /** The detent the sheet is actually resting at, readable inside handlers
   *  without making them depend on the render that produced them. */
  const resting = useRef<Detent>(detent);
  resting.current = detent;

  const stops = useCallback(() => {
    const { container, sheet: height } = size.current;
    // Ordered top to bottom: full is 0, peek is the furthest down.
    const full = 0;
    const half = clamp(height - container * HALF_SHARE, 0, height);
    const peek = clamp(height - PEEK_PX, half, height);
    return { full, half, peek };
  }, []);

  /** Write the frame. The parent gets the visible height as a custom property
   *  so the map's own controls can sit on top of the sheet rather than under
   *  it — see .map-tools in theme.css. */
  const paint = useCallback((next: number) => {
    offset.current = next;
    const node = sheet.current;
    if (!node) return;
    node.style.transform = `translate3d(0, ${next.toFixed(2)}px, 0)`;
    const visible = Math.max(0, size.current.sheet - next);
    node.parentElement?.style.setProperty('--sheet-visible', `${visible}px`);
  }, []);

  const spring = useRef<Spring | null>(null);
  if (!spring.current) spring.current = createSpring(0, paint, { restDelta: 0.4 });

  const settleTo = useCallback(
    (next: Detent, speed = 0) => {
      const target = stops()[next];
      const flicked = Math.abs(speed) > FLICK_PX_PER_S;
      spring.current!.set(offset.current);
      spring.current!.to(target, {
        velocity: speed,
        config: flicked ? SPRING.sheet : SPRING.ui,
      });
      if (next !== resting.current) onDetentChange(next);
    },
    [onDetentChange, stops],
  );

  // Measure, and keep measuring: a phone that rotates, or a browser whose
  // toolbar slides away, changes the height every detent is derived from.
  useLayoutEffect(() => {
    const node = sheet.current;
    const host = node?.parentElement;
    if (!node || !host) return undefined;
    const measure = () => {
      const container = host.clientHeight;
      if (!container) return;
      size.current = { container, sheet: container * FULL_SHARE };
      node.style.height = `${size.current.sheet}px`;
      if (!gesture.current) {
        spring.current!.set(stops()[resting.current]);
        paint(stops()[resting.current]);
      }
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(host);
    return () => observer.disconnect();
  }, [paint, stops]);

  // Someone else moved it — a route landed, or the reader started picking a
  // point on the map and needs to see the map.
  useEffect(() => {
    if (gesture.current) return;
    const target = stops()[detent];
    if (Math.abs(offset.current - target) < 0.5) return;
    spring.current!.to(target, { config: SPRING.ui });
  }, [detent, stops]);

  const ownsGesture = (target: EventTarget | null) => {
    // The grip always drags. Everywhere else on the sheet drags too, but only
    // while the content is not scrollable — at full height the content is the
    // thing under the finger, and stealing its scroll would be indefensible.
    if ((target as Element | null)?.closest?.('[data-sheet-grip]')) return true;
    return resting.current !== 'full';
  };

  const onPointerDown = (event: React.PointerEvent<HTMLElement>) => {
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    if (!ownsGesture(event.target)) return;
    const node = sheet.current;
    if (!node) return;
    spring.current!.stop();
    gesture.current = {
      id: event.pointerId,
      grabbedAt: event.clientY,
      from: offset.current,
    };
    velocity.reset(event.clientY);
    node.setPointerCapture(event.pointerId);
    setDragging(true);
  };

  const onPointerMove = (event: React.PointerEvent<HTMLElement>) => {
    const drag = gesture.current;
    if (!drag || drag.id !== event.pointerId) return;
    velocity.add(event.clientY);
    const raw = drag.from + (event.clientY - drag.grabbedAt);
    const { full, peek } = stops();
    // Past either end, the sheet gives and gives less the harder it is pushed.
    let next = raw;
    if (raw < full) next = full + rubberband(raw - full, size.current.container);
    else if (raw > peek) {
      next = peek + rubberband(raw - peek, size.current.container);
    }
    paint(next);
  };

  const endGesture = (event: React.PointerEvent<HTMLElement>, thrown = true) => {
    const drag = gesture.current;
    if (!drag || drag.id !== event.pointerId) return;
    gesture.current = null;
    setDragging(false);
    if (sheet.current?.hasPointerCapture(event.pointerId)) {
      sheet.current.releasePointerCapture(event.pointerId);
    }
    const speed = thrown ? velocity.velocity : 0;
    // Land on the detent the throw was heading for, not the one it left from.
    const projected = offset.current + project(speed, DECELERATION);
    const table = stops();
    const nearest = (Object.keys(table) as Detent[]).reduce((best, name) =>
      Math.abs(table[name] - projected) < Math.abs(table[best] - projected)
        ? name
        : best,
    );
    settleTo(nearest, speed);
  };

  /** The grip is a real button, so the sheet is operable without a gesture. */
  const cycle = () => {
    const order: Detent[] = ['peek', 'half', 'full'];
    const next = order[(order.indexOf(resting.current) + 1) % order.length]!;
    settleTo(next);
  };

  return (
    <section
      className="sheet"
      ref={sheet}
      data-detent={detent}
      data-dragging={dragging ? 'true' : undefined}
      aria-label={label}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={(event) => endGesture(event)}
      onPointerCancel={(event) => endGesture(event, false)}
    >
      <div className="sheet-grip" data-sheet-grip>
        <button
          type="button"
          className="sheet-grip-bar"
          onClick={cycle}
          aria-expanded={detent === 'full'}
          aria-label={
            detent === 'full'
              ? 'Collapse route details'
              : 'Expand route details'
          }
        />
      </div>
      <div className="sheet-scroll" ref={scroller}>
        {children}
      </div>
    </section>
  );
}
