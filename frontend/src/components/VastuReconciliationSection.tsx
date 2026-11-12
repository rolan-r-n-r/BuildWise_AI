import React from 'react';
import type { ReconciliationItem } from '../services/types';
import { Icon } from './Icon';

interface VastuReconciliationSectionProps {
  notes: ReconciliationItem[];
  className?: string;
}

export const VastuReconciliationSection: React.FC<VastuReconciliationSectionProps> = ({
  notes,
  className = '',
}) => {
  if (!notes || notes.length === 0) return null;

  return (
    <section
      data-report-section="reconciliation"
      id="sec-reconciliation"
      aria-label="Vastu and building physics reconciliation"
      className={`w-full min-w-0 ${className}`}
    >
      <div className="bw-card rounded-[16px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)] p-4 sm:p-[18px] space-y-3.5 w-full min-w-0">
        {/* Section Header */}
        <div className="flex items-center justify-between border-b border-[var(--hairline)] pb-2.5 min-w-0">
          <div className="flex items-center gap-2 min-w-0">
            <Icon name="sliders" size={15} className="text-[var(--text-2)] shrink-0" />
            <h3 className="text-[14px] font-semibold text-[var(--text-1)] tracking-tight">
              Vastu &amp; Building Physics Reconciliation
            </h3>
          </div>
          <span className="text-[11px] text-[var(--text-3)] tabular-nums shrink-0">
            {notes.length} evaluated {notes.length === 1 ? 'item' : 'items'}
          </span>
        </div>

        <p className="text-[12px] text-[var(--text-2)] leading-normal -mt-1">
          Synthesis of traditional Vedic directional guidelines with bioclimatic solar, thermal and aerodynamic physics.
        </p>

        {/* Responsive Grid: 2 columns on desktop/tablet, 1 column on mobile */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 sm:gap-3.5">
          {notes.map((item, idx) => {
            const isConcordant = item.status === 'concordant';
            return (
              <div
                key={idx}
                className="rounded-[12px] bg-[var(--fill)] border border-[var(--hairline)] p-3.5 sm:p-4 flex flex-col justify-between space-y-2.5 min-w-0"
              >
                <div className="space-y-2 min-w-0">
                  {/* Topic and Status Badge */}
                  <div className="flex items-start justify-between gap-2 min-w-0">
                    <h4 className="text-[13px] font-semibold text-[var(--text-1)] tracking-tight leading-snug">
                      {item.topic}
                    </h4>
                    <span
                      className={`text-[11px] font-semibold px-2.5 py-0.5 rounded-full capitalize shrink-0 border ${
                        isConcordant
                          ? 'bg-[var(--semantic-green)]/15 text-[var(--semantic-green-ink)] border-[var(--semantic-green)]/30'
                          : 'bg-[var(--semantic-amber)]/15 text-[var(--semantic-amber-ink)] border-[var(--semantic-amber)]/30'
                      }`}
                    >
                      {item.status}
                    </span>
                  </div>

                  {/* Position Comparison Pills */}
                  <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-[var(--accent-tint)] text-[var(--accent-ink)] font-medium">
                      Vastu: {item.vastu_position}
                    </span>
                    <span className="text-[var(--text-3)] select-none" aria-hidden="true">
                      /
                    </span>
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-[var(--card-bg-subtle)] border border-[var(--hairline)] text-[var(--text-2)] font-medium">
                      Science: {item.scientific_passive_position}
                    </span>
                    <span className="text-[var(--text-3)] select-none" aria-hidden="true">
                      →
                    </span>
                    <span className="text-[11px] font-semibold text-[var(--text-2)]">
                      {isConcordant ? 'Harmonized' : 'Compromise'}
                    </span>
                  </div>
                </div>

                {/* Synthesis Description */}
                <p className="text-[12px] text-[var(--text-2)] leading-relaxed pt-2 border-t border-[var(--hairline)]">
                  {item.recommended_synthesis}
                </p>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
};

