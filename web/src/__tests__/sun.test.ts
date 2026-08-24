/** Client-side sun position.
 *
 * The shadows on the map come from here and the shade in the routing comes from
 * the server's own solar code. If these two disagree, the map shows a sunlit
 * block that the route calls shaded — so the azimuth convention is worth
 * pinning down hard.
 */

import { describe, expect, test } from 'vitest';

import {
  clock,
  daylightWindow,
  elevationTrack,
  isDaylight,
  minutes,
  minutesIntoDay,
  startOfDay,
  sunPosition,
  withMinutesIntoDay,
} from '../sun/position';

const NYC = { lat: 40.7536, lon: -73.984 };

/** 2025-07-22, a date the server's own solar tests use. Constructed in UTC so
 *  the assertions do not depend on the machine's zone. */
const SUMMER_NOON_UTC = new Date('2025-07-22T16:00:00Z'); // 12:00 EDT
const SUMMER_AFTERNOON_UTC = new Date('2025-07-22T19:00:00Z'); // 15:00 EDT
const SUMMER_MIDNIGHT_UTC = new Date('2025-07-22T05:00:00Z'); // 01:00 EDT

describe('sunPosition', () => {
  test('azimuth is compass degrees from north, not suncalc degrees from south', () => {
    // Around local solar noon in New York the sun is very nearly due south,
    // i.e. an azimuth near 180 -- NOT near 0, which is what suncalc's raw
    // south-referenced value would give.
    const { azimuthDeg } = sunPosition(SUMMER_NOON_UTC, NYC.lat, NYC.lon);
    expect(azimuthDeg).toBeGreaterThan(140);
    expect(azimuthDeg).toBeLessThan(220);
  });

  test('the sun is in the west in the afternoon', () => {
    const { azimuthDeg } = sunPosition(SUMMER_AFTERNOON_UTC, NYC.lat, NYC.lon);
    expect(azimuthDeg).toBeGreaterThan(200);
    expect(azimuthDeg).toBeLessThan(290);
  });

  test('azimuth always stays inside one turn', () => {
    for (let hour = 0; hour < 24; hour += 1) {
      const at = new Date(Date.UTC(2025, 6, 22, hour));
      const { azimuthDeg } = sunPosition(at, NYC.lat, NYC.lon);
      expect(azimuthDeg).toBeGreaterThanOrEqual(0);
      expect(azimuthDeg).toBeLessThan(360);
    }
  });

  test('elevation is high on a July midday and below the horizon at night', () => {
    expect(
      sunPosition(SUMMER_NOON_UTC, NYC.lat, NYC.lon).elevationDeg,
    ).toBeGreaterThan(60);
    expect(
      sunPosition(SUMMER_MIDNIGHT_UTC, NYC.lat, NYC.lon).elevationDeg,
    ).toBeLessThan(0);
  });

  test('isDaylight agrees with the elevation sign', () => {
    expect(isDaylight(SUMMER_NOON_UTC, NYC.lat, NYC.lon)).toBe(true);
    expect(isDaylight(SUMMER_MIDNIGHT_UTC, NYC.lat, NYC.lon)).toBe(false);
  });
});

describe('daylightWindow', () => {
  test('sunrise comes before sunset and both fall on the day asked for', () => {
    const window = daylightWindow(SUMMER_NOON_UTC, NYC.lat, NYC.lon);
    expect(window).not.toBeNull();
    expect(window!.sunrise.getTime()).toBeLessThan(window!.sunset.getTime());
    const hours =
      (window!.sunset.getTime() - window!.sunrise.getTime()) / 3_600_000;
    expect(hours).toBeGreaterThan(13); // New York in late July
    expect(hours).toBeLessThan(16);
  });
});

describe('elevationTrack', () => {
  test('peaks once, somewhere in the middle of the day', () => {
    const track = elevationTrack(SUMMER_NOON_UTC, NYC.lat, NYC.lon, 48);
    const peak = track.reduce(
      (best, point, index) =>
        point.elevationDeg > track[best]!.elevationDeg ? index : best,
      0,
    );
    expect(peak).toBeGreaterThan(4);
    expect(peak).toBeLessThan(track.length - 4);
  });

  test('covers exactly one local day', () => {
    const track = elevationTrack(SUMMER_NOON_UTC, NYC.lat, NYC.lon, 24);
    expect(track).toHaveLength(25);
    const span = track[24]!.at.getTime() - track[0]!.at.getTime();
    expect(span).toBe(86_400_000);
  });
});

describe('scrubber time arithmetic', () => {
  test('minutesIntoDay and withMinutesIntoDay round-trip', () => {
    const base = new Date(2025, 6, 22, 15, 25);
    const minutesValue = minutesIntoDay(base);
    expect(minutesValue).toBe(15 * 60 + 25);
    const rebuilt = withMinutesIntoDay(base, minutesValue);
    expect(rebuilt.getHours()).toBe(15);
    expect(rebuilt.getMinutes()).toBe(25);
  });

  test('withMinutesIntoDay keeps the calendar day it was given', () => {
    const base = new Date(2025, 6, 22, 23, 50);
    const early = withMinutesIntoDay(base, 30);
    expect(early.getDate()).toBe(22);
    expect(early.getHours()).toBe(0);
    expect(early.getMinutes()).toBe(30);
  });

  test('startOfDay zeroes the clock without shifting the date', () => {
    const start = startOfDay(new Date(2025, 6, 22, 15, 25, 30, 500));
    expect(start.getDate()).toBe(22);
    expect(start.getHours()).toBe(0);
    expect(start.getMilliseconds()).toBe(0);
  });
});

describe('formatting', () => {
  test('clock refuses to print a garbage date', () => {
    expect(clock(null)).toBe('—');
    expect(clock(undefined)).toBe('—');
    expect(clock('not a date')).toBe('—');
  });

  test('clock accepts the ISO strings the contract sends', () => {
    expect(clock('2025-07-22T15:00:00-04:00')).toMatch(/\d/);
  });

  test('minutes rounds seconds to whole minutes', () => {
    expect(minutes(894)).toBe('15');
    expect(minutes(30)).toBe('1');
    expect(minutes(0)).toBe('0');
  });
});
