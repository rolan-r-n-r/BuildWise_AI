import React, { useState, useEffect, useId } from 'react';
import type { LandValueEstimate } from '../services/types';
import { Icon } from './Icon';
import { Skeleton } from './report/Skeleton';
import { formatIN } from '../services/numberFormat';

interface LandValueCardProps {
  landValue: LandValueEstimate;
  civilTotalCostInr: number;
  onOverrideChange?: (rate: number | null, plotArea: number | null) => void;
}

export const LandValueCard: React.FC<LandValueCardProps> = ({
  landValue,
  civilTotalCostInr,
  onOverrideChange,
}) => {
  const [overrideRate, setOverrideRate] = useState<string>(
    landValue.is_user_override && landValue.indicative_rate_per_sqft
      ? String(landValue.indicative_rate_per_sqft)
      : ''
  );
  const [overrideArea, setOverrideArea] = useState<string>('');
  // This card renders in more than one place (sheet + panel), so the override
  // inputs need instance-unique ids: hardcoded ones duplicated in the DOM and
  // broke the label/control association for assistive tech.
  const fieldId = useId();
  const rateId = `${fieldId}-rate`;
  const areaId = `${fieldId}-area`;
  // True while the debounced recomputation of the derived totals is pending —
  // the affected figures show a Skeleton rather than a stale value.
  const [isPending, setIsPending] = useState(false);

  useEffect(() => {
    const handler = setTimeout(() => {
      const parsedRate = overrideRate.trim() ? parseFloat(overrideRate) : null;
      const parsedArea = overrideArea.trim() ? parseFloat(overrideArea) : null;
      if (onOverrideChange) {
        onOverrideChange(
          parsedRate && !isNaN(parsedRate) && parsedRate > 0 ? parsedRate : null,
          parsedArea && !isNaN(parsedArea) && parsedArea > 0 ? parsedArea : null
        );
      }
      setIsPending(false);
    }, 300);

    return () => clearTimeout(handler);
  }, [overrideRate, overrideArea, onOverrideChange]);

  const numOverrideRate = overrideRate.trim() ? parseFloat(overrideRate) : null;
  const numOverrideArea = overrideArea.trim() ? parseFloat(overrideArea) : null;

  const isUserSupplied = Boolean(
    (numOverrideRate && !isNaN(numOverrideRate)) || (numOverrideArea && !isNaN(numOverrideArea))
  );

  const effectiveRate = numOverrideRate && !isNaN(numOverrideRate)
    ? numOverrideRate
    : (landValue.indicative_rate_per_sqft ?? null);

  // A guidance-table miss returns a null rate - "Not valued",
  // never a fabricated ₹0/sq ft that reads as a real valuation.
  const isRateKnown = effectiveRate !== null && effectiveRate > 0;

  const plotArea = numOverrideArea && !isNaN(numOverrideArea)
    ? numOverrideArea
    : (landValue.plot_area_sqft ?? 0);

  const landCost = isRateKnown && plotArea > 0 ? Math.round((effectiveRate as number) * plotArea) : null;
  const combinedTotal = landCost !== null ? civilTotalCostInr + landCost : null;

  const formatInr = (val: number) => {
    if (val >= 10000000) {
      return `₹${(val / 10000000).toFixed(2)} Cr`;
    } else if (val >= 100000) {
      return `₹${(val / 100000).toFixed(2)} Lakh`;
    }
    return `₹${formatIN(val)}`;
  };

  const sourceLabel =
    landValue.source_publication ||
    landValue.jurisdiction_zone ||
    (isRateKnown ? 'SRO valuation baseline' : 'No guidance table match');

  // Plot-area provenance (audit F07): the same number the hero tile prints,
  // and the basis it came from - never assumed to be a captured boundary.
  const plotAreaBasis =
    landValue.plot_area_source === 'captured_boundary'
      ? `captured boundary${
          landValue.boundary_area_sqft != null
            ? ` (${formatIN(Math.round(landValue.boundary_area_sqft))} sq ft)`
            : ''
        }`
      : landValue.plot_area_source === 'client_plot_area'
      ? 'client-supplied area'
      : landValue.plot_area_source === 'derived_from_coverage'
      ? 'derived from built-up ÷ coverage'
      : 'source not stated';

  return (
    <div className="bw-card rounded-[16px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)] p-4 space-y-3.5 w-full min-w-0">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--hairline)] pb-2 min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <Icon name="currency-rupee" size={15} className="text-[var(--text-2)] shrink-0" />
          <h3 className="text-[14px] font-semibold text-[var(--text-1)] tracking-tight">
            Indicative Land Valuation & Budget
          </h3>
        </div>
        <span
          className={`px-2.5 py-0.5 rounded-full text-[11px] font-medium shrink-0 ${
            isRateKnown || isUserSupplied
              ? 'bg-[var(--fill)] text-[var(--text-1)]'
              : 'bg-[var(--fill)] text-[var(--text-3)] border border-dashed border-[var(--hairline)]'
          }`}
        >
          {isUserSupplied ? 'Custom override' : isRateKnown ? 'SRO baseline' : 'Not valued'}
        </span>
      </div>

      {/* Combined Project Total Banner */}
      <div className="bg-[var(--fill)] p-3.5 rounded-[12px] space-y-1">
        <div className="flex items-center justify-between text-[12px] text-[var(--text-3)]">
          <span className="font-normal">Combined project total</span>
          <span className="text-[11px]">Civil + Land budget</span>
        </div>
        {isPending ? (
          <Skeleton className="h-7 w-36" label="Updating combined project total" />
        ) : (
          <div className="text-[24px] font-bold text-[var(--text-1)] tabular-nums tracking-tight">
            {combinedTotal !== null ? formatInr(combinedTotal) : '—'}
          </div>
        )}
      </div>

      {/* Key-Value Rows (No 2-column tile pair) */}
      <div className="divide-y divide-[var(--hairline)] border-y border-[var(--hairline)]">
        <div className="h-10 flex items-center justify-between px-0.5">
          <span className="text-[13px] font-normal text-[var(--text-2)]">Indicative land rate</span>
          {isRateKnown ? (
            <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
              ₹{formatIN(effectiveRate as number)}/sq ft
            </span>
          ) : (
            <span
              className="text-[13px] font-semibold text-[var(--text-3)] italic whitespace-nowrap"
              title="No state guidance circle rate matched for this jurisdiction — enter a manual override"
            >
              Not valued
            </span>
          )}
        </div>
        <div className="h-10 flex items-center justify-between px-0.5">
          <span className="text-[13px] font-normal text-[var(--text-2)]">Estimated land cost</span>
          {isPending ? (
            <Skeleton className="h-4 w-24" label="Updating estimated land cost" />
          ) : (
            <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
              {landCost !== null ? formatInr(landCost) : '—'}
            </span>
          )}
        </div>
        <div className="h-10 flex items-center justify-between px-0.5">
          <span className="text-[13px] font-normal text-[var(--text-2)]">Locality multiplier</span>
          <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
            {(landValue.locality_multiplier ?? 1.0).toFixed(2)}x
          </span>
        </div>
        {landValue.base_table_rate_per_sqft != null && (
          <div className="h-10 flex items-center justify-between px-0.5">
            <span className="text-[13px] font-normal text-[var(--text-2)]">Published table rate</span>
            <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
              ₹{formatIN(landValue.base_table_rate_per_sqft)}/sq ft
            </span>
          </div>
        )}
        <div className="h-10 flex items-center justify-between px-0.5">
          <span className="text-[13px] font-normal text-[var(--text-2)]">Civil construction cost</span>
          <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
            {formatInr(landValue.construction_cost_inr)}
          </span>
        </div>
        {landValue.as_of_year != null && (
          <div className="h-10 flex items-center justify-between px-0.5">
            <span className="text-[13px] font-normal text-[var(--text-2)]">Valuation as of</span>
            <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
              {landValue.as_of_year}
            </span>
          </div>
        )}
      </div>

      {/* Locality multiplier provenance: how the road + facility scores compose. */}
      {landValue.multiplier_breakdown && (
        <details className="text-[11px] text-[var(--text-3)]">
          <summary className="cursor-pointer text-[11px] font-medium text-[var(--accent-ink)] hover:underline select-none inline-flex items-center gap-1">
            <Icon name="info" size={11} className="shrink-0" />
            Locality multiplier breakdown
          </summary>
          <div className="mt-1.5 space-y-1 pl-1">
            <div className="flex items-center justify-between gap-2">
              <span>Road accessibility ({landValue.multiplier_breakdown.road_accessibility_score.toFixed(0)}/100)</span>
              <span className="font-mono tabular-nums">{landValue.multiplier_breakdown.road_contribution.toFixed(3)}x</span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span>Facility proximity ({landValue.multiplier_breakdown.facility_proximity_score.toFixed(0)}/100)</span>
              <span className="font-mono tabular-nums">{landValue.multiplier_breakdown.facility_contribution.toFixed(3)}x</span>
            </div>
            <div className="flex items-center justify-between gap-2 font-semibold text-[var(--text-2)]">
              <span>Net multiplier{landValue.multiplier_breakdown.is_clamped ? ' (clamped)' : ''}</span>
              <span className="font-mono tabular-nums">{landValue.multiplier_breakdown.net_multiplier.toFixed(2)}x</span>
            </div>
          </div>
        </details>
      )}

      {/* Interactive Override Inputs */}
      <div className="p-3 bg-[var(--fill)] rounded-[12px] space-y-2">
        <span className="text-[12px] font-normal text-[var(--text-3)] block">
          Custom parameter overrides
        </span>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label htmlFor={rateId} className="text-[11px] text-[var(--text-3)] block mb-1">
              Custom rate (₹/sq ft)
            </label>
            <input
              id={rateId}
              type="number"
              placeholder={isRateKnown ? String(effectiveRate) : ''}
              value={overrideRate}
              onChange={(e) => {
                setOverrideRate(e.target.value);
                setIsPending(true);
              }}
              className="w-full h-8 bg-[var(--fill)] hover:bg-[var(--fill-hover)] border-0 rounded-[8px] px-2.5 text-[12px] font-mono text-[var(--text-1)] outline-none focus:ring-[2px] focus:ring-[var(--accent)]/30"
            />
          </div>
          <div>
            <label htmlFor={areaId} className="text-[11px] text-[var(--text-3)] block mb-1">
              Plot area (sq ft)
            </label>
            <input
              id={areaId}
              type="number"
              placeholder={plotArea > 0 ? String(plotArea) : ''}
              value={overrideArea}
              onChange={(e) => {
                setOverrideArea(e.target.value);
                setIsPending(true);
              }}
              className="w-full h-8 bg-[var(--fill)] hover:bg-[var(--fill-hover)] border-0 rounded-[8px] px-2.5 text-[12px] font-mono text-[var(--text-1)] outline-none focus:ring-[2px] focus:ring-[var(--accent)]/30"
            />
          </div>
        </div>
      </div>

      {/* Plot-area basis + any physical reconciliation warning */}
      <div
        className="text-[11px] text-[var(--text-3)] flex items-baseline justify-between gap-2 min-w-0"
        data-testid="plot-area-basis"
      >
        <span className="shrink-0">Plot area basis</span>
        <span className="text-[var(--text-2)] truncate" title={plotAreaBasis}>
          {plotAreaBasis}
        </span>
      </div>
      {landValue.plot_area_warnings?.map((warning) => (
        <div
          key={warning}
          className="p-2.5 rounded-[10px] bg-amber-500/10 border border-amber-500/20 text-[11px] text-[var(--semantic-amber-ink)] leading-snug"
          data-testid="plot-area-warning"
        >
          {warning}
        </div>
      ))}

      {/* Confidence Disclosure (staleness / table miss) - never silently dropped */}
      {landValue.confidence_warning && (
        <div className="p-3 bg-[var(--fill)] rounded-[12px] text-[12px] text-[var(--text-2)] space-y-1">
          <div className="flex items-center gap-1.5 text-[var(--semantic-amber-ink)] font-medium">
            <Icon name="alert-triangle" size={13} />
            <span>Valuation confidence note</span>
          </div>
          <p className="leading-normal">{landValue.confidence_warning}</p>
        </div>
      )}

      {/* Valuation Source */}
      <div className="pt-2 border-t border-[var(--hairline)] flex items-center justify-between text-[11px] text-[var(--text-3)]">
        <span>Valuation baseline</span>
        <span className="text-[var(--text-2)] truncate max-w-[200px]" title={sourceLabel}>{sourceLabel}</span>
      </div>
    </div>
  );
};
