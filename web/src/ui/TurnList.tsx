/** The turn cards, including the one Google Maps structurally cannot give you.
 *
 * "Cross to the east side of 5th Ave" is only sayable because the graph holds
 * left and right sidewalks as separate edges. Under it goes the evidence the
 * server computed: how long the side you are leaving stays in the sun, what is
 * shading the side you are moving to, and the degrees between them.
 */

import { useStore, chosenRouteId } from '../state/store';
import { clock } from '../sun/position';
import type { Instruction } from '../api/types';

const KIND_TAG: Record<string, string> = {
  start: 'go',
  turn: 'trn',
  cross: 'xng',
  rest: 'rst',
  arrive: 'end',
  continue: 'cnt',
};

export default function TurnList() {
  const route = useStore((s) => s.route);
  const chosenId = useStore(chosenRouteId);
  const chosen = route && chosenId ? route.routes[chosenId] : undefined;

  if (!chosen) return null;
  const crossings = chosen.instructions.filter((i) => i.type === 'cross').length;

  return (
    <section className="block">
      <div className="block-head">
        <p className="eyebrow">the walk</p>
        <span className="hint">
          {crossings > 0
            ? `${crossings} side ${crossings === 1 ? 'change' : 'changes'}`
            : 'no side changes'}
        </span>
      </div>

      <div className="turns">
        {chosen.instructions.map((instruction, index) => (
          <Card key={`${instruction.type}-${index}`} instruction={instruction} />
        ))}
      </div>

      {chosen.waypoints.length ? (
        <p className="hint" style={{ marginTop: 10 }}>
          Rest stops are suggested once the walk has built up enough heat load to
          be worth breaking — they are additions to the route, not part of it.
        </p>
      ) : null}
    </section>
  );
}

function Card({ instruction }: { instruction: Instruction }) {
  const why = instruction.why;
  const evidence: string[] = [];

  if (why?.sunlit_until_iso) {
    evidence.push(`the side you are leaving stays sunlit until ${clock(why.sunlit_until_iso)}`);
  }
  if (why?.shaded_by) {
    evidence.push(
      why.dappled
        ? `${why.shaded_by} — dappled light, not full shade`
        : `shaded by ${why.shaded_by}`,
    );
  }

  return (
    <div className={`turn turn-${instruction.type}`}>
      <span className="turn-kind">{KIND_TAG[instruction.type] ?? '···'}</span>
      <span>
        <span className="turn-text">{instruction.text}</span>
        {evidence.length || why?.delta_c != null ? (
          <span className="turn-why">
            {why?.delta_c != null ? (
              <span className="num">
                {why.delta_c > 0
                  ? `${Math.abs(why.delta_c).toFixed(1)}° cooler`
                  : `${Math.abs(why.delta_c).toFixed(1)}° warmer`}
              </span>
            ) : null}
            {evidence.map((line) => (
              <span key={line}>{line}</span>
            ))}
          </span>
        ) : null}
      </span>
    </div>
  );
}
