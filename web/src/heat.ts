/** The one place a felt temperature becomes a colour or a word.
 *
 * The map layer, the thermal strip, the compare card, the departure curve and
 * the legend all come through here, so a route line and its number can never
 * disagree about what 33 degrees looks like.
 *
 * The scale is the published UTCI assessment scale (Broede et al. 2012,
 * table 1), hinged on the 26 C boundary between "no thermal stress" and
 * "moderate heat stress". Below the hinge is one cool pole; above it the ramp
 * escalates with rising chroma and falling lightness. Adjacent stops sit inside
 * the colour-vision-deficiency floor band, which is inherent to a continuous
 * scale — so colour is never the only channel anywhere in the interface. The
 * strip has a degree axis, the legend names every category, every route prints
 * its own number.
 */

import {
  temperatureDeltaValue,
  temperatureValue,
  type UnitSystem,
} from './units';

export interface HeatStop {
  readonly c: number;
  readonly hex: string;
}

/** The ramp, at the UTCI category boundaries. */
export const HEAT_STOPS: readonly HeatStop[] = [
  { c: 18, hex: '#50bfbe' },
  { c: 26, hex: '#b4ae99' },
  { c: 32, hex: '#edb333' },
  { c: 38, hex: '#f87724' },
  { c: 46, hex: '#e52751' },
];

/** UTCI assessment categories, so the legend can name what the colours mean. */
export const HEAT_CATEGORIES: readonly { label: string; from: number; hex: string }[] = [
  { label: 'no stress', from: -Infinity, hex: '#50bfbe' },
  { label: 'moderate', from: 26, hex: '#edb333' },
  { label: 'strong', from: 32, hex: '#f87724' },
  { label: 'very strong', from: 38, hex: '#e52751' },
  { label: 'extreme', from: 46, hex: '#e52751' },
];

/** The UTCI heat-stress line. Below it there is no heat stress to accumulate. */
export const COMFORT_BOUNDARY_C = 26;

export type Rgb = [number, number, number];

function hexToRgb(hex: string): Rgb {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

const STOP_RGB: Rgb[] = HEAT_STOPS.map((stop) => hexToRgb(stop.hex));

/** Linear interpolation between ramp stops. sRGB is close enough between
 *  neighbouring stops of an already perceptually-stepped ramp, and it keeps
 *  this callable per-vertex on the map without a colour library. */
export function heatRgb(celsius: number): Rgb {
  if (!Number.isFinite(celsius)) return [120, 130, 140];
  const first = HEAT_STOPS[0]!;
  const last = HEAT_STOPS[HEAT_STOPS.length - 1]!;
  if (celsius <= first.c) return STOP_RGB[0]!;
  if (celsius >= last.c) return STOP_RGB[STOP_RGB.length - 1]!;
  for (let i = 1; i < HEAT_STOPS.length; i += 1) {
    const hi = HEAT_STOPS[i]!;
    if (celsius > hi.c) continue;
    const lo = HEAT_STOPS[i - 1]!;
    const t = (celsius - lo.c) / (hi.c - lo.c);
    const a = STOP_RGB[i - 1]!;
    const b = STOP_RGB[i]!;
    return [
      Math.round(a[0] + (b[0] - a[0]) * t),
      Math.round(a[1] + (b[1] - a[1]) * t),
      Math.round(a[2] + (b[2] - a[2]) * t),
    ];
  }
  return STOP_RGB[STOP_RGB.length - 1]!;
}

export function heatCss(celsius: number): string {
  const [r, g, b] = heatRgb(celsius);
  return `rgb(${r} ${g} ${b})`;
}

/** The UTCI category a felt temperature falls in — the text half of the
 *  encoding, so the colour never has to carry the meaning alone. */
export function heatCategory(celsius: number): string {
  if (!Number.isFinite(celsius)) return 'unknown';
  if (celsius >= 46) return 'extreme heat stress';
  if (celsius >= 38) return 'very strong heat stress';
  if (celsius >= 32) return 'strong heat stress';
  if (celsius >= 26) return 'moderate heat stress';
  if (celsius >= 9) return 'no thermal stress';
  return 'cold stress';
}

/** Rounded to a whole degree, because a tenth of a degree of felt temperature
 *  is well inside the model's own uncertainty and printing it would overclaim. */
export function degrees(
  celsius: number | null | undefined,
  system: UnitSystem = 'metric',
): string {
  if (celsius == null || !Number.isFinite(celsius)) return '—';
  return String(Math.round(temperatureValue(celsius, system)));
}

export function deltaDegrees(
  deltaCelsius: number,
  system: UnitSystem = 'metric',
  decimals = 0,
): string {
  return Math.abs(temperatureDeltaValue(deltaCelsius, system)).toFixed(decimals);
}

export function signedDegrees(
  delta: number,
  system: UnitSystem = 'metric',
): string {
  const rounded = Math.round(Math.abs(temperatureDeltaValue(delta, system)));
  if (rounded === 0) return 'the same';
  return `${delta < 0 ? '−' : '+'}${rounded}°`;
}
