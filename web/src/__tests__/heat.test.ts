/** The heat scale. Everything on screen that is coloured or named by
 *  temperature comes through here, so a bug in this file makes the map and the
 *  numbers disagree — which is the one thing that would discredit the whole
 *  product. */

import { describe, expect, test } from 'vitest';

import {
  COMFORT_BOUNDARY_C,
  HEAT_STOPS,
  degrees,
  heatCategory,
  heatCss,
  heatRgb,
  signedDegrees,
} from '../heat';

function luminance([r, g, b]: [number, number, number]): number {
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

describe('heatRgb', () => {
  test('clamps below the first stop and above the last', () => {
    expect(heatRgb(-40)).toEqual(heatRgb(HEAT_STOPS[0]!.c));
    expect(heatRgb(200)).toEqual(heatRgb(HEAT_STOPS[HEAT_STOPS.length - 1]!.c));
  });

  test('reproduces each published stop exactly', () => {
    for (const stop of HEAT_STOPS) {
      const [r, g, b] = heatRgb(stop.c);
      const hex = `#${[r, g, b]
        .map((v) => v.toString(16).padStart(2, '0'))
        .join('')}`;
      expect(hex).toBe(stop.hex);
    }
  });

  test('interpolates between stops instead of snapping to bands', () => {
    const lo = heatRgb(32);
    const hi = heatRgb(38);
    const mid = heatRgb(35);
    expect(mid).not.toEqual(lo);
    expect(mid).not.toEqual(hi);
    // the red channel rises monotonically across this pair
    expect(mid[0]).toBeGreaterThanOrEqual(lo[0]);
    expect(mid[0]).toBeLessThanOrEqual(hi[0]);
  });

  test('darkens monotonically once past the heat-stress boundary', () => {
    // The design criterion for the warm half of the ramp: a sequential scale
    // has to be ordered by lightness, or a reader cannot rank two blocks by
    // looking at them. Individual channels are NOT monotone here (the extreme
    // stop is a crimson, so its red channel drops below the orange stop's) --
    // lightness is, and lightness is what carries the ordering.
    const samples = [32, 35, 38, 41, 44, 46];
    const light = samples.map((c) => luminance(heatRgb(c)));
    for (let i = 1; i < samples.length; i += 1) {
      expect(light[i]!).toBeLessThan(light[i - 1]!);
    }
  });

  test('moves away from the cool pole as heat stress begins', () => {
    const cool = heatRgb(18);
    const distance = (c: number) => {
      const [r, g, b] = heatRgb(c);
      return Math.hypot(r - cool[0], g - cool[1], b - cool[2]);
    };
    expect(distance(18)).toBe(0);
    expect(distance(26)).toBeGreaterThan(distance(18));
    expect(distance(32)).toBeGreaterThan(distance(26));
    expect(distance(38)).toBeGreaterThan(distance(32));
  });

  test('no two published stops render as the same colour', () => {
    const seen = new Set(HEAT_STOPS.map((stop) => heatRgb(stop.c).join(',')));
    expect(seen.size).toBe(HEAT_STOPS.length);
  });

  test('every stop stays readable on the dark panel', () => {
    // The panel is #17191c. A stop that sinks into it is invisible on the map.
    const panel = luminance([23, 25, 28]);
    for (const stop of HEAT_STOPS) {
      expect(luminance(heatRgb(stop.c))).toBeGreaterThan(panel * 3);
    }
  });

  test('survives a NaN rather than emitting an invalid colour', () => {
    const [r, g, b] = heatRgb(Number.NaN);
    for (const channel of [r, g, b]) {
      expect(Number.isInteger(channel)).toBe(true);
      expect(channel).toBeGreaterThanOrEqual(0);
      expect(channel).toBeLessThanOrEqual(255);
    }
  });
});

describe('heatCss', () => {
  test('is a css colour the browser will accept', () => {
    expect(heatCss(33)).toMatch(/^rgb\(\d+ \d+ \d+\)$/);
  });
});

describe('heatCategory', () => {
  test('names the published UTCI bands at their boundaries', () => {
    expect(heatCategory(25.9)).toBe('no thermal stress');
    expect(heatCategory(26)).toBe('moderate heat stress');
    expect(heatCategory(32)).toBe('strong heat stress');
    expect(heatCategory(38)).toBe('very strong heat stress');
    expect(heatCategory(46)).toBe('extreme heat stress');
  });

  test('the comfort boundary is the moderate-heat-stress line', () => {
    expect(heatCategory(COMFORT_BOUNDARY_C)).toBe('moderate heat stress');
    expect(heatCategory(COMFORT_BOUNDARY_C - 0.1)).toBe('no thermal stress');
  });

  test('does not claim a category for a missing value', () => {
    expect(heatCategory(Number.NaN)).toBe('unknown');
  });
});

describe('degrees', () => {
  test('rounds to a whole degree, because a tenth overclaims', () => {
    expect(degrees(32.4)).toBe('32');
    expect(degrees(32.6)).toBe('33');
  });

  test('shows an em dash rather than NaN when there is no value', () => {
    expect(degrees(null)).toBe('—');
    expect(degrees(undefined)).toBe('—');
    expect(degrees(Number.NaN)).toBe('—');
  });
});

describe('signedDegrees', () => {
  test('uses a real minus sign, not a hyphen', () => {
    expect(signedDegrees(-8)).toBe('−8°');
  });
  test('marks a warmer route as warmer', () => {
    expect(signedDegrees(3.2)).toBe('+3°');
  });
  test('says so plainly when the difference rounds away', () => {
    expect(signedDegrees(0.2)).toBe('the same');
  });
});
