/**
 * ResultsSummary.tsx — the sidebar's scored summary, behind its own chunk.
 * =======================================================================
 * This is the block the sidebar shows the moment an analysis lands: the compact
 * score hero, the top-3 factor card and the one primary CTA. None of it can be
 * on screen before an analysis exists, and together they drag in a dependency
 * graph (popovers, disclosures, status badges, number formatting) the first view
 * of `/app` does not need — so it is fetched on demand (see App.tsx) behind a
 * same-height placeholder, and warmed when an analysis starts so the chunk is
 * already there when the results arrive.
 *
 * The markup is the sidebar's own, moved verbatim; `data` is the analysis the
 * panel received before the split, and `ctaRef` is the button the report sheet's
 * close path returns focus to.
 */
import React from 'react';
import type { AnalysisResponse } from '../../services/types';
import { ReportHeroHeader } from './ReportHeroHeader';
import { ProvenanceFactorCard } from './ProvenanceFactorCard';
import { Icon } from '../Icon';

export interface ResultsSummaryProps {
  data: AnalysisResponse;
  /** Open the full report sheet — the hero and the CTA both do. */
  onOpenReport: () => void;
  /** The primary CTA, so the sheet's close path can focus it back. */
  ctaRef: React.RefObject<HTMLButtonElement | null>;
}

export const ResultsSummary: React.FC<ResultsSummaryProps> = ({ data, onOpenReport, ctaRef }) => (
  <>
    {/* Score Hero Card (Clicking hero triggers open report) */}
    <ReportHeroHeader data={data} variant="compact" onClickHero={onOpenReport} />

    {/* Top 3 Factor Breakdown Rows — same factor card as the report, so
        status badges and provenance are present in the sidebar too. */}
    <div className="rounded-[14px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)] p-4 sm:p-[18px] space-y-3.5 w-full min-w-0">
      <div className="flex items-center justify-between border-b border-[var(--hairline)] pb-2 min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <Icon name="layers" size={15} className="text-[var(--text-2)] shrink-0" />
          <h3 className="text-[14px] font-semibold text-[var(--text-1)] tracking-tight">
            Multi-Criteria Factor Breakdown
          </h3>
        </div>
        <span className="text-[12px] font-normal text-[var(--text-3)] shrink-0">
          MCDA model (Top 3)
        </span>
      </div>
      <div className="divide-y divide-[var(--hairline)]">
        {data.factors.slice(0, 3).map((factor) => (
          <ProvenanceFactorCard
            key={factor.factor_id}
            factor={factor}
            dataSources={data.data_sources}
            methodology={data.methodology}
            variant="compact"
          />
        ))}
      </div>
    </div>

    {/* ONE Primary CTA: "Open Full Report" */}
    <button
      ref={ctaRef}
      type="button"
      onClick={onOpenReport}
      className="w-full h-10 rounded-[12px] bg-[var(--accent)] hover:bg-[var(--accent-hover)] active:bg-[var(--accent-press)] text-white text-[13px] font-semibold flex items-center justify-center gap-2 shadow-sm transition-ui cursor-pointer select-none"
    >
      <span>Open Full Report</span>
      <Icon name="arrow-up-right" size={16} />
    </button>
  </>
);
