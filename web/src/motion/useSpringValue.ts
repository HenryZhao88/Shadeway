import { useEffect, useRef, useState } from 'react';

import { createSpring, SPRING, type Spring, type SpringConfig } from './spring';

/** A number that springs to wherever you last aimed it, from wherever it
 *  currently is.
 *
 *  The difference from a keyframe hook is what happens when the target changes
 *  mid-flight: this continues, carrying its velocity, rather than restarting
 *  from a value that is no longer on screen.
 */
export function useSpringValue(
  initial: number,
  config: SpringConfig = SPRING.ui,
  restDelta = 0.01,
): readonly [number, Spring] {
  const [value, setValue] = useState(initial);
  const ref = useRef<Spring | null>(null);
  if (!ref.current) ref.current = createSpring(initial, setValue, { config, restDelta });

  // stop(), not dispose(): a spring that is only paused survives StrictMode's
  // mount / unmount / remount without needing to be rebuilt.
  useEffect(() => () => ref.current?.stop(), []);

  return [value, ref.current] as const;
}
