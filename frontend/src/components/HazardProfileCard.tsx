import React, { useState } from 'react';
import type { HazardProfile } from '../services/types';
import { Icon } from './Icon';
import { AMSL_DISCLOSURE, Z_FACTOR_DISCLOSURE } from './report/termDisclosures';

interface HazardProfileCardProps {
  hazard: HazardProfile;
  layout?: 'stack' | 'grid';
}

export const HazardProfileCard: React.FC<HazardProfileCardProps> = ({ hazard, layout = 'stack' }) => {
  const isGrid = layout === 'grid';
  const { seismic, flood, storm_cyclone: storm, overall_hazard_level } = hazard;

  // Zone is null when the site lies outside the
  // IS 1893:2016 mapping extent - a distinct neutral "Not Assessed" state,
  // never styled as a low-risk green signal.
  const isSeismicNotAssessed = !seismic.zone;

  const getSeismicSeverity = (): { level: 'low' | 'moderate' | 'high' | 'not-assessed'; label: string } => {
    if (isSeismicNotAssessed) {
      return { level: 'not-assessed', label: 'Not Assessed' };
    }
    const zone = seismic.zone as string;
    if (zone.includes('V') || zone.includes('IV')) {
      return { level: 'high', label: `${zone} High` };
    }
    if (zone.includes('III')) {
      return { level: 'moderate', label: `${zone} Moderate` };
    }
    return { level: 'low', label: `${zone} Low` };
  };

  const seismicSev = getSeismicSeverity();

  // Worst-severity hazard starts expanded in stack mode; all start expanded in grid mode
  const [expanded, setExpanded] = useState<Record<string, boolean>>(() => {
    if (isGrid) {
      return { seismic: true, flood: true, storm: true };
    }
    const scores: Record<string, number> = {
      seismic: seismicSev.level === 'high' ? 3 : seismicSev.level === 'moderate' ? 2 : seismicSev.level === 'low' ? 1 : 0,
      flood: flood.pressure_level === 'high' ? 3 : flood.pressure_level === 'moderate' ? 2 : 1,
      storm: storm.exposure_level === 'high' ? 3 : storm.exposure_level === 'moderate' ? 2 : 1,
    };
    let worst = 'flood';
    let maxVal = scores.flood;
    for (const [k, v] of Object.entries(scores)) {
      if (v > maxVal) {
        maxVal = v;
        worst = k;
      }
    }
    return {
      seismic: worst === 'seismic',
      flood: worst === 'flood',
      storm: worst === 'storm',
    };
  });

  const toggleExpand = (key: string) => {
    setExpanded((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const getSeverityPill = (level: 'low' | 'moderate' | 'high' | 'critical' | 'not-assessed', customLabel?: string) => {
    // Pill text uses the -ink hues: the bright semantic tokens are fills and
    // measured below AA as small text on their own 12% tints.
    let bg = 'rgba(52, 199, 89, 0.12)';
    let text = 'var(--semantic-green-ink)';
    let label = customLabel || `${level} risk`;

    if (level === 'high' || level === 'critical') {
      bg = 'rgba(255, 59, 48, 0.12)';
      text = 'var(--semantic-red-ink)';
    } else if (level === 'moderate') {
      bg = 'rgba(255, 159, 10, 0.12)';
      text = 'var(--semantic-amber-ink)';
    } else if (level === 'not-assessed') {
      // Neutral gray, dashed treatment: must never read as green "clear"
      bg = 'var(--fill)';
      text = 'var(--text-2)';
    }

    return (
      <span
        className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[12px] font-semibold capitalize shrink-0"
        style={{
          backgroundColor: bg,
          color: text,
          ...(level === 'not-assessed' ? { border: '1px dashed var(--hairline)' } : {}),
        }}
      >
        <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: text }} />
        <span>{label}</span>
      </span>
    );
  };

  /** Data-confidence chip: how much of this reading is live telemetry. */
  const getConfidenceChip = (conf: 'high' | 'moderate' | 'low') => {
    const map = {
      high: { label: 'Verified', cls: 'bg-[var(--semantic-green)]/10 text-[var(--semantic-green-ink)] border border-[var(--semantic-green)]/30', title: 'Measured from live external telemetry this analysis.' },
      moderate: { label: 'Calculated', cls: 'bg-[var(--accent-tint)] text-[var(--accent-ink)] border border-[var(--accent)]/30', title: 'Derived from partial or reanalysed telemetry with known inputs.' },
      low: { label: 'Assumed', cls: 'bg-[var(--semantic-amber)]/10 text-[var(--semantic-amber-ink)] border border-[var(--semantic-amber)]/30', title: 'Fallback baseline model in effect — not a live reading.' },
    } as const;
    const cfg = map[conf] ?? map.low;
    return (
      <span
        data-confidence={conf}
        title={cfg.title}
        className={`hidden sm:inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold tracking-wide shrink-0 ${cfg.cls}`}
      >
        {cfg.label}
      </span>
    );
  };

  const allWarnings = [
    seismic.confidence_warning,
    flood.confidence_warning,
    storm.confidence_warning,
    ...(hazard.warnings || []),
  ].filter((w): w is string => Boolean(w));

  return (
    <div className="space-y-3 w-full min-w-0">
      {/* Overall Hazard Status Pill Header */}
      <div className="flex items-center justify-between border-b border-[var(--hairline)] pb-2 min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <Icon name="activity" size={15} className="text-[var(--text-2)] shrink-0" />
          <h3 className="text-[14px] font-semibold text-[var(--text-1)] tracking-tight">
            Climate & Hazard Vulnerability
          </h3>
        </div>
        {getSeverityPill(overall_hazard_level, `${overall_hazard_level} hazard`)}
      </div>

      <div className={isGrid ? 'grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 items-start' : 'space-y-3'}>
        {/* 1. Seismic Vulnerability Card */}
        <div className="bw-card rounded-[16px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)] p-3.5">
        <button
          type="button"
          onClick={() => toggleExpand('seismic')}
          className="w-full flex items-center justify-between gap-2 text-left cursor-pointer select-none"
          aria-expanded={expanded.seismic}
        >
          <div className="flex items-center gap-2.5 min-w-0">
            <div
              className="w-6 h-6 rounded-[6px] flex items-center justify-center shrink-0"
              style={{
                backgroundColor:
                  seismicSev.level === 'high'
                    ? 'rgba(255, 59, 48, 0.12)'
                    : seismicSev.level === 'moderate'
                    ? 'rgba(255, 159, 10, 0.12)'
                    : seismicSev.level === 'not-assessed'
                    ? 'var(--fill)'
                    : 'rgba(52, 199, 89, 0.12)',
                color:
                  seismicSev.level === 'high'
                    ? 'var(--semantic-red-ink)'
                    : seismicSev.level === 'moderate'
                    ? 'var(--semantic-amber-ink)'
                    : seismicSev.level === 'not-assessed'
                    ? 'var(--text-2)'
                    : 'var(--semantic-green-ink)',
              }}
            >
              <Icon name="activity" size={16} />
            </div>
            <span className="text-[14px] font-semibold text-[var(--text-1)] tracking-tight">
              Seismic Vulnerability
            </span>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {getSeverityPill(seismicSev.level, seismicSev.label)}
            {getConfidenceChip(seismic.confidence)}
            <Icon
              name="chevron-down"
              size={14}
              className={`text-[var(--text-3)] transition-transform duration-250 ${
                expanded.seismic ? 'rotate-180 text-[var(--text-1)]' : ''
              }`}
            />
          </div>
        </button>

        <div
          className={`grid transition-[grid-template-rows] duration-250 ease-out ${
            expanded.seismic ? 'grid-rows-[1fr] mt-3 pt-1 border-t border-[var(--hairline)]' : 'grid-rows-[0fr]'
          }`}
        >
          <div className="overflow-hidden">
            <div className="divide-y divide-[var(--hairline)]">
              <div className="h-10 flex items-center justify-between px-0.5">
                <span className="text-[13px] font-normal text-[var(--text-2)]">50-year quake events</span>
                <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
                  {seismic.event_count_display}
                </span>
              </div>
              <div className="h-10 flex items-center justify-between px-0.5">
                <span className="text-[13px] font-normal text-[var(--text-2)]">Peak recorded magnitude</span>
                <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
                  {seismic.max_magnitude ? `M ${seismic.max_magnitude.toFixed(1)}` : 'None'}
                </span>
              </div>
              <div className="h-10 flex items-center justify-between px-0.5">
                <span className="text-[13px] font-normal text-[var(--text-2)]">Years since last event</span>
                <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
                  {seismic.years_since_last_event !== null && seismic.years_since_last_event !== undefined
                    ? `${seismic.years_since_last_event}y ago`
                    : 'None'}
                </span>
              </div>
              <div className="h-10 flex items-center justify-between px-0.5">
                <span className="inline-flex items-center gap-1 text-[13px] font-normal text-[var(--text-2)]">
                  Design zone factor
                  {Z_FACTOR_DISCLOSURE}
                </span>
                <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
                  {seismic.zone_factor !== null && seismic.zone_factor !== undefined
                    ? `Z = ${seismic.zone_factor.toFixed(2)}`
                    : 'Not assessed'}
                </span>
              </div>
            </div>
            {seismic.recent_major_events && seismic.recent_major_events.length > 0 && (
              <div className="pt-2 space-y-1">
                <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--text-3)] block">
                  Recent significant events
                </span>
                {seismic.recent_major_events.slice(0, 4).map((ev, idx) => (
                  <div key={`${ev.date_iso}-${idx}`} className="flex items-center justify-between gap-2 text-[11px]">
                    <span className="text-[var(--text-2)] truncate" title={ev.place}>{ev.place}</span>
                    <span className="font-mono text-[var(--text-3)] whitespace-nowrap ui-font-tabular">
                      M{ev.magnitude.toFixed(1)} · {ev.distance_km.toFixed(0)} km · {ev.date_iso.slice(0, 10)}
                    </span>
                  </div>
                ))}
              </div>
            )}
            <div className="text-[12px] text-[var(--text-3)] pt-2 border-t border-[var(--hairline)]">
              Source: {seismic.standard}{seismic.district ? ` • ${seismic.district}` : ''}
            </div>
          </div>
        </div>
      </div>

      {/* 2. Hydrological Flood Stress Card */}
      <div className="bw-card rounded-[16px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)] p-3.5">
        <button
          type="button"
          onClick={() => toggleExpand('flood')}
          className="w-full flex items-center justify-between gap-2 text-left cursor-pointer select-none"
          aria-expanded={expanded.flood}
        >
          <div className="flex items-center gap-2.5 min-w-0">
            <div
              className="w-6 h-6 rounded-[6px] flex items-center justify-center shrink-0"
              style={{
                backgroundColor:
                  flood.pressure_level === 'high'
                    ? 'rgba(255, 59, 48, 0.12)'
                    : flood.pressure_level === 'moderate'
                    ? 'rgba(255, 159, 10, 0.12)'
                    : 'rgba(52, 199, 89, 0.12)',
                color:
                  flood.pressure_level === 'high'
                    ? 'var(--semantic-red)'
                    : flood.pressure_level === 'moderate'
                    ? 'var(--semantic-amber)'
                    : 'var(--semantic-green)',
              }}
            >
              <Icon name="droplet" size={16} />
            </div>
            <span className="text-[14px] font-semibold text-[var(--text-1)] tracking-tight">
              Hydrological Flood Stress
            </span>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {getSeverityPill(flood.pressure_level, `${flood.pressure_level} pressure`)}
            {getConfidenceChip(flood.confidence)}
            <Icon
              name="chevron-down"
              size={14}
              className={`text-[var(--text-3)] transition-transform duration-250 ${
                expanded.flood ? 'rotate-180 text-[var(--text-1)]' : ''
              }`}
            />
          </div>
        </button>

        <div
          className={`grid transition-[grid-template-rows] duration-250 ease-out ${
            expanded.flood ? 'grid-rows-[1fr] mt-3 pt-1 border-t border-[var(--hairline)]' : 'grid-rows-[0fr]'
          }`}
        >
          <div className="overflow-hidden">
            <div className="divide-y divide-[var(--hairline)]">
              <div className="h-10 flex items-center justify-between px-0.5">
                <span className="text-[13px] font-normal text-[var(--text-2)]">Peak-to-mean discharge</span>
                <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
                  {flood.discharge_peak_to_mean_ratio !== null && flood.discharge_peak_to_mean_ratio !== undefined
                    ? `${flood.discharge_peak_to_mean_ratio.toFixed(2)}x`
                    : '—'}
                </span>
              </div>
              <div className="h-10 flex items-center justify-between px-0.5">
                <span className="inline-flex items-center gap-1 text-[13px] font-normal text-[var(--text-2)]">
                  Site elevation (AMSL)
                  {AMSL_DISCLOSURE}
                </span>
                <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
                  {flood.elevation_amsl_m !== null && flood.elevation_amsl_m !== undefined
                    ? `${flood.elevation_amsl_m.toFixed(0)}m`
                    : '—'}
                </span>
              </div>
              <div className="h-10 flex items-center justify-between px-0.5">
                <span className="text-[13px] font-normal text-[var(--text-2)]">NDMA flood zone</span>
                <span className="text-[13px] font-semibold text-[var(--text-1)] whitespace-nowrap">
                  {flood.ndma_flood_prone ? 'Prone zone' : 'Clear baseline'}
                </span>
              </div>
              <div className="h-10 flex items-center justify-between px-0.5">
                <span className="text-[13px] font-normal text-[var(--text-2)]">Hydrological pressure</span>
                <span className="text-[13px] font-semibold text-[var(--text-1)] whitespace-nowrap capitalize">
                  {flood.pressure_level}
                </span>
              </div>
            </div>
            <div className="text-[12px] text-[var(--text-3)] pt-2 border-t border-[var(--hairline)]">
              Source: Open-Meteo GloFAS & ECMWF ERA5 Hydrological Monitoring
            </div>
          </div>
        </div>
      </div>

      {/* 3. Storm & Wind Exposure Card */}
      <div className={`bw-card rounded-[16px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)] p-3.5 ${isGrid ? 'md:col-span-2 lg:col-span-1' : ''}`}>
        <button
          type="button"
          onClick={() => toggleExpand('storm')}
          className="w-full flex items-center justify-between gap-2 text-left cursor-pointer select-none"
          aria-expanded={expanded.storm}
        >
          <div className="flex items-center gap-2.5 min-w-0">
            <div
              className="w-6 h-6 rounded-[6px] flex items-center justify-center shrink-0"
              style={{
                backgroundColor:
                  storm.exposure_level === 'high'
                    ? 'rgba(255, 59, 48, 0.12)'
                    : storm.exposure_level === 'moderate'
                    ? 'rgba(255, 159, 10, 0.12)'
                    : 'rgba(52, 199, 89, 0.12)',
                color:
                  storm.exposure_level === 'high'
                    ? 'var(--semantic-red)'
                    : storm.exposure_level === 'moderate'
                    ? 'var(--semantic-amber)'
                    : 'var(--semantic-green)',
              }}
            >
              <Icon name="wind" size={16} />
            </div>
            <span className="text-[14px] font-semibold text-[var(--text-1)] tracking-tight">
              Storm & Wind Exposure
            </span>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {getSeverityPill(storm.exposure_level, `${storm.exposure_level} exposure`)}
            {getConfidenceChip(storm.confidence)}
            <Icon
              name="chevron-down"
              size={14}
              className={`text-[var(--text-3)] transition-transform duration-250 ${
                expanded.storm ? 'rotate-180 text-[var(--text-1)]' : ''
              }`}
            />
          </div>
        </button>

        <div
          className={`grid transition-[grid-template-rows] duration-250 ease-out ${
            expanded.storm ? 'grid-rows-[1fr] mt-3 pt-1 border-t border-[var(--hairline)]' : 'grid-rows-[0fr]'
          }`}
        >
          <div className="overflow-hidden">
            <div className="divide-y divide-[var(--hairline)]">
              <div className="h-10 flex items-center justify-between px-0.5">
                <span className="text-[13px] font-normal text-[var(--text-2)]">Maximum annual wind gust</span>
                <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
                  {storm.max_annual_gust_kmh !== null && storm.max_annual_gust_kmh !== undefined
                    ? `${storm.max_annual_gust_kmh.toFixed(0)} km/h`
                    : '—'}
                </span>
              </div>
              <div className="h-10 flex items-center justify-between px-0.5">
                <span className="text-[13px] font-normal text-[var(--text-2)]">Extreme rainfall days</span>
                <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
                  {storm.extreme_rainfall_days !== null && storm.extreme_rainfall_days !== undefined
                    ? `${storm.extreme_rainfall_days} days/year`
                    : '—'}
                </span>
              </div>
              <div className="h-10 flex items-center justify-between px-0.5">
                <span className="text-[13px] font-normal text-[var(--text-2)]">NDMA cyclone zone</span>
                <span className="text-[13px] font-semibold text-[var(--text-1)] whitespace-nowrap">
                  {storm.ndma_cyclone_prone ? 'Prone zone' : 'Clear baseline'}
                </span>
              </div>
              <div className="h-10 flex items-center justify-between px-0.5">
                <span className="text-[13px] font-normal text-[var(--text-2)]">Wind exposure level</span>
                <span className="text-[13px] font-semibold text-[var(--text-1)] whitespace-nowrap capitalize">
                  {storm.exposure_level}
                </span>
              </div>
            </div>
            <div className="text-[12px] text-[var(--text-3)] pt-2 border-t border-[var(--hairline)]">
              Source: IMD & ECMWF ERA5 Historical Wind Modeling
            </div>
          </div>
        </div>
      </div>
      </div>

      {allWarnings.length > 0 && (
        <div className="p-3 bg-[var(--fill)] rounded-[12px] text-[12px] text-[var(--text-2)] space-y-1">
          <div className="flex items-center gap-1.5 text-[var(--semantic-amber-ink)] font-medium">
            <Icon name="alert-triangle" size={13} />
            <span>Hazard Telemetry Notes</span>
          </div>
          {allWarnings.map((w, idx) => (
            <p key={idx} className="leading-normal">{w}</p>
          ))}
        </div>
      )}
    </div>
  );
};
