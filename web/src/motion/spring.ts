/** Springs, in Apple's two parameters rather than physics' three.
 *
 * A fixed-duration animation cannot answer new input: it knows where it started
 * and refuses to be told otherwise. A spring only ever knows a target, a current
 * value and a velocity, so re-aiming it mid-flight is the normal case rather
 * than an interruption. Everything the reader can touch in this interface
 * settles on one of these.
 *
 * The parameters are Apple's, not the textbook's:
 *
 *   damping   the damping ratio. 1 is critically damped — it arrives and stops.
 *             Below 1 it overshoots. Bounce is only honest when the gesture
 *             that caused it carried momentum, so 1 is the default and 0.82 is
 *             reserved for the end of a flick.
 *   response  roughly how long, in seconds, the value takes to reach the
 *             target. It is NOT a duration: a spring has no duration, and the
 *             settle time falls out of the two numbers together.
 *
 * Integration is semi-implicit Euler at a fixed sub-step. A closed-form
 * solution would be exact, but it has to branch on the damping ratio and has to
 * be re-derived from scratch on every re-target; the sub-step is stable at any
 * ratio, is exact enough at 240 Hz to be invisible, and makes re-targeting a
 * one-line assignment.
 */

export interface SpringConfig {
  /** Damping ratio. 1 = critically damped, no overshoot. < 1 = bouncy. */
  damping: number;
  /** Seconds to reach the target. Lower is snappier. Not a duration. */
  response: number;
}

/** The house style. Everything critically damped unless a flick preceded it. */
export const SPRING = {
  /** Default for anything that just needs to arrive. */
  ui: { damping: 1, response: 0.35 },
  /** Repositioning something the reader put somewhere. */
  move: { damping: 1, response: 0.4 },
  /** The landing after a throw — the one place overshoot is earned. */
  momentum: { damping: 0.82, response: 0.4 },
  /** A drawer or sheet, per Apple's own table: quicker than a free throw,
   *  because the reader is waiting to read what is on it. */
  sheet: { damping: 0.8, response: 0.3 },
  /** A value counting itself into place, read rather than watched. */
  readout: { damping: 1, response: 0.55 },
} satisfies Record<string, SpringConfig>;

const SUBSTEP_S = 1 / 240;
/** A backgrounded tab hands back one enormous frame. Clamp it rather than
 *  fast-forwarding the spring through half a second of imaginary physics. */
const MAX_FRAME_S = 1 / 20;

export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export interface SpringOptions {
  config?: SpringConfig;
  /** Distance below which the spring is considered home. In the units of the
   *  value being animated, so callers animating degrees and callers animating
   *  minutes both get a threshold that means something. */
  restDelta?: number;
  /** Set true to run even under prefers-reduced-motion. Almost never right. */
  ignoreReducedMotion?: boolean;
}

export interface Spring {
  /** The presentation value — what is on screen this frame. */
  readonly value: number;
  readonly velocity: number;
  readonly settled: boolean;
  /** Re-aim. Position is never reset; velocity is carried through unless a new
   *  one is handed in, which is what makes a reversal a curve rather than a
   *  brick wall. */
  to(target: number, options?: { velocity?: number; config?: SpringConfig }): void;
  /** Hard-set the value — 1:1 tracking during a gesture, where the finger is
   *  the animation and the spring is only along for the ride. */
  set(value: number, velocity?: number): void;
  /** Freeze where it is. The value stays put; the loop stops. */
  stop(): void;
  dispose(): void;
}

export function createSpring(
  initial: number,
  onChange: (value: number) => void,
  options: SpringOptions = {},
): Spring {
  const restDelta = options.restDelta ?? 0.01;
  // A spring that is close but still moving fast is not home. Tie the velocity
  // threshold to the distance threshold so one knob controls both.
  const restVelocity = restDelta * 8;

  let config = options.config ?? SPRING.ui;
  let value = initial;
  let velocity = 0;
  let target = initial;
  let frame = 0;
  let last = 0;
  let disposed = false;

  const reduced = () => !options.ignoreReducedMotion && prefersReducedMotion();

  const emit = () => onChange(value);

  const tick = (now: number) => {
    frame = 0;
    const elapsed = Math.min((now - last) / 1000, MAX_FRAME_S);
    last = now;

    const omega = (2 * Math.PI) / config.response;
    const zeta = config.damping;
    let remaining = elapsed;
    while (remaining > 0) {
      const dt = Math.min(SUBSTEP_S, remaining);
      remaining -= dt;
      const accel = -omega * omega * (value - target) - 2 * zeta * omega * velocity;
      velocity += accel * dt;
      value += velocity * dt;
    }

    if (Math.abs(value - target) < restDelta && Math.abs(velocity) < restVelocity) {
      value = target;
      velocity = 0;
      emit();
      return;
    }
    emit();
    run();
  };

  const run = () => {
    if (disposed || frame) return;
    last = performance.now();
    frame = requestAnimationFrame(tick);
  };

  return {
    get value() {
      return value;
    },
    get velocity() {
      return velocity;
    },
    get settled() {
      return frame === 0;
    },
    to(next, opts) {
      if (opts?.config) config = opts.config;
      target = next;
      if (opts?.velocity !== undefined) velocity = opts.velocity;
      if (reduced()) {
        // Reduced motion is not "no feedback" — it is the same end state
        // without the vestibular part. Arrive, do not travel.
        this.stop();
        value = target;
        velocity = 0;
        emit();
        return;
      }
      if (value === target && velocity === 0) return;
      run();
    },
    set(next, nextVelocity) {
      this.stop();
      value = next;
      target = next;
      velocity = nextVelocity ?? 0;
      emit();
    },
    stop() {
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
    },
    dispose() {
      disposed = true;
      this.stop();
    },
  };
}
