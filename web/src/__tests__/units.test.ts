import { describe, expect, test } from 'vitest';

import {
  convertMetresInText,
  formatAccuracy,
  formatDistance,
  formatMinutesPerDegree,
  formatSpeed,
  temperatureDeltaValue,
  temperatureValue,
} from '../units';

describe('display units', () => {
  test('converts absolute temperatures differently from deltas', () => {
    expect(temperatureValue(0, 'imperial')).toBe(32);
    expect(temperatureDeltaValue(10, 'imperial')).toBe(18);
  });

  test('formats walking distances and GPS accuracy', () => {
    expect(formatDistance(100, 'metric')).toBe('100 m');
    expect(formatDistance(1609.344, 'imperial')).toBe('1.00 mi');
    expect(formatAccuracy(10, 'imperial')).toBe('33 ft');
  });

  test('formats speed and heat-profile units', () => {
    expect(formatSpeed(1.6, 'imperial', 2)).toBe('3.58 mph');
    expect(formatMinutesPerDegree(1.8, 'imperial')).toBe('1.0 min per °F');
  });

  test('converts metric heights embedded in route evidence', () => {
    expect(convertMetresInText('the 226 m tower', 'imperial')).toBe(
      'the 741 ft tower',
    );
  });
});
