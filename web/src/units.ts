/** Display-unit conversions. API payloads and all thermal/routing calculations
 * stay in SI; only values crossing the presentation boundary come through here. */

export type UnitSystem = 'imperial' | 'metric';

const FEET_PER_METRE = 3.28084;
const METRES_PER_MILE = 1609.344;
const MPH_PER_MS = 2.236936;

export function temperatureValue(celsius: number, system: UnitSystem): number {
  return system === 'imperial' ? (celsius * 9) / 5 + 32 : celsius;
}

export function temperatureDeltaValue(
  deltaCelsius: number,
  system: UnitSystem,
): number {
  return system === 'imperial' ? (deltaCelsius * 9) / 5 : deltaCelsius;
}

export function temperatureUnit(system: UnitSystem): '°F' | '°C' {
  return system === 'imperial' ? '°F' : '°C';
}

export function temperatureName(system: UnitSystem): 'Fahrenheit' | 'Celsius' {
  return system === 'imperial' ? 'Fahrenheit' : 'Celsius';
}

export function formatDistance(metres: number, system: UnitSystem): string {
  if (!Number.isFinite(metres)) return '—';
  if (system === 'metric') {
    return metres < 1000
      ? `${Math.round(metres)} m`
      : `${(metres / 1000).toFixed(2)} km`;
  }
  const feet = metres * FEET_PER_METRE;
  return metres < 160
    ? `${Math.round(feet)} ft`
    : `${(metres / METRES_PER_MILE).toFixed(2)} mi`;
}

export function formatAccuracy(metres: number, system: UnitSystem): string {
  if (!Number.isFinite(metres)) return '—';
  return system === 'imperial'
    ? `${Math.round(metres * FEET_PER_METRE)} ft`
    : `${Math.round(metres)} m`;
}

export function formatSpeed(
  metresPerSecond: number,
  system: UnitSystem,
  decimals = 1,
): string {
  if (!Number.isFinite(metresPerSecond)) return '—';
  return system === 'imperial'
    ? `${(metresPerSecond * MPH_PER_MS).toFixed(decimals)} mph`
    : `${metresPerSecond.toFixed(decimals)} m/s`;
}

/** Evidence arrives as prose from the API (for example "the 226 m tower"). */
export function convertMetresInText(text: string, system: UnitSystem): string {
  if (system === 'metric') return text;
  return text.replace(/(\d+(?:\.\d+)?)\s*m\b/g, (_match, raw: string) => {
    const feet = Number(raw) * FEET_PER_METRE;
    return `${Math.round(feet)} ft`;
  });
}

/** The profile is stored as minutes per one Celsius degree of cooling. */
export function formatMinutesPerDegree(
  minutesPerCelsius: number,
  system: UnitSystem,
): string {
  if (system === 'metric') {
    const minutes = Number.isInteger(minutesPerCelsius)
      ? minutesPerCelsius.toFixed(0)
      : minutesPerCelsius.toFixed(1);
    return `${minutes} min per °C`;
  }
  const minutes = minutesPerCelsius / 1.8;
  return `${minutes.toFixed(1)} min per °F`;
}
