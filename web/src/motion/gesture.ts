/** The three pieces of arithmetic that separate a control you drag from a
 *  control that feels like an object: where a throw is going, how an edge
 *  should push back, and how fast the finger was actually moving.
 */

/** Where a flick comes to rest, given the velocity it was released at.
 *
 *  This is the exponential-decay form Apple ships in the Designing Fluid
 *  Interfaces sample code, not the textbook v^2 / 2a. The point is to animate
 *  to where the gesture was *going*, so a small flick produces a large,
 *  intentional-feeling move.
 *
 *  `decelerationRate` is where the calibration lives. 0.998 is the scroll-view
 *  value, and it is right when the content is longer than the screen. It is
 *  wrong for a control whose entire domain is already on screen — see the
 *  scrubber, which picks its own.
 *
 *  @param velocity units per second
 *  @returns the distance still to travel, in the same units
 */
export function project(velocity: number, decelerationRate = 0.998): number {
  return ((velocity / 1000) * decelerationRate) / (1 - decelerationRate);
}

/** Progressive resistance past a boundary.
 *
 *  A hard clamp reads as frozen — the reader cannot tell a limit from a bug. A
 *  boundary that gives, and gives less the further it is pushed, says "still
 *  listening, but there is nothing over here."
 *
 *  @param overshoot how far past the edge the finger is
 *  @param dimension the size of the thing being dragged against
 */
export function rubberband(overshoot: number, dimension: number, constant = 0.55): number {
  if (overshoot === 0 || dimension === 0) return 0;
  return (overshoot * dimension * constant) / (dimension + constant * Math.abs(overshoot));
}

interface Sample {
  at: number;
  position: number;
}

/** Release velocity, from a short history rather than the last two events.
 *
 *  The final pointermove before a release is frequently a near-zero straggler —
 *  fingers decelerate as they lift. Reading velocity off that one event throws
 *  away the throw. A window of the last ~90 ms is long enough to survive the
 *  straggler and short enough that it is still the velocity the reader meant.
 */
export class VelocityTracker {
  private samples: Sample[] = [];

  constructor(private readonly windowMs = 90) {}

  reset(position: number, at = performance.now()) {
    this.samples = [{ at, position }];
  }

  add(position: number, at = performance.now()) {
    this.samples.push({ at, position });
    const cutoff = at - this.windowMs;
    while (this.samples.length > 2 && this.samples[0]!.at < cutoff) this.samples.shift();
  }

  /** Units per second. Zero when the pointer has been still. */
  get velocity(): number {
    if (this.samples.length < 2) return 0;
    const first = this.samples[0]!;
    const last = this.samples[this.samples.length - 1]!;
    const seconds = (last.at - first.at) / 1000;
    if (seconds <= 0) return 0;
    // A pointer that stopped moving before it lifted was not thrown, whatever
    // the window says about the 90 ms before that.
    if (performance.now() - last.at > this.windowMs) return 0;
    return (last.position - first.position) / seconds;
  }
}
