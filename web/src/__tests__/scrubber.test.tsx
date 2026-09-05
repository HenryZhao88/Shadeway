/** The scrubber's gesture.
 *
 * The claims worth testing are the ones a screenshot cannot make: that the
 * press sets the time on the way *down*, that the drag tracks at minute
 * resolution rather than in five-minute steps, that a throw lands past where
 * the finger let go, and that the range input underneath is still the thing a
 * keyboard drives.
 */

import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { useStore } from '../state/store';
import { minutesIntoDay } from '../sun/position';
import TimeScrubber from '../ui/TimeScrubber';

const TRACK_LEFT = 0;
const TRACK_WIDTH = 960;
const DAY_MINUTES = 24 * 60;

/** Where on the track a given minute of the day sits. */
const xFor = (minute: number) => TRACK_LEFT + (minute / DAY_MINUTES) * TRACK_WIDTH;

let now = 0;
let nextFrame = 1;
let pending = new Map<number, FrameRequestCallback>();

function runFrames(count: number, stepMs = 1000 / 60) {
  act(() => {
    for (let i = 0; i < count && pending.size; i += 1) {
      now += stepMs;
      const due = [...pending.values()];
      pending = new Map();
      for (const frame of due) frame(now);
    }
  });
}

function noon() {
  const at = new Date('2026-08-24T00:00:00');
  at.setHours(12, 0, 0, 0);
  return at;
}

function track() {
  // The gesture surface is the track, not the input: the input no longer takes
  // the pointer at all.
  const element = screen.getByLabelText('Departure time').parentElement!;
  element.getBoundingClientRect = () =>
    ({ left: TRACK_LEFT, top: 0, width: TRACK_WIDTH, height: 52, right: TRACK_WIDTH, bottom: 52, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;
  return element;
}

const scrubMinutes = () => minutesIntoDay(useStore.getState().scrubAt);

/** jsdom ships no PointerEvent, so fireEvent.pointerDown drops clientX on the
 *  floor — and clientX is the one property this control reads. React dispatches
 *  on the event's type string, so a MouseEvent named `pointerdown` reaches the
 *  same handler carrying real coordinates. */
function pointer(
  type: 'pointerdown' | 'pointermove' | 'pointerup' | 'pointercancel',
  element: Element,
  init: { clientX?: number; pointerId?: number } = {},
) {
  const event = new MouseEvent(type, {
    bubbles: true,
    cancelable: true,
    clientX: init.clientX ?? 0,
    button: 0,
  });
  Object.assign(event, { pointerId: init.pointerId ?? 1, pointerType: 'mouse' });
  act(() => {
    element.dispatchEvent(event);
  });
}

beforeEach(() => {
  now = 0;
  nextFrame = 1;
  pending = new Map();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }));
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    const id = nextFrame++;
    pending.set(id, callback);
    return id;
  });
  vi.stubGlobal('cancelAnimationFrame', (id: number) => pending.delete(id));
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }),
  );
  vi.spyOn(performance, 'now').mockImplementation(() => now);
  // jsdom has no pointer capture; the control only ever asks politely.
  Element.prototype.setPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
  Element.prototype.hasPointerCapture = vi.fn().mockReturnValue(false);
  useStore.setState({ scrubAt: noon(), departAt: noon(), route: null, routeStatus: 'idle' });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('pressing the track', () => {
  test('sets the time on the way down, not on release', () => {
    render(<TimeScrubber />);
    pointer('pointerdown', track(), { pointerId: 1, clientX: xFor(9 * 60) });
    // No pointerup yet — the value has already moved.
    expect(scrubMinutes()).toBe(9 * 60);
  });

  test('grabbing the handle keeps the offset instead of snapping it under the finger', () => {
    render(<TimeScrubber />);
    const handleX = xFor(12 * 60);
    // 8 px to the right of the handle, inside the grab slop
    pointer('pointerdown', track(), { pointerId: 1, clientX: handleX + 8 });
    expect(scrubMinutes()).toBe(12 * 60);
  });
});

describe('dragging', () => {
  test('tracks the pointer at minute resolution, not in five-minute steps', () => {
    render(<TimeScrubber />);
    const surface = track();
    pointer('pointerdown', surface, { pointerId: 1, clientX: xFor(12 * 60) });
    pointer('pointermove', surface, { pointerId: 1, clientX: xFor(14 * 60 + 3) });
    expect(scrubMinutes()).toBe(14 * 60 + 3);
  });

  test('the far end of the day gives rather than freezing', () => {
    render(<TimeScrubber />);
    const surface = track();
    pointer('pointerdown', surface, { pointerId: 1, clientX: xFor(23 * 60) });
    pointer('pointermove', surface, { pointerId: 1, clientX: TRACK_WIDTH + 220 });
    // the time itself stops at the last minute of the day...
    expect(scrubMinutes()).toBe(DAY_MINUTES - 1);
    // ...while the handle is carried past it, by less than it was pushed
    const handle = document.querySelector('.scrub-handle') as HTMLElement;
    const give = Number(/translate3d\((-?[\d.]+)px/.exec(handle.style.transform)![1]);
    expect(give).toBeGreaterThan(0);
    expect(give).toBeLessThan(220);
  });
});

describe('letting go', () => {
  test('a slow release settles on a clean five minutes', () => {
    render(<TimeScrubber />);
    const surface = track();
    pointer('pointerdown', surface, { pointerId: 1, clientX: xFor(12 * 60) });
    now += 400;
    pointer('pointermove', surface, { pointerId: 1, clientX: xFor(14 * 60 + 3) });
    now += 400; // came to rest before lifting: not a throw
    pointer('pointerup', surface, { pointerId: 1 });
    runFrames(240);
    expect(scrubMinutes()).toBe(14 * 60 + 5);
    expect(scrubMinutes() % 5).toBe(0);
  });

  test('a flick lands past where the finger let go', () => {
    render(<TimeScrubber />);
    const surface = track();
    pointer('pointerdown', surface, { pointerId: 1, clientX: xFor(9 * 60) });
    // ~2 h of day crossed in 50 ms — a throw, not a drag
    now += 25;
    pointer('pointermove', surface, { pointerId: 1, clientX: xFor(10 * 60) });
    now += 25;
    pointer('pointermove', surface, { pointerId: 1, clientX: xFor(11 * 60) });
    const released = scrubMinutes();
    pointer('pointerup', surface, { pointerId: 1 });
    runFrames(400);

    expect(released).toBe(11 * 60);
    expect(scrubMinutes()).toBeGreaterThan(released);
    // and never more than the flick ceiling
    expect(scrubMinutes() - released).toBeLessThanOrEqual(240);
  });

  test('a gentle release coasts a little — there is no cliff in the landing', () => {
    render(<TimeScrubber />);
    const surface = track();
    pointer('pointerdown', surface, { pointerId: 1, clientX: xFor(9 * 60) });
    // 10 minutes of day in 50 ms: real movement, but well under a flick
    now += 50;
    pointer('pointermove', surface, { pointerId: 1, clientX: xFor(9 * 60 + 10) });
    const released = scrubMinutes();
    pointer('pointerup', surface, { pointerId: 1 });
    runFrames(400);

    // It carried on in the direction it was going rather than stopping dead,
    // and it stopped somewhere far short of what a flick would have bought.
    expect(scrubMinutes()).toBeGreaterThan(released);
    expect(scrubMinutes() - released).toBeLessThan(30);
    expect(scrubMinutes() % 5).toBe(0);
  });

  test('a throw can be caught mid-flight and taken over', () => {
    render(<TimeScrubber />);
    const surface = track();
    pointer('pointerdown', surface, { pointerId: 1, clientX: xFor(9 * 60) });
    now += 25;
    pointer('pointermove', surface, { pointerId: 1, clientX: xFor(10 * 60) });
    now += 25;
    pointer('pointermove', surface, { pointerId: 1, clientX: xFor(11 * 60) });
    pointer('pointerup', surface, { pointerId: 1 });
    runFrames(4);
    const caughtAt = scrubMinutes();

    pointer('pointerdown', surface, { pointerId: 2, clientX: xFor(caughtAt) });
    runFrames(400);
    // The coast stopped dead where it was grabbed rather than finishing first.
    expect(scrubMinutes()).toBe(caughtAt);
  });
});

describe('the control underneath', () => {
  test('keyboard input interrupts a flick already in flight', () => {
    render(<TimeScrubber />);
    const surface = track();
    pointer('pointerdown', surface, { clientX: xFor(9 * 60) });
    now += 50;
    pointer('pointermove', surface, { clientX: xFor(10 * 60) });
    pointer('pointerup', surface);
    runFrames(4);

    fireEvent.change(screen.getByLabelText('Departure time'), {
      target: { value: String(18 * 60) },
    });
    runFrames(400);

    expect(scrubMinutes()).toBe(18 * 60);
  });

  test('unmounting cancels motion before it can change departure again', () => {
    const { unmount } = render(<TimeScrubber />);
    const surface = track();
    pointer('pointerdown', surface, { clientX: xFor(9 * 60) });
    now += 50;
    pointer('pointermove', surface, { clientX: xFor(10 * 60) });
    pointer('pointerup', surface);
    runFrames(4);
    const departureAtUnmount = scrubMinutes();

    unmount();
    runFrames(400);

    expect(scrubMinutes()).toBe(departureAtUnmount);
    expect(pending.size).toBe(0);
  });

  test('is still a range input, and still what a keyboard drives', () => {
    render(<TimeScrubber />);
    const input = screen.getByLabelText('Departure time') as HTMLInputElement;
    expect(input.type).toBe('range');
    expect(input.step).toBe('5');
    fireEvent.change(input, { target: { value: String(15 * 60) } });
    expect(scrubMinutes()).toBe(15 * 60);
  });

  test('says what the sun is doing, not just what the number is', () => {
    render(<TimeScrubber />);
    expect(screen.getByLabelText('Departure time')).toHaveAttribute(
      'aria-valuetext',
      expect.stringContaining('degrees above the horizon'),
    );
  });
});
