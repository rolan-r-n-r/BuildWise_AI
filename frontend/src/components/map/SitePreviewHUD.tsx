/**
 * SitePreviewHUD.tsx — glass HUD chips for the site preview.
 * ===================================================================
 * Sits over the map (bottom-right, mirrored from the BoundaryChip) and
 * surfaces the deterministic preview measurements with their annotation
 * statuses. ASSUMED badges must never read as CALCULATED (taxonomy rule).
 */
import React from 'react';
import { Icon } from '../Icon';
import { ANNOTATION_BADGE, type AnnotationStatus, type SitePreviewResponse } from '../../services/siteIntelligence';

function StatusPill({ status }: { status: AnnotationStatus }) {
  const badge = ANNOTATION_BADGE[status];
  return (
    <span
      className={`px-1.5 py-0.5 rounded-full text-[10px] font-semibold tracking-[0.06em] ${badge.className}`}
      title={`Annotation status: ${status}`}
    >
      {badge.label}
    </span>
  );
}

export interface SitePreviewHUDProps {
  preview: SitePreviewResponse | null;
  loading: boolean;
  error: string | null;
  onDismiss: () => void;
  onEditBoundary?: () => void;
}

export const SitePreviewHUD: React.FC<SitePreviewHUDProps> = ({
  preview,
  loading,
  error,
  onDismiss,
  onEditBoundary,
}) => {
  if (!preview && !loading && !error) return null;

  const setbacks = preview?.setbacks ?? {};
  const cert = preview?.certificate ?? {};

  return (
    <div
      data-testid="site-preview-hud"
      /*
       * The HUD is a property summary, so it must never slide under the left
       * parameters panel or clip its own dismiss control on a phone.
       *   • compact: pinned to both edges, above the boundary chip; the assisted
       *     bar yields once a plot exists (App).
       *   • desktop: bounded by both floating panels and right-aligned inside
       *     that band, never starting under the 340px sidebar.
       */
      className="absolute bottom-[118px] left-2 right-2 z-[999] pointer-events-none flex justify-end min-w-0 sm:bottom-[104px] sm:left-auto sm:right-3 lg:left-[364px] lg:right-[384px]"
      role="status"
      aria-label="Site preview measurements"
    >
      <div className="vibrancy-panel rounded-[14px] shadow-lg border border-[var(--panel-border-color)] px-2.5 sm:px-3 py-1.5 sm:py-2 pointer-events-auto w-fit max-w-full min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex items-center gap-1.5 text-[11px] font-semibold text-[var(--text-1)] shrink-0">
            <Icon name="layers" size={13} className="text-[var(--accent-ink)]" />
            <span>Site preview</span>
          </div>

          {loading && (
            <div className="flex items-center gap-2" aria-live="polite">
              <span className="h-4 w-16 rounded-full bg-[var(--fill)] animate-pulse" />
              <span className="h-4 w-20 rounded-full bg-[var(--fill)] animate-pulse" />
              <span className="h-4 w-14 rounded-full bg-[var(--fill)] animate-pulse" />
            </div>
          )}

          {!loading && error && (
            <span className="text-[11px] text-[var(--semantic-red-ink)] ui-font-tabular">{error}</span>
          )}

          {!loading && !error && preview && !preview.ok && (
            <span className="text-[11px] text-[var(--semantic-amber-ink)]">
              Site geometry unavailable for this boundary
            </span>
          )}

          {!loading && !error && preview && preview.ok && (
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="px-2 py-0.5 rounded-full bg-[var(--fill)] text-[10.5px] ui-font-tabular text-[var(--text-1)]">
                {preview.plot.area_sqm.toFixed(0)} m² plot
              </span>
              <span className="px-2 py-0.5 rounded-full bg-[var(--fill)] text-[10.5px] ui-font-tabular text-[var(--text-1)]">
                {preview.footprint.area_sqm.toFixed(0)} m² footprint
              </span>
              {typeof cert.ground_coverage_actual_pct === 'number' && (
                <span
                  className="px-2 py-0.5 rounded-full bg-[var(--fill)] text-[10.5px] ui-font-tabular text-[var(--text-1)]"
                  title={
                    typeof cert.ground_coverage_limit_pct === 'number'
                      ? `Footprint covers ${cert.ground_coverage_actual_pct.toFixed(1)}% of the plot; the max envelope coverage is ${cert.ground_coverage_limit_pct.toFixed(0)}%`
                      : 'Footprint area as a share of the plot area'
                  }
                >
                  {cert.ground_coverage_actual_pct.toFixed(0)}% of{' '}
                  {typeof cert.ground_coverage_limit_pct === 'number'
                    ? `${cert.ground_coverage_limit_pct.toFixed(0)}%`
                    : '—'}{' '}
                  max envelope coverage
                </span>
              )}
              <span className="px-2 py-0.5 rounded-full bg-[var(--fill)] text-[10.5px] ui-font-tabular text-[var(--text-2)]">
                SB {String(setbacks.front_m ?? '–')}/{String(setbacks.rear_m ?? '–')}/{String(setbacks.left_m ?? '–')} m
              </span>
              {typeof preview.parking.provided_ecs === 'number' && (
                <span className="px-2 py-0.5 rounded-full bg-[var(--fill)] text-[10.5px] ui-font-tabular text-[var(--text-1)]">
                  ECS {preview.parking.provided_ecs}/{preview.parking.required_ecs}
                </span>
              )}
              {preview.frontage && (
                <span className="flex items-center gap-1">
                  <span className="px-2 py-0.5 rounded-full bg-[var(--fill)] text-[10.5px] ui-font-tabular text-[var(--text-1)]">
                    Frontage P{preview.frontage.edge_index + 1}
                  </span>
                  <StatusPill status={preview.frontage.status} />
                </span>
              )}
              {preview.cached && (
                <span className="px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-[var(--fill)] text-[var(--text-3)]" title="Served from the deterministic hash cache">
                  CACHED
                </span>
              )}
            </div>
          )}

          <div className="flex items-center gap-1 ml-auto shrink-0">
            {onEditBoundary && (
              <button
                type="button"
                onClick={onEditBoundary}
                className="bw-touch-target w-6 h-6 rounded-[6px] bg-[var(--fill)] hover:bg-[var(--fill-hover)] text-[var(--text-2)] hover:text-[var(--text-1)] flex items-center justify-center cursor-pointer"
                title="Edit boundary on map"
                aria-label="Edit boundary on map"
              >
                <Icon name="edit" size={12} />
              </button>
            )}
            <button
              type="button"
              onClick={onDismiss}
              className="bw-touch-target w-6 h-6 rounded-[6px] bg-[var(--fill)] hover:bg-[var(--fill-hover)] text-[var(--text-2)] hover:text-[var(--text-1)] flex items-center justify-center cursor-pointer"
              title="Dismiss site preview"
              aria-label="Dismiss site preview"
            >
              <Icon name="x" size={12} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default SitePreviewHUD;
