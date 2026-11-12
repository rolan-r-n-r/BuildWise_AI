import React from 'react';
import type { SiteVisionResponse, PreservationRank } from '../services/types';
import { Icon } from './Icon';
import { Skeleton } from './report/Skeleton';
import { NDVI_DISCLOSURE } from './report/termDisclosures';

interface SiteVisionCardProps {
  data: SiteVisionResponse | null;
  isLoading: boolean;
  onScan: (modeOverride?: 'segformer' | 'index-only') => void;
  hasCoordinates: boolean;
  className?: string;
  layout?: 'stack' | 'grid';
}

export const SiteVisionCard: React.FC<SiteVisionCardProps> = ({
  data,
  isLoading,
  onScan,
  hasCoordinates,
  className = '',
  layout = 'stack',
}) => {
  const isGrid = layout === 'grid';
  // Rank badge styling helper (Sentence case & tinted only)
  const getRankBadge = (rank: PreservationRank) => {
    switch (rank) {
      case 'preserve':
        return {
          label: 'Preserve',
          badgeClass: 'bg-[var(--semantic-green)]/12 text-[var(--semantic-green-ink)]',
        };
      case 'compensate':
        return {
          label: 'Compensate',
          badgeClass: 'bg-[var(--semantic-amber)]/12 text-[var(--semantic-amber-ink)]',
        };
      case 'removable':
        return {
          label: 'Removable',
          badgeClass: 'bg-[var(--semantic-red)]/12 text-[var(--semantic-red-ink)]',
        };
      case 'context':
      default:
        return {
          label: 'Context',
          badgeClass: 'bg-[var(--fill)] text-[var(--text-2)]',
        };
    }
  };

  // SVG Circular Progress Ring Calculation
  const radius = 32;
  const circumference = 2 * Math.PI * radius;
  const rawPct =
    data && typeof data.green_cover_pct === 'number' && !isNaN(data.green_cover_pct)
      ? data.green_cover_pct
      : 0;
  const greenPct = Math.max(0, Math.min(100, rawPct));
  const strokeDashoffset = circumference - (greenPct / 100) * circumference;

  return (
    <div className={`bw-card rounded-[16px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)] p-4 space-y-4 w-full min-w-0 ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--hairline)] pb-2 min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <Icon name="satellite" size={15} className="text-[var(--text-2)] shrink-0" />
          <h3 className="inline-flex items-center gap-1.5 text-[14px] font-semibold text-[var(--text-1)] tracking-tight">
            Ecological Site Vision & Trees
            {NDVI_DISCLOSURE}
          </h3>
        </div>

        {/* Mode Badge */}
        {data && (
          <div className="flex items-center gap-1.5 shrink-0">
            {data.mode === 'segformer' && (
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-[var(--semantic-green)]/12 text-[var(--semantic-green-ink)]">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--semantic-green)]" />
                SegFormer B0
              </span>
            )}
            {data.mode === 'index-only' && (
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-[var(--semantic-amber)]/12 text-[var(--semantic-amber-ink)]">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--semantic-amber)]" />
                Index Only
              </span>
            )}
            {data.mode === 'unavailable' && (
              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-[var(--fill)] text-[var(--text-2)]">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--text-3)]" />
                Unavailable
              </span>
            )}
            {data.scene_metadata && data.mode !== 'unavailable' && (
              <span
                title={`Sentinel-2 scene ${data.scene_metadata.id} · ${data.scene_metadata.source}`}
                className="hidden sm:inline-flex items-center px-2 py-0.5 rounded-full bg-[var(--fill)] text-[10px] font-medium text-[var(--text-3)] tabular-nums whitespace-nowrap"
              >
                {data.scene_metadata.datetime.slice(0, 10)} · {data.scene_metadata.cloud_cover_pct.toFixed(0)}% cloud
              </span>
            )}
          </div>
        )}
      </div>

      {/* Loading State — Skeleton placeholder shaped like the loaded layout */}
      {isLoading && (
        <div className="space-y-3.5" aria-label="Analyzing satellite canopy and ecological inference">
          <div className="flex items-center gap-4 bg-[var(--fill)] rounded-[12px] p-3.5">
            <Skeleton className="w-16 h-16 rounded-full" label="Canopy cover loading" />
            <div className="flex-1 min-w-0 space-y-1.5">
              <Skeleton className="h-3.5 w-full" />
              <Skeleton className="h-3.5 w-3/4" />
              <Skeleton className="h-3.5 w-2/3" />
            </div>
          </div>
          <p className="text-[12px] text-[var(--text-2)] flex items-center gap-2">
            <span className="ios-spinner-16 shrink-0" aria-hidden="true" />
            Analyzing satellite canopy &amp; ecological inference…
          </p>
        </div>
      )}

      {/* Empty / Unscanned State */}
      {!isLoading && !data && (
        <div className="py-5 px-4 text-center bg-[var(--fill)] rounded-[12px] space-y-3">
          <div className="w-9 h-9 mx-auto rounded-full bg-[var(--accent-tint)] text-[var(--accent-ink)] flex items-center justify-center">
            <Icon name="tree" size={18} />
          </div>
          <div className="space-y-1 max-w-sm mx-auto">
            <h4 className="text-[13px] font-semibold text-[var(--text-1)]">
              Canopy & tree preservation analysis
            </h4>
            <p className="text-[12px] text-[var(--text-2)] leading-relaxed">
              Detect vegetation coverage, tree clusters, and environmental preservation requirements.
            </p>
          </div>
          <button
            type="button"
            onClick={() => onScan()}
            disabled={!hasCoordinates}
            className="inline-flex items-center gap-1.5 px-3.5 h-8 bg-[var(--accent)] hover:bg-[var(--accent-hover)] disabled:opacity-40 text-white rounded-full text-[12px] font-medium transition-ui cursor-pointer disabled:cursor-not-allowed shadow-sm"
          >
            <Icon name="satellite" size={13} />
            <span>Scan satellite canopy</span>
          </button>
        </div>
      )}

      {/* Unavailable Mode Card */}
      {!isLoading && data && data.mode === 'unavailable' && (
        <div className="space-y-2.5 bg-[var(--semantic-amber)]/10 border border-[var(--semantic-amber)]/20 rounded-[12px] p-3 text-[12px] text-[var(--text-1)]">
          <div className="flex items-start gap-2">
            <Icon name="alert-triangle" size={15} className="text-[var(--semantic-amber-ink)] shrink-0 mt-0.5" />
            <div className="space-y-1 min-w-0">
              <h4 className="font-semibold text-[var(--text-1)] text-[13px]">
                Satellite imagery temporarily unavailable
              </h4>
              <p className="text-[12px] text-[var(--text-2)] leading-relaxed">
                Cloud-free imagery could not be accessed within the latency budget. Feasibility scores remain valid.
              </p>
            </div>
          </div>
          <div className="flex justify-end pt-1">
            <button
              type="button"
              onClick={() => onScan()}
              className="inline-flex items-center gap-1 px-3 py-1 bg-[var(--fill)] hover:bg-[var(--fill-hover)] text-[var(--text-1)] rounded-full text-[12px] font-medium transition-colors"
            >
              <Icon name="refresh" size={12} />
              <span>Retry scan</span>
            </button>
          </div>
        </div>
      )}

      {/* Loaded Analysis Data */}
      {!isLoading && data && data.mode !== 'unavailable' && (
        <div className={isGrid ? 'grid grid-cols-1 md:grid-cols-2 gap-4 items-start' : 'space-y-3.5'}>
          {/* Left Column in Grid mode (Canopy Stats, Water Bodies, Latency) */}
          <div className="space-y-3.5 min-w-0">
            {/* Key-Value Rows with Ring Gauge */}
            <div className="flex items-center gap-4 bg-[var(--fill)] rounded-[12px] p-3.5">
              {/* SVG Circular Progress Ring */}
              <div className="relative w-16 h-16 shrink-0 flex items-center justify-center">
                <svg className="w-16 h-16 -rotate-90 block" viewBox="0 0 80 80">
                  <circle
                    cx="40"
                    cy="40"
                    r={radius}
                    stroke="var(--fill-hover)"
                    strokeWidth="6"
                    fill="transparent"
                  />
                  <circle
                    cx="40"
                    cy="40"
                    r={radius}
                    stroke="var(--semantic-green)"
                    strokeWidth="6"
                    strokeDasharray={circumference}
                    strokeDashoffset={strokeDashoffset}
                    strokeLinecap="round"
                    fill="transparent"
                    className="transition-[stroke-dashoffset] duration-700 ease-out"
                  />
                </svg>
                <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                  <span className="text-[14px] font-bold text-[var(--text-1)] tabular-nums leading-none">
                    {data.green_cover_pct.toFixed(0)}%
                  </span>
                  <span className="text-[10px] text-[var(--text-3)] font-normal mt-0.5">
                    Canopy
                  </span>
                </div>
              </div>

              {/* Key-Value Rows (No background micro-tiles) */}
              <div className="flex-1 min-w-0 divide-y divide-[var(--hairline)]">
                <div className="h-8 flex items-center justify-between">
                  <span className="text-[12px] font-normal text-[var(--text-2)]">Green canopy cover</span>
                  <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
                    {data.green_cover_pct.toFixed(1)}%
                  </span>
                </div>
                <div className="h-8 flex items-center justify-between">
                  <span className="text-[12px] font-normal text-[var(--text-2)]">Surface water cover</span>
                  <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
                    {data.water_cover_pct.toFixed(1)}%
                  </span>
                </div>
                <div className="h-8 flex items-center justify-between">
                  <span className="text-[12px] font-normal text-[var(--text-2)]">Built-up footprint</span>
                  <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
                    {data.built_up_pct.toFixed(1)}%
                  </span>
                </div>
                <div className="h-8 flex items-center justify-between">
                  <span className="text-[12px] font-normal text-[var(--text-2)]">Tree clusters detected</span>
                  <span className="text-[13px] font-semibold text-[var(--text-1)] tabular-nums whitespace-nowrap">
                    {data.tree_clusters?.features?.length ?? 0}
                  </span>
                </div>
              </div>
            </div>

            {/* Water Bodies Callout */}
            {data.water_bodies.features.length > 0 && (
              <div className="p-3 bg-[var(--accent-tint)]/40 rounded-[12px] text-[12px] space-y-1">
                <div className="flex items-center gap-1.5 text-[var(--text-1)] font-semibold">
                  <Icon name="droplet" size={13} className="text-[var(--accent-ink)] shrink-0" />
                  <span>Surface water detected on site</span>
                </div>
                <p className="text-[12px] text-[var(--text-2)] leading-relaxed">
                  {data.water_bodies.features.length} water feature
                  {data.water_bodies.features.length !== 1 ? 's' : ''} detected ({data.water_cover_pct.toFixed(1)}% cover). Maintain statutory drainage buffers.
                </p>
              </div>
            )}

            {/* Pipeline warnings (e.g. partial imagery / degraded segmentation) */}
            {data.warnings && data.warnings.length > 0 && (
              <div className="p-2.5 bg-[var(--semantic-amber)]/10 rounded-[10px] space-y-1 text-[11px] text-[var(--text-2)]">
                <div className="flex items-center gap-1.5 text-[var(--semantic-amber-ink)] font-medium">
                  <Icon name="alert-triangle" size={12} className="shrink-0" />
                  <span>Vision pipeline notes</span>
                </div>
                {data.warnings.map((w, idx) => (
                  <p key={idx} className="leading-snug">{w}</p>
                ))}
              </div>
            )}

            {/* Timing & Rescan Bar */}
            <div className="pt-2 border-t border-[var(--hairline)] flex items-center justify-between text-[11px] text-[var(--text-3)]">
              <span>
                {data.timing_ms?.total_ms || data.timing_ms?.total_pipeline_ms
                  ? `Latency: ${(((data.timing_ms.total_ms || data.timing_ms.total_pipeline_ms) as number) / 1000).toFixed(1)}s`
                  : 'Satellite scan complete'}
              </span>
              <button
                type="button"
                onClick={() => onScan()}
                className="text-[var(--accent-ink)] hover:underline transition-colors cursor-pointer font-medium"
              >
                Rescan satellite
              </button>
            </div>
          </div>

          {/* Right Column in Grid mode (Tree Preservation Plan List) */}
          <div className="space-y-2 min-w-0">
            <div className="flex items-center justify-between text-[12px] min-w-0">
              <div className="flex items-center gap-1.5 font-semibold text-[var(--text-1)]">
                <Icon name="tree" size={13} className="text-[var(--semantic-green-ink)] shrink-0" />
                <span>Tree preservation plan</span>
                <span className="text-[11px] font-normal text-[var(--text-3)]">
                  ({data.preservation_plan.length} cluster{data.preservation_plan.length !== 1 ? 's' : ''})
                </span>
              </div>
              <span className="text-[11px] text-[var(--text-3)] font-mono">analysis window</span>
            </div>

            {data.preservation_plan.length === 0 ? (
              <div className="p-3 bg-[var(--fill)] rounded-[10px] text-center text-[12px] text-[var(--text-2)]">
                No significant tree clusters (≥ 25 m²) detected on the surveyed plot.
              </div>
            ) : (
              <div className="divide-y divide-[var(--hairline)]">
                {data.preservation_plan.map((item) => {
                  const badge = getRankBadge(item.rank);
                  return (
                    <div
                      key={item.cluster_id}
                      className="py-2.5 space-y-1 text-[12px] min-w-0 first:pt-0"
                    >
                      <div className="flex items-center justify-between gap-1">
                        <div className="flex items-center gap-1.5 min-w-0">
                          <span className="font-semibold text-[var(--text-1)] font-mono text-[11px]">
                            {item.cluster_id}
                          </span>
                          <span
                            className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${badge.badgeClass}`}
                          >
                            {badge.label}
                          </span>
                        </div>
                        <div className="flex items-center gap-2 text-[11px] font-mono text-[var(--text-2)] shrink-0">
                          <span>
                            Area: <b className="text-[var(--text-1)] font-medium">{item.area_sqm} m²</b>
                          </span>
                          <span className="inline-flex items-center gap-1">
                            NDVI: <b className="text-[var(--text-1)] font-medium">{item.mean_ndvi.toFixed(2)}</b>
                            {NDVI_DISCLOSURE}
                          </span>
                        </div>
                      </div>

                      <div className="flex items-center gap-1.5 text-[11px]">
                        {item.overlap_footprint ? (
                          <span className="inline-flex items-center gap-1 text-[var(--semantic-red-ink)] font-medium">
                            <Icon name="alert-triangle" size={11} className="shrink-0" />
                            Overlaps proposed building footprint
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-[var(--semantic-green-ink)] font-medium">
                            <Icon name="check-circle" size={11} className="shrink-0" />
                            Clear of building footprint
                          </span>
                        )}
                      </div>

                      <p className="text-[12px] text-[var(--text-2)] leading-relaxed break-words">
                        {item.action}
                      </p>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
