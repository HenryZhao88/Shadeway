/** Sun position, computed in the browser.
 *
 * This is the reason the time scrubber feels instant: the shadows on the map
 * are driven from here and never touch the server. The server has its own
 * implementation (server/shadeway/thermal/solar.py) for the physics; this one
 * exists purely so dragging the scrubber costs a round trip of zero.
 *
 * suncalc implements the standard low-precision solar position algorithm
 * (Meeus, Astronomical Algorithms), which agrees with NOAA's to well inside a
 * tenth of a degree — far finer than the 5-degree azimuth bins the horizon
 * cache quantises to on the server, so the two cannot visibly disagree.
 */

import SunCalc from 'suncalc';

export interface SunPosition {
  /** Compass degrees: 0 = north, 90 = east. */
  azimuthDeg: number;
  /** Degrees above the horizon; negative when the sun is down. */
  elevationDeg: number;
}

const RAD_TO_DEG = 180 / Math.PI;

export function sunPosition(when: Date, lat: number, lon: number): SunPosition {
  const position = SunCalc.getPosition(when, lat, lon);
  // suncalc measures azimuth from due SOUTH, going west. Everything else in
  // this project — the horizon cache bins, the side-of-street naming, the
  // instruction compass — measures from north, going clockwise.
  return {
    azimuthDeg: (position.azimuth * RAD_TO_DEG + 180 + 360) % 360,
    elevationDeg: position.altitude * RAD_TO_DEG,
  };
}

export function isDaylight(when: Date, lat: number, lon: number): boolean {
  return sunPosition(when, lat, lon).elevationDeg > 0;
}

/** Sunrise and sunset for the day `when` falls in, or null on a polar day. */
export function daylightWindow(
  when: Date,
  lat: number,
  lon: number,
): { sunrise: Date; sunset: Date } | null {
  const times = SunCalc.getTimes(when, lat, lon);
  if (
    !(times.sunrise instanceof Date) ||
    !(times.sunset instanceof Date) ||
    Number.isNaN(times.sunrise.getTime()) ||
    Number.isNaN(times.sunset.getTime())
  ) {
    return null;
  }
  return { sunrise: times.sunrise, sunset: times.sunset };
}

/** Sun elevation sampled across a day — the shape behind the time scrubber.
 *  Not a chart to read values off: it is the track the handle slides along,
 *  telling you where in the day you are without a second axis. */
export function elevationTrack(
  day: Date,
  lat: number,
  lon: number,
  samples = 96,
): { at: Date; elevationDeg: number }[] {
  const start = startOfDay(day);
  const out: { at: Date; elevationDeg: number }[] = [];
  for (let i = 0; i <= samples; i += 1) {
    const at = new Date(start.getTime() + (i / samples) * 86_400_000);
    out.push({ at, elevationDeg: sunPosition(at, lat, lon).elevationDeg });
  }
  return out;
}

export function startOfDay(when: Date): Date {
  const day = new Date(when);
  day.setHours(0, 0, 0, 0);
  return day;
}

/** Minutes since local midnight — the scrubber's unit. */
export function minutesIntoDay(when: Date): number {
  return when.getHours() * 60 + when.getMinutes();
}

export function withMinutesIntoDay(day: Date, minutes: number): Date {
  const out = startOfDay(day);
  out.setMinutes(Math.round(minutes));
  return out;
}

const CLOCK = new Intl.DateTimeFormat(undefined, {
  hour: 'numeric',
  minute: '2-digit',
});

export function clock(when: Date | string | null | undefined): string {
  if (when == null) return '—';
  const date = when instanceof Date ? when : new Date(when);
  if (Number.isNaN(date.getTime())) return '—';
  return CLOCK.format(date);
}

export function minutes(seconds: number): string {
  return String(Math.round(seconds / 60));
}
