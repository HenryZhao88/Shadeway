import { useStore } from '../state/store';
import type { UnitSystem } from '../units';

const OPTIONS: { system: UnitSystem; label: string; units: string }[] = [
  { system: 'imperial', label: 'Imperial', units: '°F · mi' },
  { system: 'metric', label: 'Metric', units: '°C · km' },
];

export default function UnitToggle() {
  const unitSystem = useStore((s) => s.unitSystem);
  const setUnitSystem = useStore((s) => s.setUnitSystem);

  return (
    <div className="unit-toggle" role="group" aria-label="Display units">
      {OPTIONS.map((option) => (
        <button
          type="button"
          key={option.system}
          aria-pressed={unitSystem === option.system}
          aria-label={`Use ${option.label.toLowerCase()} units`}
          onClick={() => setUnitSystem(option.system)}
        >
          <span>{option.label}</span>
          <small>{option.units}</small>
        </button>
      ))}
    </div>
  );
}
