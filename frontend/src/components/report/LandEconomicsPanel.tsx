import React from 'react';
import type { LandEconomicsReport } from '../../services/types';
import { Icon } from '../Icon';

/**
 * Land economics & space-efficiency panel.
 *
 * Every number here is read from the land-economics certificate the gate consumes
 * (L1-bearing), never recomputed in the browser. The certificate's own checks are
 * printed in full - a failing check is never hidden behind a green badge.
 */

const CHECK_LABELS: Record<string, string> = {
  site_plan_present: 'Site plan present',
  site_plan: 'Site plan present',
  geometry: 'Land geometry readable',
  footprint_contained_in_buildable: 'Footprint inside the setback buildable',
  coverage_within_limit: 'Ground coverage within the statutory limit',
  program_fits_footprint: 'Programme fits the footprint',
  interior_dead_corners_zero: 'No interior dead corner >= 1 m²',
  residuals_labelled: 'Every residual labelled',
  anonymous_outdoor_zero: 'No anonymous outdoor sliver',
  circulation_within_12_20: 'Circulation ratio within the 12-20% band',
  footprint_utilization_90: 'Footprint utilisation >= 90%',
  furniture_fit: 'Furniture sets fit their rooms',
};

const STATUS_TONE: Record<string, string> = {
  PASS: 'bg-[var(--semantic-green)]/10 text-[var(--semantic-green-ink)]',
  WARN: 'bg-[var(--semantic-amber)]/10 text-[var(--semantic-amber-ink)]',
  FAIL: 'bg-[var(--semantic-red)]/10 text-[var(--semantic-red-ink)]',
};

const fmt = (value: number, digits = 1) =>
  Number.isFinite(value) ? value.toFixed(digits) : '—';

export const LandEconomicsPanel: React.FC<{ report: LandEconomicsReport; className?: string }> = ({
  report,
  className = '',
}) => {
  const cert = report.certificate;
  const status = String(cert?.status ?? 'WARN').toUpperCase();
  const checks = Object.entries(cert?.checks ?? {});
  const failing = checks.filter(([, ok]) => !ok);
  const slivers = report.slivers ?? [];
  // Deduplicated: the same advisory can arrive from the report and from the
  // certificate, and rendering both produced duplicate React keys.
  const warnings = Array.from(
    new Set([...(report.warnings ?? []), ...((cert?.warnings as string[]) ?? [])].filter(Boolean)),
  );

  const kpis = [
    { label: 'Land-use efficiency', value: `${fmt(report.land_use_efficiency_pct)}%` },
    { label: 'Circulation ratio', value: `${fmt(report.circulation_ratio_pct)}%` },
    { label: 'Waste', value: `${fmt(report.waste_area_sqm)} m² (${fmt(report.waste_pct)}%)` },
    { label: 'Footprint utilisation', value: `${fmt(report.footprint_utilization_pct)}%` },
  ];

  const plinthGap = report.footprint_area_sqm - report.program_needed_area_m2;
  const plinthReconciliation =
    plinthGap < -1.0
      ? `${fmt(-plinthGap)} m² short — add a storey, reduce the programme, or enlarge the plate`
      : plinthGap > 1.0
      ? `${fmt(plinthGap)} m² unbuilt — add a storey, enlarge the units, or accept the smaller plate`
      : 'balanced';

  const rows: Array<[string, string, boolean?]> = [
    ['Footprint source', report.footprint_source],
    ['Footprint area', `${fmt(report.footprint_area_sqm)} m²`],
    ['Coverage ceiling', `${fmt(report.coverage_limit_area_sqm)} m²`],
    ['Programme needed', `${fmt(report.program_needed_area_m2)} m²`],
    [
      'Programme deficit',
      report.program_deficit_sqm > 0.05 ? `${fmt(report.program_deficit_sqm)} m² short` : 'none',
      report.program_deficit_sqm > 0.05,
    ],
    ['Plinth reconciliation', plinthReconciliation, Math.abs(plinthGap) > 1.0],
    ['Floor area ratio', fmt(report.floor_area_ratio, 2)],
    ['Interior dead corners', `${fmt(report.dead_corner_area_sqm)} m²`],
    ['Anonymous outdoor area', `${fmt(report.anonymous_outdoor_area_sqm)} m²`],
    ['Residual slivers', `${report.sliver_count} (${report.absorbed_residual_count} absorbed)`],
    [
      'Furniture fit',
      report.furniture_fit_pct == null ? 'not evaluated' : `${fmt(report.furniture_fit_pct)}%`,
    ],
  ];

  return (
    <section
      data-testid="land-economics-panel"
      aria-label="Land economics and space efficiency"
      className={`bw-card rounded-[16px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)] p-4 sm:p-[18px] space-y-3.5 w-full min-w-0 ${className}`}
    >
      <div className="flex items-center justify-between border-b border-[var(--hairline)] pb-2 min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <Icon name="layers" size={15} className="text-[var(--text-2)] shrink-0" />
          <h3 className="text-[14px] font-semibold text-[var(--text-1)] tracking-tight truncate">
            Land Economics & Space Efficiency
          </h3>
        </div>
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-bold shrink-0 ${
            STATUS_TONE[status] ?? 'bg-[var(--fill)] text-[var(--text-2)]'
          }`}
          title="Status of the land-economics certificate. These checks are gate-bearing (L1)."
        >
          {status}
        </span>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2.5" data-testid="land-economics-kpis">
        {kpis.map((kpi) => (
          <div key={kpi.label} className="bg-[var(--fill)] rounded-[10px] px-3 py-2 min-w-0">
            <span className="text-[11px] text-[var(--text-3)] block truncate">{kpi.label}</span>
            <span className="text-[15px] font-semibold text-[var(--text-1)] tabular-nums block truncate">
              {kpi.value}
            </span>
          </div>
        ))}
      </div>

      <div className="divide-y divide-[var(--hairline)] border-y border-[var(--hairline)]">
        {rows.map(([label, value, tone]) => (
          <div key={label} className="min-h-[34px] py-1.5 flex items-center justify-between gap-3">
            <span className="text-[12px] text-[var(--text-2)]">{label}</span>
            <span
              className={`text-[12px] font-semibold tabular-nums text-right ${
                tone ? 'text-[var(--semantic-amber-ink)]' : 'text-[var(--text-1)]'
              }`}
            >
              {value}
            </span>
          </div>
        ))}
      </div>

      {checks.length > 0 && (
        <div className="space-y-1" data-testid="land-economics-checks">
          <div className="flex items-baseline justify-between">
            <span className="text-[11px] font-semibold text-[var(--text-2)]">
              Certificate checks ({checks.length - failing.length}/{checks.length} pass)
            </span>
            {failing.length > 0 && (
              <span className="text-[11px] font-semibold text-[var(--semantic-red-ink)]">
                {failing.length} failing
              </span>
            )}
          </div>
          <ul className="space-y-0.5">
            {checks.map(([name, ok]) => (
              <li key={name} className="flex items-center justify-between gap-2 text-[11px]">
                <span className="text-[var(--text-2)] truncate">{CHECK_LABELS[name] ?? name}</span>
                <span
                  className={`shrink-0 font-mono text-[10px] px-1.5 py-0.5 rounded ${
                    ok ? STATUS_TONE.PASS : STATUS_TONE.FAIL
                  }`}
                >
                  {ok ? 'PASS' : 'FAIL'}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {slivers.length > 0 && (
        <div className="space-y-1" data-testid="land-economics-slivers">
          <span className="text-[11px] font-semibold text-[var(--text-2)]">Residual slivers</span>
          <ul className="space-y-0.5">
            {slivers.map((sliver, index) => (
              <li
                key={`${index}:${sliver.sliver_id}`}
                className="flex items-baseline justify-between gap-2 text-[11px]"
              >
                <span className="font-mono text-[var(--text-3)]">{sliver.sliver_id}</span>
                <span className="text-[var(--text-2)] tabular-nums">
                  {fmt(sliver.area_sqm)} m² · {sliver.absorbed_as ?? 'unassigned'}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {warnings.length > 0 && (
        <ul className="space-y-1" data-testid="land-economics-warnings">
          {warnings.map((warning, index) => (
            <li
              key={`${index}:${warning}`}
              className="text-[11px] leading-snug text-[var(--semantic-amber-ink)] flex items-start gap-1.5"
            >
              <Icon name="alert-triangle" size={11} className="shrink-0 mt-0.5" />
              <span>{warning}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
};
