/** Which layout the app builds, and what the topbar keeps in each.
 *
 * The two forms are not a restyle of one tree: on a phone the planner belongs
 * inside the sheet, and on a wide screen it floats over the map with a rail
 * beside it. That is a rendering decision, so it is testable — unlike the
 * stylesheet, which jsdom does not apply, and which is where the bug that
 * emptied the mobile topbar lived.
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import App from '../App';
import { useStore } from '../state/store';
import { mockFetch } from './fixture';

vi.mock('../map/MapCanvas', () => ({
  default: () => <div data-testid="map" />,
}));

const INITIAL = useStore.getState();

function screenIs(compact: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockReturnValue({
      matches: compact,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  );
}

beforeEach(() => {
  useStore.setState({ ...INITIAL, route: null, routeStatus: 'idle' });
  vi.stubGlobal('fetch', vi.fn(mockFetch()));
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('on a phone', () => {
  beforeEach(() => screenIs(true));

  test('the evidence rides in a sheet, and there is no rail competing for height', async () => {
    render(<App />);
    expect(
      await screen.findByRole('region', { name: /route planner and details/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('complementary', { name: /route details/i }),
    ).not.toBeInTheDocument();
  });

  test('the planner is inside the sheet rather than floating over the map', () => {
    render(<App />);
    const sheet = screen.getByRole('region', {
      name: /route planner and details/i,
    });
    const planner = screen.getByRole('region', { name: /plan a walking route/i });
    expect(sheet).toContainElement(planner);
  });

  test('there is exactly one planner, not one per layout', () => {
    render(<App />);
    expect(
      screen.getAllByRole('region', { name: /plan a walking route/i }),
    ).toHaveLength(1);
  });

  test('the topbar renders its controls', () => {
    render(<App />);
    expect(screen.getByRole('group', { name: /unit/i })).toBeInTheDocument();
    expect(screen.getByText(/NYC scene|offline/)).toBeInTheDocument();
  });
});

describe('on a wide screen', () => {
  beforeEach(() => screenIs(false));

  test('the rail returns and no sheet is built', () => {
    render(<App />);
    expect(
      screen.getByRole('complementary', { name: /route details/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('region', { name: /route planner and details/i }),
    ).not.toBeInTheDocument();
  });

  test('there is still exactly one planner', () => {
    render(<App />);
    expect(
      screen.getAllByRole('region', { name: /plan a walking route/i }),
    ).toHaveLength(1);
  });
});

/** Rendering the element is only half of it.
 *
 *  `.topbar > .eyebrow { display: none }` was written to drop the tagline, but
 *  .topbar-meta is also a direct child of .topbar carrying .eyebrow — and at
 *  (0,2,0) it beat that element's own display:flex, so every phone lost the
 *  unit toggle, the clock and the connection status together. Every test above
 *  passed throughout: jsdom does not apply the stylesheet, so no amount of
 *  rendering catches a selector that matches one element too many.
 *
 *  This reads the stylesheet instead and asks the question directly — does any
 *  rule that hides things match something that must never be hidden?
 */
describe('the stylesheet', () => {
  // import.meta.url is an http:// URL under jsdom; vitest runs from web/.
  const css = readFileSync(resolve(process.cwd(), 'src/theme.css'), 'utf8')
    // comments first: they contain braces and selector-shaped prose
    .replace(/\/\*[\s\S]*?\*\//g, '');

  /** Every selector that hides what it matches. Innermost blocks only, which
   *  is what the non-greedy brace pair naturally finds; an at-rule prelude
   *  swept up with the first rule inside it is trimmed at its own brace. */
  function hidingSelectors(): string[] {
    const out: string[] = [];
    for (const [, selector, body] of css.matchAll(/([^{}]*)\{([^{}]*)\}/g)) {
      if (!/display\s*:\s*none/.test(body ?? '')) continue;
      const cleaned = (selector ?? '').slice((selector ?? '').lastIndexOf('{') + 1);
      for (const one of cleaned.split(',')) {
        const trimmed = one.trim();
        if (trimmed && !trimmed.startsWith('@')) out.push(trimmed);
      }
    }
    return out;
  }

  function topbar(): HTMLElement {
    const app = document.createElement('div');
    app.className = 'app has-route is-compact';
    app.innerHTML = `
      <header class="topbar">
        <p class="wordmark"></p>
        <p class="eyebrow topbar-tagline"></p>
        <div class="topbar-meta eyebrow">
          <div class="unit-toggle"><button><span></span></button></div>
          <span class="topbar-date"></span>
          <span class="num"></span>
          <span class="scene-status"></span>
        </div>
      </header>`;
    document.body.append(app);
    return app;
  }

  test('finds the hiding rules at all, so an empty pass means nothing', () => {
    expect(hidingSelectors().length).toBeGreaterThan(5);
  });

  test.each([
    ['.topbar-meta', 'the whole right-hand cluster'],
    ['.unit-toggle', 'switching between °F and °C'],
    ['.scene-status', 'whether the server is reachable'],
  ])('nothing hides %s — %s', (target) => {
    const app = topbar();
    const element = app.querySelector(target)!;
    const offenders = hidingSelectors().filter((selector) => {
      try {
        return element.matches(selector);
      } catch {
        return false; // a selector jsdom cannot parse cannot be judged here
      }
    });
    expect(offenders).toEqual([]);
    app.remove();
  });
});
