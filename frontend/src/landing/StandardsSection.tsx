/**
 * StandardsSection.tsx — what the engine implements, and on what data.
 * Renders the three provenance groups from landing/standards.ts inside
 * structured specification panels, paired with the Survey Datum Bearing dial
 * and the verbatim certification definition.
 */
import React, { useRef } from 'react';
import { motion } from 'framer-motion';
import { fadeRise, fadeRiseTight, staggerParent, SETTLE_VIEWPORT } from './motion';
import { SectionHeading } from './SectionHeading';
import { ScrollRule } from './ScrollRule';
import { Bearing } from './Bearing';
import { useDampedScrub, useOnScreen } from './interaction';
import { GROUP_LABELS, GROUP_ORDER, sourcesIn, type Source, type SourceGroup } from './standards';
import { CERTIFIED_DEFINITION } from '../components/report/statusTaxonomy';
import { Icon } from '../components/Icon';
import type { IconName } from '../components/Icon';

const GROUP_META: Record<SourceGroup, { icon: IconName; unit: string; toneClass: string }> = {
  standards: {
    icon: 'shield-check',
    unit: 'codes',
    toneClass: 'bg-bw-green-tint text-bw-green-ink',
  },
  siteData: {
    icon: 'activity',
    unit: 'datasets',
    toneClass: 'bg-bw-accent-tint text-bw-accent',
  },
  imagery: {
    icon: 'satellite',
    unit: 'layers',
    toneClass: 'bg-bw-accent-tint text-bw-accent',
  },
};

const SpecPanel: React.FC<{ group: SourceGroup; rows: ReadonlyArray<Source>; wideTablet?: boolean }> = ({
  group,
  rows,
  wideTablet = false,
}) => {
  const meta = GROUP_META[group];
  return (
    <motion.div
      variants={fadeRise}
      className={`bw-surface flex flex-col rounded-[14px] p-5 sm:p-6 min-w-0 ${
        wideTablet ? 'md:col-span-2 min-[1200px]:col-span-1' : ''
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 pb-4 border-b border-bw-line-soft">
        <div className="flex items-center gap-2.5 min-w-0">
          <span
            aria-hidden
            className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px] border border-bw-line-soft ${meta.toneClass}`}
          >
            <Icon name={meta.icon} size={16} strokeWidth={1.9} />
          </span>
          <h3
            className="text-[11px] font-semibold uppercase text-bw-ink"
            style={{ letterSpacing: '0.12em' }}
          >
            {GROUP_LABELS[group]}
          </h3>
        </div>
        <span className="font-mono text-[10.5px] text-bw-ink-2 shrink-0">
          {rows.length} {meta.unit}
        </span>
      </div>

      <dl
        className={`mt-1 divide-y divide-bw-line-soft ${
          wideTablet ? 'md:grid md:grid-cols-2 md:gap-x-6 md:divide-y-0 min-[1200px]:block min-[1200px]:divide-y' : ''
        }`}
      >
        {rows.map((row) => (
          <motion.div
            key={row.name}
            variants={fadeRiseTight}
            className={`py-3.5 px-2 rounded-[8px] transition-colors duration-150 hover:bg-bw-porcelain ${
              wideTablet ? 'md:border-b md:border-bw-line-soft min-[1200px]:border-b-0' : ''
            }`}
          >
            <dt className="flex items-baseline justify-between gap-2 text-[14px] font-semibold text-bw-ink">
              <span className="min-w-0">{row.name}</span>
              <span className="font-mono text-[10px] font-medium uppercase text-bw-ink-3 shrink-0">{row.short}</span>
            </dt>
            <dd className="mt-1 text-[13px] leading-[1.5] text-bw-ink-2">{row.role}</dd>
            <dd className="mt-1.5 font-mono text-[11px] leading-[1.45] text-bw-ink-3">{row.credit}</dd>
          </motion.div>
        ))}
      </dl>
    </motion.div>
  );
};

export const StandardsSection: React.FC = () => {
  const sectionRef = useRef<HTMLDivElement>(null);
  const onScreen = useOnScreen(sectionRef);
  const entry = useDampedScrub(sectionRef, { enabled: onScreen, tau: 0.13 });

  return (
    <section id="standards" aria-label="Standards and data sources" className="scroll-mt-24 py-8 md:py-16 lg:py-24">
      <div ref={sectionRef} className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-10">
        <motion.div variants={staggerParent(0.08)} initial="hidden" whileInView="show" viewport={SETTLE_VIEWPORT}>
          <div className="flex items-start justify-between gap-10">
            <div className="min-w-0">
              <SectionHeading
                eyebrow="Standards and data"
                title="Grounded in code and named sources"
                copy="Every figure in a dossier traces back to a published standard or a named dataset. Nothing is a black box, and nothing is behind a paid key."
              />
            </div>
            <div className="hidden w-[152px] shrink-0 md:block lg:w-[clamp(152px,15vw,200px)]">
              <Bearing
                progress={entry}
                sweep={-58}
                counterSweep={108}
                bearing={189}
                caption="Survey datum"
                footnote="IS 1893 · NBC 2016"
                dialOpacity={0.78}
                className="text-bw-accent"
              />
            </div>
          </div>

          <ScrollRule className="mt-5 md:mt-8" />

          {/* Verbatim certification definition strip */}
          <motion.div
            variants={fadeRise}
            className="mt-6 rounded-[12px] border border-bw-line-soft bg-bw-surface px-4 py-3.5 sm:px-5"
            style={{ boxShadow: 'var(--bw-shadow-1)' }}
          >
            <div className="flex items-start gap-3">
              <span
                aria-hidden
                className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-[8px] bg-bw-green-tint text-bw-green-ink"
              >
                <Icon name="badge-check" size={15} strokeWidth={2} />
              </span>
              <div className="min-w-0">
                <p
                  className="font-mono text-[10.5px] font-semibold uppercase text-bw-ink"
                  style={{ letterSpacing: '0.12em' }}
                >
                  Certification Rule Taxonomy
                </p>
                <p
                  data-testid="landing-certified-definition"
                  className="mt-1 text-[12.5px] leading-[1.6] text-bw-ink-2"
                >
                  {CERTIFIED_DEFINITION}
                </p>
              </div>
            </div>
          </motion.div>

          <div className="mt-6 grid grid-cols-1 gap-5 md:grid-cols-2 min-[1200px]:grid-cols-3">
            {GROUP_ORDER.map((group) => (
              <SpecPanel key={group} group={group} rows={sourcesIn(group)} wideTablet={group === 'imagery'} />
            ))}
          </div>

          <motion.p variants={fadeRise} className="mt-5 md:mt-8 text-[13px] leading-[1.6] text-bw-ink-3">
            Attribution travels with the data: the map carries its own basemap credits, and every
            dossier carries a data sources panel.
          </motion.p>
        </motion.div>
      </div>
    </section>
  );
};
