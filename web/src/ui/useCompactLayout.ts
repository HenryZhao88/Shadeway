import { useEffect, useState } from 'react';

/** Whether the interface is in its one-column, sheet-over-map form.
 *
 *  The same breakpoint the stylesheet uses, read in JavaScript because the two
 *  layouts are not a restyle of one tree — on a phone the planner belongs
 *  inside the sheet, and on a desktop it floats over the map with a rail beside
 *  it. Asking matchMedia is honest about that; rendering both and hiding one
 *  would mount two maps' worth of components to show one.
 */
export const COMPACT_QUERY = '(max-width: 1000px)';

export function useCompactLayout(): boolean {
  const [compact, setCompact] = useState(() => matches());

  useEffect(() => {
    const query = window.matchMedia?.(COMPACT_QUERY);
    if (!query) return undefined;
    const onChange = () => setCompact(query.matches);
    onChange();
    query.addEventListener('change', onChange);
    return () => query.removeEventListener('change', onChange);
  }, []);

  return compact;
}

function matches(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false;
  return window.matchMedia(COMPACT_QUERY).matches;
}
