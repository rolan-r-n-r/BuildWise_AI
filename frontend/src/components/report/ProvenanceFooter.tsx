import React from 'react';
import type { AnalysisResponse } from '../../services/types';
import { STATUS_LEGEND } from './statusTaxonomy';

interface ProvenanceFooterProps {
  data: AnalysisResponse;
}

/**
 * Report provenance footer: generation token, per-source fetch timestamps
 * when available, the disclaimer, and the status-taxonomy legend with
 * per-context definitions (a word never carries two meanings on one page).
 */
export const ProvenanceFooter: React.FC<ProvenanceFooterProps> = ({ data }) => {
  const gen = data.request_id;
  const stamps: string[] = [];
  const hazard = data.hazard_profile;
  if (hazard?.seismic?.confidence === 'high') stamps.push('Seismic catalog: verified this analysis');
  if (hazard?.seismic?.confidence === 'low') stamps.push('Seismic catalog: fallback baseline');
  if (hazard?.flood?.confidence === 'high') stamps.push('River discharge: verified this analysis');
  if (hazard?.flood?.confidence === 'low') stamps.push('River discharge: fallback baseline');
  if (hazard?.storm_cyclone?.confidence === 'high') stamps.push('Wind telemetry: verified this analysis');
  const verifiedFactors = data.factors.filter((f) => f.raw_value != null).length;
  if (verifiedFactors > 0) stamps.push(`Elevation/climate: verified (${verifiedFactors} factors)`);

  return (
    <footer
      aria-label="Report provenance"
      className="bw-card rounded-[16px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)] p-4 sm:p-[18px] space-y-3 w-full min-w-0"
    >
      {/* Status taxonomy legend — per-context definitions */}
      <div>
        <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--text-3)] block mb-1.5">
          Status legend — meaning depends on context
        </span>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-6 gap-y-1">
          {STATUS_LEGEND.map((row) => (
            <div key={row.status} className="text-[11px] leading-snug">
              <span
                className={`font-bold mr-1.5 ${
                  row.style === 'verified' ? 'text-[var(--semantic-green-ink)]'
                  : row.style === 'calculated' ? 'text-[var(--accent-ink)]'
                  : row.style === 'assumed' ? 'text-[var(--semantic-amber-ink)]'
                  : 'text-[var(--text-2)]'
                }`}
              >
                {row.status}
              </span>
              <span className="text-[var(--text-3)]">
                factors: {row.factorMeaning} · checks: {row.checkMeaning} · annotations: {row.annotationMeaning}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="pt-1.5 border-t border-[var(--hairline)] space-y-1">
        <p className="text-[10px] font-mono text-[var(--text-3)] truncate" title={`Generation token: ${gen}`}>
          GEN {gen}
        </p>
        {stamps.length > 0 && (
          <ul className="text-[10px] text-[var(--text-3)] space-y-0.5">
            {stamps.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        )}
        <p className="text-[10px] text-[var(--text-3)] leading-snug">
          {data.land_value?.disclaimer ||
            'Indicative assessment for pre-feasibility screening only; verify all statutory parameters with the local authority before design decisions.'}
        </p>
      </div>
    </footer>
  );
};
