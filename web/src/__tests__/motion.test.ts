/** The motion primitives, pinned.
 *
 * These are the numbers that decide whether a control feels like an object or
 * like a form field, and none of them are visible in a screenshot — so they are
 * the ones worth a test. The spring is driven through a hand-rolled frame clock
 * rather than real rAF, so a settle is exact rather than flaky.
 */

import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { project, rubberband, VelocityTracker } from '../motion/gesture';
import { createSpring, SPRING } from '../motion/spring';

describe('momentum projection', () => {
  test('is the exponential-decay form, not the textbook one', () => {
    // Apple's sample code: (v / 1000) * d / (1 - d).
    expect(project(1000, 0.998)).toBeCloseTo(499, 6);
    expect(project(1000, 0.99)).toBeCloseTo(99, 6);
  });

  test('a stationary release projects nowhere', () => {
    expect(project(0)).toBe(0);
  });

  test('keeps the direction of the throw', () => {
    expect(project(-800, 0.99)).toBeCloseTo(-project(800, 0.99), 9);
  });

  test('a snappier deceleration rate coasts less', () => {
    expect(Math.abs(project(1000, 0.985))).toBeLessThan(
      Math.abs(project(1000, 0.998)),
    );
  });
});

describe('rubber-banding', () => {
  const WIDTH = 700;

  test('gives nothing back at the boundary itself', () => {
    expect(rubberband(0, WIDTH)).toBe(0);
  });

  test('always gives less than it is pushed', () => {
    for (const overshoot of [5, 25, 120, 600]) {
      expect(rubberband(overshoot, WIDTH)).toBeLessThan(overshoot);
    }
  });

  test('resists more the further it is pushed', () => {
    const near = rubberband(20, WIDTH) / 20;
    const far = rubberband(400, WIDTH) / 400;
    expect(far).toBeLessThan(near);
  });

  test('is symmetric — an edge pushes back the same way at both ends', () => {
    expect(rubberband(-90, WIDTH)).toBeCloseTo(-rubberband(90, WIDTH), 9);
  });

  test('never becomes a hard stop: more push always yields more give', () => {
    expect(rubberband(500, WIDTH)).toBeGreaterThan(rubberband(200, WIDTH));
  });
});

describe('release velocity', () => {
  test('is read across a window, in units per second', () => {
    const tracker = new VelocityTracker();
    tracker.reset(0, 1000);
    tracker.add(30, 1030);
    tracker.add(60, 1060);
    vi.spyOn(performance, 'now').mockReturnValue(1060);
    expect(tracker.velocity).toBeCloseTo(1000, 3);
  });

  test('survives the decelerating straggler that ends most gestures', () => {
    const tracker = new VelocityTracker();
    tracker.reset(0, 1000);
    tracker.add(40, 1020);
    tracker.add(80, 1040);
    // the finger slows as it lifts; the last pair alone would read 200/s
    tracker.add(84, 1060);
    vi.spyOn(performance, 'now').mockReturnValue(1060);
    expect(tracker.velocity).toBeGreaterThan(1000);
  });

  test('a pointer that came to rest before lifting was not thrown', () => {
    const tracker = new VelocityTracker();
    tracker.reset(0, 1000);
    tracker.add(60, 1060);
    vi.spyOn(performance, 'now').mockReturnValue(1400);
    expect(tracker.velocity).toBe(0);
  });

  test('a press with no movement has no velocity', () => {
    const tracker = new VelocityTracker();
    tracker.reset(42, 1000);
    vi.spyOn(performance, 'now').mockReturnValue(1000);
    expect(tracker.velocity).toBe(0);
  });
});

describe('the spring', () => {
  let now = 0;
  let nextId = 1;
  let pending = new Map<number, FrameRequestCallback>();

  /** Run frames until the spring stops asking for them, or the budget runs
   *  out. Returns every value it published, so overshoot is inspectable. */
  function settle(budgetMs = 4000, stepMs = 1000 / 60) {
    const deadline = now + budgetMs;
    while (pending.size && now < deadline) {
      now += stepMs;
      const due = [...pending.values()];
      pending = new Map();
      for (const frame of due) frame(now);
    }
  }

  beforeEach(() => {
    now = 0;
    nextId = 1;
    pending = new Map();
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      const id = nextId++;
      pending.set(id, callback);
      return id;
    });
    vi.stubGlobal('cancelAnimationFrame', (id: number) => {
      pending.delete(id);
    });
    vi.stubGlobal(
      'matchMedia',
      vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }),
    );
    vi.spyOn(performance, 'now').mockImplementation(() => now);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  test('arrives exactly, and stops asking for frames', () => {
    const seen: number[] = [];
    const spring = createSpring(0, (v) => seen.push(v), { config: SPRING.ui });
    spring.to(100);
    settle();
    expect(seen.at(-1)).toBe(100);
    expect(pending.size).toBe(0);
  });

  test('critically damped never overshoots', () => {
    const seen: number[] = [];
    const spring = createSpring(0, (v) => seen.push(v), {
      config: { damping: 1, response: 0.35 },
    });
    spring.to(100);
    settle();
    expect(Math.max(...seen)).toBeLessThanOrEqual(100);
  });

  test('under-damped overshoots — the bounce a flick earns', () => {
    const seen: number[] = [];
    const spring = createSpring(0, (v) => seen.push(v), {
      config: SPRING.momentum,
    });
    spring.to(100);
    settle();
    expect(Math.max(...seen)).toBeGreaterThan(100);
    expect(seen.at(-1)).toBe(100);
  });

  test('a lower response arrives sooner', () => {
    const frames = (response: number) => {
      let count = 0;
      const spring = createSpring(0, () => (count += 1), {
        config: { damping: 1, response },
      });
      spring.to(100);
      settle();
      return count;
    };
    const quick = frames(0.25);
    now = 0;
    const slow = frames(0.6);
    expect(quick).toBeLessThan(slow);
  });

  test('re-targeting mid-flight continues from the value on screen', () => {
    const seen: number[] = [];
    const spring = createSpring(0, (v) => seen.push(v), { config: SPRING.ui });
    spring.to(100);
    // a few frames in, aim somewhere else entirely
    for (let i = 0; i < 6 && pending.size; i += 1) {
      now += 1000 / 60;
      const due = [...pending.values()];
      pending = new Map();
      for (const frame of due) frame(now);
    }
    const midflight = spring.value;
    expect(midflight).toBeGreaterThan(0);
    expect(midflight).toBeLessThan(100);

    const before = seen.length;
    spring.to(0);
    settle();
    // No jump: the first value after the re-target is still next to where it
    // was, not back at some remembered starting point.
    expect(Math.abs(seen[before]! - midflight)).toBeLessThan(5);
    expect(seen.at(-1)).toBe(0);
  });

  test('a reversal carries its velocity through rather than hard-cutting it', () => {
    const spring = createSpring(0, () => {}, { config: SPRING.ui });
    spring.to(100);
    for (let i = 0; i < 6 && pending.size; i += 1) {
      now += 1000 / 60;
      const due = [...pending.values()];
      pending = new Map();
      for (const frame of due) frame(now);
    }
    const carried = spring.velocity;
    expect(carried).toBeGreaterThan(0);
    spring.to(0);
    // Still travelling the old way for a moment — that continuity is what
    // stops a reversal reading as a brick wall.
    expect(spring.velocity).toBe(carried);
  });

  test('an explicit velocity is the hand-off from a gesture', () => {
    const seen: number[] = [];
    const spring = createSpring(0, (v) => seen.push(v), { config: SPRING.ui });
    spring.to(0.0001, { velocity: 600 });
    now += 1000 / 60;
    const due = [...pending.values()];
    pending = new Map();
    for (const frame of due) frame(now);
    // It left in the direction of the throw even though the target was behind.
    expect(seen[0]).toBeGreaterThan(1);
  });

  test('set() is 1:1 tracking — no motion, no queued frames', () => {
    const seen: number[] = [];
    const spring = createSpring(0, (v) => seen.push(v), { config: SPRING.ui });
    spring.to(100);
    spring.set(42);
    expect(seen.at(-1)).toBe(42);
    expect(spring.velocity).toBe(0);
    expect(pending.size).toBe(0);
  });

  test('stop() freezes where it is rather than snapping home', () => {
    const spring = createSpring(0, () => {}, { config: SPRING.ui });
    spring.to(100);
    settle(80);
    spring.stop();
    const frozen = spring.value;
    expect(frozen).toBeGreaterThan(0);
    expect(frozen).toBeLessThan(100);
    settle();
    expect(spring.value).toBe(frozen);
  });

  test('reduced motion arrives without travelling', () => {
    vi.stubGlobal(
      'matchMedia',
      vi.fn().mockReturnValue({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }),
    );
    const seen: number[] = [];
    const spring = createSpring(0, (v) => seen.push(v), { config: SPRING.ui });
    spring.to(100);
    expect(seen).toEqual([100]);
    expect(pending.size).toBe(0);
  });

  test('a stalled tab does not fast-forward the physics', () => {
    const seen: number[] = [];
    const spring = createSpring(0, (v) => seen.push(v), { config: SPRING.ui });
    spring.to(100);
    // one frame worth two seconds, as a backgrounded tab hands back
    now += 2000;
    const due = [...pending.values()];
    pending = new Map();
    for (const frame of due) frame(now);
    // Clamped to a 50 ms step, so it advanced a little, not all the way.
    expect(seen[0]).toBeLessThan(60);
    expect(pending.size).toBe(1);
  });
});
