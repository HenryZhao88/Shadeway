/** The bottom sheet's gesture.
 *
 * The claims worth pinning are the ones that decide whether it feels like an
 * object: that a throw lands on the detent it was heading for rather than the
 * one it left, that the grip works without a gesture at all, and that at full
 * height the content keeps its own scrolling instead of having it stolen.
 */

import { act, fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import BottomSheet, { type Detent } from '../ui/BottomSheet';

const CONTAINER = 600;
const SHEET = CONTAINER * 0.92; // 552
// full 0 · half 552 - 312 = 240 · peek 552 - 136 = 416
const STOPS = { full: 0, half: SHEET - CONTAINER * 0.52, peek: SHEET - 136 };

let now = 0;
let nextFrame = 1;
let pending = new Map<number, FrameRequestCallback>();

function runFrames(count = 400, stepMs = 1000 / 60) {
  act(() => {
    for (let i = 0; i < count && pending.size; i += 1) {
      now += stepMs;
      const due = [...pending.values()];
      pending = new Map();
      for (const frame of due) frame(now);
    }
  });
}

/** jsdom ships no PointerEvent, and fireEvent.pointerDown drops clientY — the
 *  one property a vertical drag reads. React dispatches on the type string, so
 *  a MouseEvent named `pointerdown` lands on the same handler with real
 *  coordinates. */
function pointer(
  type: 'pointerdown' | 'pointermove' | 'pointerup',
  element: Element,
  clientY: number,
  pointerId = 1,
) {
  const event = new MouseEvent(type, {
    bubbles: true,
    cancelable: true,
    clientY,
    button: 0,
  });
  Object.assign(event, { pointerId, pointerType: 'touch' });
  act(() => {
    element.dispatchEvent(event);
  });
}

function Host({ initial = 'half' as Detent, children }: { initial?: Detent; children?: React.ReactNode }) {
  const [detent, setDetent] = useState<Detent>(initial);
  return (
    <div style={{ position: 'relative' }}>
      <BottomSheet detent={detent} onDetentChange={setDetent} label="Details">
        <p>a very long list of route evidence</p>
        {children}
      </BottomSheet>
    </div>
  );
}

const sheet = () => document.querySelector('.sheet') as HTMLElement;
const grip = () => screen.getByRole('button');
const content = () => document.querySelector('.sheet-scroll') as HTMLElement;
const offset = () =>
  Number(
    /translate3d\([^,]*,\s*(-?[\d.]+)px/.exec(sheet().style.transform)?.[1] ?? NaN,
  );

beforeEach(() => {
  now = 0;
  nextFrame = 1;
  pending = new Map();
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
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    },
  );
  vi.spyOn(performance, 'now').mockImplementation(() => now);
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(CONTAINER);
  Element.prototype.setPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
  Element.prototype.hasPointerCapture = vi.fn().mockReturnValue(false);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('resting', () => {
  test('opens at the detent it was given, measured from the container', () => {
    render(<Host />);
    expect(offset()).toBeCloseTo(STOPS.half, 0);
  });

  test('publishes how much of itself is showing, so the map controls can clear it', () => {
    render(<Host />);
    const host = sheet().parentElement!;
    expect(host.style.getPropertyValue('--sheet-visible')).toBe(
      `${SHEET - STOPS.half}px`,
    );
  });
});

describe('dragging', () => {
  test('tracks the finger 1:1', () => {
    render(<Host />);
    pointer('pointerdown', sheet(), 400);
    pointer('pointermove', sheet(), 340);
    expect(offset()).toBeCloseTo(STOPS.half - 60, 0);
  });

  test('the top of the travel gives rather than stopping dead', () => {
    render(<Host />);
    pointer('pointerdown', sheet(), 400);
    pointer('pointermove', sheet(), 400 - STOPS.half - 200);
    // pushed 200 px past fully open, and it followed by less than that
    expect(offset()).toBeLessThan(0);
    expect(offset()).toBeGreaterThan(-200);
  });

  test('a slow drag past halfway settles on the detent it was left nearest', () => {
    render(<Host />);
    pointer('pointerdown', sheet(), 400);
    now += 400;
    pointer('pointermove', sheet(), 400 - (STOPS.half - STOPS.full) + 30);
    now += 400; // came to rest before lifting: a placement, not a throw
    pointer('pointerup', sheet(), 400 - (STOPS.half - STOPS.full) + 30);
    runFrames();
    expect(offset()).toBeCloseTo(STOPS.full, 0);
  });

  test('a flick lands where the throw was going, not where it was let go', () => {
    render(<Host />);
    pointer('pointerdown', sheet(), 400);
    // barely moved, but fast: a flick downward
    now += 20;
    pointer('pointermove', sheet(), 425);
    now += 20;
    pointer('pointermove', sheet(), 450);
    pointer('pointerup', sheet(), 450);
    runFrames();
    // 50 px of travel would have left it nearest half; the throw carried it home
    expect(offset()).toBeCloseTo(STOPS.peek, 0);
  });
});

describe('the grip', () => {
  test('keeps capture on the button so a pointer tap can still click it', () => {
    render(<Host />);
    pointer('pointerdown', grip(), 400);
    expect(vi.mocked(Element.prototype.setPointerCapture).mock.instances[0]).toBe(grip());
    pointer('pointerup', grip(), 400);
    fireEvent.click(grip(), { detail: 1 });
    runFrames();
    expect(offset()).toBeCloseTo(STOPS.full, 0);
  });

  test('a click synthesized after dragging does not advance another detent', () => {
    render(<Host />);
    pointer('pointerdown', grip(), 400);
    now += 400;
    pointer('pointermove', grip(), 170);
    now += 400;
    pointer('pointerup', grip(), 170);
    fireEvent.click(grip(), { detail: 1 });
    runFrames();
    expect(offset()).toBeCloseTo(STOPS.full, 0);
  });

  test('advances a detent on a plain tap, so no gesture is required', () => {
    render(<Host />);
    act(() => grip().click());
    runFrames();
    expect(offset()).toBeCloseTo(STOPS.full, 0);
  });

  test('wraps back to peek from the top', () => {
    render(<Host initial="full" />);
    act(() => grip().click());
    runFrames();
    expect(offset()).toBeCloseTo(STOPS.peek, 0);
  });

  test('says which way it will go', () => {
    render(<Host initial="full" />);
    expect(grip()).toHaveAttribute('aria-expanded', 'true');
    expect(grip()).toHaveAccessibleName(/collapse/i);
  });
});

describe('scrolling versus dragging', () => {
  test.each(['half', 'peek'] as Detent[])('controls keep their pointer at %s height', (initial) => {
    render(<Host initial={initial}><button>Search address</button><input aria-label="Address" /></Host>);
    const before = offset();
    for (const element of [screen.getByRole('button', { name: 'Search address' }), screen.getByLabelText('Address')]) {
      pointer('pointerdown', element, 400);
      pointer('pointermove', element, 350);
      pointer('pointerup', element, 350);
    }
    expect(offset()).toBe(before);
    expect(Element.prototype.setPointerCapture).not.toHaveBeenCalled();
  });

  test('unmounting cancels a settling sheet', () => {
    const { unmount } = render(<Host />);
    act(() => grip().click());
    expect(pending.size).toBeGreaterThan(0);
    unmount();
    expect(pending.size).toBe(0);
  });

  test('below full height the whole sheet is a drag surface', () => {
    render(<Host />);
    pointer('pointerdown', content(), 400);
    pointer('pointermove', content(), 350);
    expect(offset()).toBeCloseTo(STOPS.half - 50, 0);
  });

  test('at full height the content keeps its own scrolling', () => {
    render(<Host initial="full" />);
    const before = offset();
    pointer('pointerdown', content(), 400);
    pointer('pointermove', content(), 350);
    // the sheet did not move: that gesture belongs to the list under the finger
    expect(offset()).toBe(before);
  });

  test('the grip still drags at full height', () => {
    render(<Host initial="full" />);
    pointer('pointerdown', grip(), 200);
    pointer('pointermove', grip(), 260);
    expect(offset()).toBeCloseTo(60, 0);
  });
});
