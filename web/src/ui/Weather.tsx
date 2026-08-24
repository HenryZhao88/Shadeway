/** The weather the felt temperature was computed from.
 *
 * Shown because a felt temperature is only as good as its inputs, and a reader
 * who can see that we used 799 W/m2 of direct beam can check us. The source
 * line matters most: the server labels its offline fallback, and if we are
 * running on made-up weather this says so rather than presenting it as real.
 */

import { useStore } from '../state/store';
import { clock } from '../sun/position';

export default function Weather() {
  const route = useStore((s) => s.route);
  const health = useStore((s) => s.health);
  if (!route) return null;
  const weather = route.weather;
  const isFallback = !weather.source.startsWith('open-meteo');

  return (
    <section className="block">
      <div className="block-head">
        <p className="eyebrow">what we fed the model</p>
        <span className="hint num">{clock(weather.observed_iso)}</span>
      </div>

      <dl className="map-readout" style={{ position: 'static', display: 'grid', gap: 3 }}>
        <Row label="air" value={`${weather.air_temp_c.toFixed(1)} °C`} />
        <Row label="humidity" value={`${Math.round(weather.relative_humidity_pct)} %`} />
        <Row label="wind at 10 m" value={`${weather.wind_speed_10m_ms.toFixed(1)} m/s`} />
        <Row label="cloud" value={`${Math.round(weather.cloud_cover_pct)} %`} />
        <Row label="direct beam" value={`${Math.round(weather.direct_normal_wm2)} W/m²`} />
        <Row label="diffuse" value={`${Math.round(weather.diffuse_wm2)} W/m²`} />
        <Row label="global horizontal" value={`${Math.round(weather.global_horizontal_wm2)} W/m²`} />
      </dl>

      <p className="hint" style={{ marginTop: 10 }}>
        {isFallback ? (
          <b style={{ color: 'var(--heat-38)' }}>
            Weather source: {weather.source}. These are stand-in numbers, not an
            observation.
          </b>
        ) : (
          <>Weather from Open-Meteo. No key, no proxy.</>
        )}
      </p>
      {health ? (
        <p className="hint num" style={{ marginTop: 6 }}>
          {health.n_edges.toLocaleString()} sidewalk edges ·{' '}
          {health.n_samples.toLocaleString()} sample points ·{' '}
          {health.cache_warm
            ? 'horizon cache warm'
            : `cache ${Math.round(health.warm_fraction * 100)}% warm`}
        </p>
      ) : null}
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <b className="num">{value}</b>
    </div>
  );
}
