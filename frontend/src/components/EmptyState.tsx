import React from 'react';
import { Icon } from './Icon';

/**
 * EmptyState — the first page of the site dossier.
 *
 * This panel used to be four icon rows in a bordered list: a generic dashboard
 * card stack, and the heaviest visual object on a screen whose actual subject
 * was the map behind it. It is now set like the front matter of a technical
 * document — a small register line, a heading, and a numbered method — so the
 * eye reads sequence rather than ornament. The copy is unchanged; the steps are
 * the same four the funnel performs.
 */
export const EmptyState: React.FC = () => {
  const steps = [
    {
      title: 'Geographic Site Selection',
      desc: 'Click on the interactive map canvas to drop a pin or enter coordinates manually.',
    },
    {
      title: 'Structural Specifications',
      desc: 'Set the target built-up plinth area, specification grade tier, and level storeys.',
    },
    {
      title: 'Deterministic Engine Analysis',
      desc: 'Computes multi-factor terrain slope, drainage, bioclimatic orientation, and CPWD costs.',
    },
    {
      title: 'Engineering Synthesis & PDF',
      desc: 'Review solar-wind vectors, hazard telemetry, and export official vector PDF reports.',
    },
  ];

  return (
    <div className="w-full min-w-0 py-1" data-testid="dossier-empty-state">
      <div className="flex items-center justify-between gap-2 border-b border-[var(--hairline)] pb-2">
        <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--text-3)]">
          Site dossier
        </span>
        <span className="text-[10px] font-medium uppercase tracking-[0.08em] text-[var(--text-3)]">
          No active study
        </span>
      </div>

      <div className="pt-4 pb-5">
        <h3 className="text-[19px] font-semibold leading-[1.2] tracking-[-0.02em] text-[var(--text-1)]">
          Site Feasibility &amp; Planning
        </h3>
        <p className="mt-2 max-w-[30ch] text-[12.5px] leading-[1.55] text-[var(--text-2)]">
          Drop a pin anywhere on the map or input coordinates to evaluate terrain, passive
          orientation, and preliminary budgets.
        </p>
      </div>

      <ol className="border-t border-[var(--hairline)]">
        {steps.map((step, idx) => (
          <li
            key={step.title}
            className="grid grid-cols-[2.25rem_minmax(0,1fr)] gap-x-2 border-b border-[var(--hairline)] py-3"
          >
            <span className="ui-font-tabular pt-px text-[10.5px] font-medium leading-[1.5] text-[var(--text-3)]">
              {String(idx + 1).padStart(2, '0')}
            </span>
            <div className="min-w-0">
              <span className="block text-[12.5px] font-semibold leading-tight text-[var(--text-1)]">
                {step.title}
              </span>
              <p className="mt-1 text-[11.5px] leading-[1.5] text-[var(--text-2)]">{step.desc}</p>
            </div>
          </li>
        ))}
      </ol>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pt-3 text-[10.5px] text-[var(--text-3)]">
        <span className="inline-flex items-center gap-1">
          <Icon name="shield-check" size={12} className="shrink-0" />
          CPWD &amp; IS 1893 Benchmarks
        </span>
        <span className="text-[var(--hairline)]" aria-hidden="true">
          /
        </span>
        <span className="inline-flex items-center gap-1">
          <Icon name="badge-check" size={12} className="shrink-0" />
          Zero Paid APIs
        </span>
      </div>
    </div>
  );
};
