import React from 'react';
import type { CostEstimate } from '../services/types';
import { Icon } from './Icon';

interface CostBreakdownTableProps {
  costEstimate: CostEstimate;
  hideSummaryHeader?: boolean;
  /** Payload citation for the baseline (cost_estimate.disclaimer). */
  citation?: string;
}

export const CostBreakdownTable: React.FC<CostBreakdownTableProps> = ({
  costEstimate,
  hideSummaryHeader = false,
  citation,
}) => {
  const formatINR = (val: number) => {
    return new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 0,
    }).format(val);
  };

  return (
    <div className="bw-card rounded-[16px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)] p-4 space-y-3.5 w-full min-w-0">
      {/* Section Header */}
      <div className="flex items-center justify-between border-b border-[var(--hairline)] pb-2 min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <Icon name="currency-rupee" size={15} className="text-[var(--text-2)] shrink-0" />
          <h3 className="text-[14px] font-semibold text-[var(--text-1)] tracking-tight">
            Preliminary Construction Cost Estimation
          </h3>
        </div>
        <span className="text-[12px] font-normal text-[var(--text-3)] shrink-0" title={citation}>
          CPWD PAR baseline
        </span>
      </div>

      {!hideSummaryHeader && (
        <>
          {/* Key-Value Rows */}
          <div className="divide-y divide-[var(--hairline)] border-y border-[var(--hairline)]">
            <div className="h-10 flex items-center justify-between px-0.5">
              <span className="text-[13px] font-normal text-[var(--text-2)]">Plinth area base rate</span>
              <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
                ₹{costEstimate.base_rate_per_sqft.toLocaleString()}/sq ft
              </span>
            </div>
            <div className="h-10 flex items-center justify-between px-0.5">
              <span className="text-[13px] font-normal text-[var(--text-2)]">Topographic terrain modifier</span>
              <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
                {costEstimate.terrain_multiplier.toFixed(2)}x {costEstimate.terrain_surcharge_inr > 0 ? `(+${formatINR(costEstimate.terrain_surcharge_inr)})` : '(Baseline)'}
              </span>
            </div>
          </div>

          {/* Total Estimated Civil Budget */}
          <div className="bg-[var(--fill)] p-3.5 rounded-[12px] space-y-1">
            <div className="flex items-center justify-between text-[12px] text-[var(--text-3)]">
              <span className="font-normal">
                Total estimated civil budget
              </span>
              <span className="text-[11px] tabular-nums">Range: {formatINR(costEstimate.cost_range_min_inr)} – {formatINR(costEstimate.cost_range_max_inr)}</span>
            </div>
            <div className="text-[24px] font-bold text-[var(--text-1)] tabular-nums tracking-tight">
              {formatINR(costEstimate.total_estimated_cost_inr)}
            </div>
          </div>
        </>
      )}

      {/* Itemized Table with Hairline Rows */}
      <div className="divide-y divide-[var(--hairline)] border-y border-[var(--hairline)]">
        {costEstimate.breakdown.map((item, idx) => (
          <div key={idx} className="py-2.5 space-y-1.5 min-w-0 first:pt-1 last:pb-1">
            <div className="flex items-center justify-between gap-2 min-w-0">
              <span className="text-[13px] font-semibold text-[var(--text-1)] truncate">
                {item.category}
              </span>
              <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums shrink-0 whitespace-nowrap">
                {formatINR(item.amount_inr)}
              </span>
            </div>

            {/* 4px Progress Bar */}
            <div className="space-y-1">
              <div className="w-full bg-[var(--fill)] rounded-full h-1 overflow-hidden">
                <div
                  className="bg-[var(--accent)] h-full rounded-full transition-[width] duration-500"
                  style={{ width: `${Math.min(100, Math.max(0, item.percentage))}%` }}
                />
              </div>
              <div className="flex justify-between items-center text-[12px] text-[var(--text-3)]">
                <span className="truncate pr-2">{item.description}</span>
                <span className="tabular-nums font-semibold shrink-0">{item.percentage.toFixed(1)}%</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
