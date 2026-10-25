import React from 'react';
import type { AnalysisResponse } from '../../services/types';
import { Icon } from '../Icon';
import { isCriticalPlanWarning, page1PlanWarnings } from '../../services/planWarnings';

interface WarningsBannerProps {
  data: AnalysisResponse;
}

/**
 * Persistent banner listing every caveat on the report.
 *
 * It reads the same merged list the backend PDF banner renders, so the two
 * surfaces show an identical set of lines.  The list has two classes, and the
 * banner names them separately: page-1 plan disclosures (proportion, programme,
 * plinth, room bands) and data-degradation notices (fallbacks, stale guidance,
 * unavailable telemetry).  Counting all of them under one "Proportion /
 * programme non-compliance" headline overstated the plan's defects and hid the
 * provenance caveats.
 */
export const WarningsBanner: React.FC<WarningsBannerProps> = ({ data }) => {
  const warnings = data.warnings ?? [];
  if (warnings.length === 0) return null;

  const planWarnings = page1PlanWarnings(warnings);
  const planSet = new Set(planWarnings);
  const degradationWarnings = warnings
    .map((w) => String(w))
    .filter((w) => !planSet.has(w.trim()));

  // Refusal: a proportion/programme FAIL is drawn, not refused - so the banner
  // must be the loudest thing on the sheet when one is present.  It switches to
  // the red treatment and never hides the list behind a count.
  // ROOM-MIN / PLATE-SHORT are the named squeezed-room lines: a deficit with
  // only those (no PROP-HARD) still has to read as a FAIL, not an advisory.
  const critical = planWarnings.some((w) => isCriticalPlanWarning(String(w)));
  const tone = critical
    ? {
        section: 'bg-[var(--semantic-red)]/10 border-[var(--semantic-red)]',
        icon: 'text-[var(--semantic-red-ink)]',
        badge: 'text-[var(--semantic-red-ink)] bg-[var(--semantic-red)]/15',
        bullet: 'bg-[var(--semantic-red)]',
      }
    : {
        section: 'bg-[var(--semantic-amber)]/10 border-[var(--semantic-amber)]',
        icon: 'text-[var(--semantic-amber-ink)]',
        badge: 'text-[var(--semantic-amber-ink)] bg-[var(--semantic-amber)]/15',
        bullet: 'bg-[var(--semantic-amber)]',
      };
  const headline = planWarnings.length > 0 ? 'Plan warnings' : 'Data degradation notice';
  const headlineCount = planWarnings.length > 0 ? planWarnings.length : degradationWarnings.length;

  return (
    <section
      data-testid="warnings-banner"
      data-critical={critical ? 'true' : 'false'}
      data-plan-warning-count={planWarnings.length}
      data-degradation-count={degradationWarnings.length}
      aria-label="Plan and data warnings"
      aria-live="polite"
      className={`report-warnings-banner rounded-[12px] p-3.5 border-l-2 space-y-2 ${tone.section}`}
    >
      <div className="flex items-center gap-2">
        <Icon name="alert-triangle" size={15} className={`${tone.icon} shrink-0`} />
        <span className="text-[13px] font-semibold text-[var(--text-1)]">{headline}</span>
        <span className={`inline-flex items-center justify-center px-1.5 py-0.5 rounded-full text-[10px] font-bold tabular-nums min-w-[1.4rem] ${tone.badge}`}>
          {headlineCount}
        </span>
        {critical && (
          <span className="ml-auto inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-[var(--semantic-red)] text-white">
            FAIL stamp
          </span>
        )}
        {critical && (
          <p className="text-[11px] text-[var(--semantic-red-ink)] leading-snug pl-6">
            The plan is still drawn and exported with a FAIL stamp. The squeezed rooms are named
            individually below; refusal is reserved for statutory, egress and stacking failures.
          </p>
        )}
      </div>

      {planWarnings.length > 0 && (
        <ul data-testid="banner-plan-warnings" className="space-y-1.5 pl-6">
          {planWarnings.map((w, idx) => (
            <li key={idx} className="flex items-start gap-2 text-[12px] text-[var(--text-2)] leading-snug">
              <span aria-hidden="true" className={`mt-1.5 w-1 h-1 rounded-full shrink-0 ${tone.bullet}`} />
              <span>{w}</span>
            </li>
          ))}
        </ul>
      )}

      {degradationWarnings.length > 0 && (
        <div data-testid="banner-degradation-notice" className="pt-1.5 border-t border-[var(--hairline)] space-y-1.5">
          <div className="flex items-center gap-1.5 pl-0.5">
            <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-[var(--amber-ink,#b45309)]">
              Data degradation notice
            </span>
            <span className="inline-flex items-center justify-center px-1.5 py-0.5 rounded-full text-[10px] font-bold tabular-nums min-w-[1.4rem] bg-[var(--fill)] text-[var(--text-2)]">
              {degradationWarnings.length}
            </span>
          </div>
          <ul className="space-y-1.5 pl-6">
            {degradationWarnings.map((w, idx) => (
              <li key={idx} className="flex items-start gap-2 text-[12px] text-[var(--text-2)] leading-snug">
                <span aria-hidden="true" className="mt-1.5 w-1 h-1 rounded-full shrink-0 bg-[var(--semantic-amber)]" />
                <span>{w}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
};
