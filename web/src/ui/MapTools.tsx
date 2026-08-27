/** The controls that live on the map rather than the rail: pin visibility, and
 *  planting.
 *
 *  Planting is the "this is a planning tool too" beat. It drops honey locust
 *  crowns into the live scene, invalidates only the horizon-cache entries those
 *  crowns can possibly shade, and re-routes — so the corridor genuinely gets
 *  cooler rather than being redrawn.
 */

import { useStore } from '../state/store';

export default function MapTools() {
  const showAmenities = useStore((s) => s.showAmenities);
  const toggleAmenities = useStore((s) => s.toggleAmenities);
  const pickMode = useStore((s) => s.pickMode);
  const setPickMode = useStore((s) => s.setPickMode);
  const plantedCount = useStore((s) => s.plantedCount);
  const lastPlant = useStore((s) => s.lastPlant);
  const buildingsTruncated = useStore((s) => s.buildingsTruncated);
  const plantingEnabled = useStore((s) => s.health?.planting_enabled ?? false);

  return (
    <>
      <div className="map-overlay map-tools">
        <button
          type="button"
          className="ghost-button"
          aria-pressed={showAmenities}
          onClick={toggleAmenities}
        >
          {showAmenities ? 'Hide water & shade' : 'Show water & shade'}
        </button>
        {plantingEnabled ? (
          <button
            type="button"
            className="ghost-button"
            aria-pressed={pickMode === 'plant'}
            onClick={() => setPickMode(pickMode === 'plant' ? 'none' : 'plant')}
          >
            {pickMode === 'plant'
              ? `Planting${plantedCount ? ` · ${plantedCount}` : ''} · stop`
              : `Plant trees${plantedCount ? ` (${plantedCount})` : ''}`}
          </button>
        ) : null}
      </div>

      {pickMode !== 'none' ? (
        <p className="map-overlay map-hint">
          {pickMode === 'plant' ? (
            lastPlant ? (
              <>
                Planted {lastPlant.planted}. That invalidated{' '}
                <span className="num">{lastPlant.invalidated}</span> cached sample
                points — everything else stayed warm.
              </>
            ) : (
              'Keep clicking to plant honey locusts along a corridor. The route re-runs after each one.'
            )
          ) : (
            `Click the map to set the ${pickMode}.`
          )}
        </p>
      ) : buildingsTruncated ? (
        <p className="map-overlay map-hint">
          City overview is prioritising the tallest buildings. Zoom in for the
          complete street scene and live shadows.
        </p>
      ) : null}
    </>
  );
}
