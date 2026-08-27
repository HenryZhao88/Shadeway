/** Who is walking.
 *
 * Age, medication, outdoor work and pace all collapse into one number: how many
 * extra walking minutes a degree of cooling is worth. That number selects a
 * point on a frontier the router already computed, which is why switching
 * profiles changes the recommendation rather than starting a new search.
 */

import { PROFILES, useStore, type ProfileKey } from '../state/store';
import { PRESET_PROFILE_NAMES } from '../api/types';
import { formatMinutesPerDegree, formatSpeed } from '../units';

const PACES: { label: string; ms: number; note: string }[] = [
  { label: 'strolling', ms: 1.1, note: 'unhurried' },
  { label: 'normal', ms: 1.35, note: 'the usual assumption' },
  { label: 'brisk', ms: 1.6, note: 'somewhere to be' },
];

export default function HeatProfile() {
  const profileKey = useStore((s) => s.profileKey);
  const setProfile = useStore((s) => s.setProfile);
  const walkSpeedMs = useStore((s) => s.walkSpeedMs);
  const setWalkSpeed = useStore((s) => s.setWalkSpeed);
  const unitSystem = useStore((s) => s.unitSystem);

  const profile = PROFILES[profileKey]!;
  const pace = PACES.find((p) => Math.abs(p.ms - walkSpeedMs) < 0.01);

  return (
    <section className="block">
      <div className="block-head">
        <p className="eyebrow">who is walking</p>
        <span className="hint num">
          {formatMinutesPerDegree(profile.minutes_per_degree, unitSystem)}
        </span>
      </div>

      <div className="chip-row" role="group" aria-label="Heat sensitivity">
        {PRESET_PROFILE_NAMES.map((key) => (
          <button
            type="button"
            key={key}
            className="chip"
            aria-pressed={profileKey === key}
            onClick={() => setProfile(key as ProfileKey)}
          >
            {PROFILES[key]!.name}
          </button>
        ))}
      </div>
      <p className="hint" style={{ marginTop: 8 }}>
        {profile.who}
      </p>

      <div className="block-head" style={{ marginTop: 16 }}>
        <p className="eyebrow">pace</p>
        <span className="hint num">{formatSpeed(walkSpeedMs, unitSystem, 2)}</span>
      </div>
      <div className="chip-row" role="group" aria-label="Walking pace">
        {PACES.map((option) => (
          <button
            type="button"
            key={option.label}
            className="chip"
            aria-pressed={Math.abs(option.ms - walkSpeedMs) < 0.01}
            onClick={() => setWalkSpeed(option.ms)}
          >
            {option.label}
          </button>
        ))}
      </div>
      <p className="hint" style={{ marginTop: 8 }}>
        {pace ? pace.note : 'custom'} — pace changes when you reach each block,
        so it changes where the sun is when you get there.
      </p>
    </section>
  );
}
