/**
 * AboutSection.tsx — Brand Positioning & Platform Architecture for BuildWise.
 * Uses an asymmetric 12-column editorial split: a lead architectural
 * specification panel (What is BuildWise? + What makes BuildWise different?)
 * paired with a 2x2 operational matrix for problem, users, AI CSP, and suite.
 */
import React from 'react';
import { motion } from 'framer-motion';
import { fadeRise, staggerParent, SETTLE_VIEWPORT } from './motion';
import { SectionHeading } from './SectionHeading';
import { ScrollRule } from './ScrollRule';
import { Icon } from '../components/Icon';
import type { IconName } from '../components/Icon';

interface OperationalPillar {
  index: string;
  title: string;
  meta: string;
  copy: string;
  highlight: string;
  specDetail: string;
  iconName: IconName;
}

const OPERATIONAL_PILLARS: ReadonlyArray<OperationalPillar> = [
  {
    index: '01',
    title: 'What problem does it solve?',
    meta: 'The Problem Solved',
    copy: 'Traditional pre-construction feasibility takes weeks of siloed GIS research, manual zoning cross-checks, and iterative CAD drafting. BuildWise eliminates pre-construction blindspots by revealing slope liabilities, seismic hazard zones, and flood stress before land acquisition or foundation design.',
    highlight: 'Pre-Purchase Feasibility',
    specDetail: 'MCDA · 100-Yr Discharge',
    iconName: 'shield-check',
  },
  {
    index: '02',
    title: 'Who is it built for?',
    meta: 'Target Users',
    copy: 'BuildWise is built for architects, civil engineers, general contractors, real estate developers, and individual land owners who need rapid, technically sound building plans, site analyses, and construction quantity takeoffs.',
    highlight: 'Architects, Engineers & Builders',
    specDetail: 'Multi-Role Workflows',
    iconName: 'sparkles',
  },
  {
    index: '03',
    title: 'How does AI assist construction planning?',
    meta: 'Spatial CSP',
    copy: 'AI operates as a spatial intelligence layer and constraint solver — interpreting natural-language client briefs, synthesizing room hierarchies, solving slicing-tree topologies for non-overlapping spaces, and verifying statutory setbacks and Vastu alignments without guessing numbers.',
    highlight: 'Constraint Satisfaction (CSP)',
    specDetail: 'Slicing-Tree Topology',
    iconName: 'cpu',
  },
  {
    index: '04',
    title: 'What features are available?',
    meta: 'Feature Suite',
    copy: 'The BuildWise Blueprint Generator creates dimensioned floor plans with room zoning and circulation. The platform also delivers elemental cost schedules (CPWD DSR 2023), multi-hazard environmental stress modeling, Vastu directional audits, and audit-ready PDF/SVG dossiers.',
    highlight: 'BuildWise Blueprint Generator',
    specDetail: 'Plans · Costs · Hazards · Dossiers',
    iconName: 'layers',
  },
];

const GROUNDING_FACTS: ReadonlyArray<{ code: string; scope: string }> = [
  { code: 'NBC 2016', scope: 'Setbacks, occupancy & ventilation' },
  { code: 'IS 1893:2016', scope: 'Seismic zone factor & lateral load' },
  { code: 'CPWD DSR', scope: 'Elemental rates & material takeoff' },
];

export const AboutSection: React.FC = () => (
  <section id="about" aria-label="About BuildWise" className="relative scroll-mt-24 py-8 md:py-16 lg:py-24">
    <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-10">
      <motion.div variants={staggerParent(0.06)} initial="hidden" whileInView="show" viewport={SETTLE_VIEWPORT}>
        <SectionHeading
          eyebrow="Platform Overview"
          title="From ideas to intelligent building plans"
          copy="BuildWise is an AI-powered construction planning and blueprint generation platform that pairs deterministic civil engineering code with algorithmic spatial layout synthesis."
        />
        <ScrollRule className="mt-5 md:mt-8" />

        <div className="mt-6 md:mt-8 grid grid-cols-1 gap-5 lg:grid-cols-12 lg:items-stretch min-w-0">
          {/* Lead Architectural Specification Sheet (5 cols) */}
          <motion.article
            variants={fadeRise}
            className="bw-surface lg:col-span-5 p-6 sm:p-7 flex flex-col justify-between rounded-[14px] min-w-0"
          >
            <div className="space-y-6">
              <div>
                <div className="flex items-center justify-between gap-3">
                  <span
                    aria-hidden
                    className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px] border border-bw-line-soft bg-bw-accent-tint text-bw-accent"
                  >
                    <Icon name="blueprint" size={19} strokeWidth={1.9} />
                  </span>
                  <span
                    className="font-mono text-[10.5px] font-semibold uppercase text-bw-accent-deep"
                    style={{ letterSpacing: '0.12em' }}
                  >
                    Platform Identity
                  </span>
                </div>
                <h3 className="mt-4 text-[19px] font-bold tracking-[-0.02em] text-bw-ink">
                  What is BuildWise?
                </h3>
                <p className="mt-2.5 text-[14.5px] leading-[1.65] text-bw-ink-2">
                  BuildWise is an AI-powered construction planning and blueprint generation platform. From a single map
                  pin or plot boundary, it synthesizes dimensioned building plans, elemental cost estimates, material
                  requirements, and site risk profiles in seconds.
                </p>
              </div>

              <div className="border-t border-bw-line-soft pt-6">
                <div className="flex items-center justify-between gap-3">
                  <span className="inline-flex items-center gap-2 text-[12px] font-semibold text-bw-ink">
                    <Icon name="zap" size={15} className="text-bw-accent" />
                    <span>Engineering Grounding</span>
                  </span>
                  <span
                    className="font-mono text-[10.5px] font-semibold uppercase text-bw-ink-2"
                    style={{ letterSpacing: '0.08em' }}
                  >
                    Zero Black Boxes
                  </span>
                </div>
                <h3 className="mt-2.5 text-[17px] font-bold tracking-[-0.015em] text-bw-ink">
                  What makes BuildWise different?
                </h3>
                <p className="mt-2 text-[14px] leading-[1.65] text-bw-ink-2">
                  Unlike generic generative AI tools that hallucinate unbuildable concepts, BuildWise grounds all
                  calculations in codified standards — National Building Code (NBC 2016), IS 1893:2016 seismic zoning,
                  and CPWD Delhi Schedule of Rates (DSR) with zero paid third-party map APIs.
                </p>
              </div>
            </div>

            <div className="mt-7 border-t border-bw-line-soft pt-4">
              <dl className="space-y-2.5">
                {GROUNDING_FACTS.map((fact) => (
                  <div key={fact.code} className="flex items-baseline justify-between gap-4 text-[12px]">
                    <dt className="font-mono font-semibold text-bw-ink shrink-0">{fact.code}</dt>
                    <dd className="text-right text-bw-ink-2 truncate">{fact.scope}</dd>
                  </div>
                ))}
              </dl>
              <div className="mt-4 pt-3 border-t border-bw-line-soft flex items-center justify-between gap-2 text-[11px]">
                <span className="font-medium text-bw-accent-deep">BuildWise AI Platform</span>
                <span className="font-mono text-bw-ink-2">Web · Desktop &amp; Field</span>
              </div>
            </div>
          </motion.article>

          {/* Operational Matrix (7 cols, 2x2) */}
          <div className="lg:col-span-7 grid grid-cols-1 gap-4 sm:grid-cols-2 min-w-0">
            {OPERATIONAL_PILLARS.map((pillar) => (
              <motion.article
                key={pillar.title}
                variants={fadeRise}
                className="bw-surface p-5 sm:p-6 flex flex-col justify-between rounded-[14px] min-w-0 w-full"
              >
                <div className="min-w-0">
                  <div className="flex items-center justify-between gap-2 min-w-0">
                    <span
                      aria-hidden
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] border border-bw-line-soft bg-bw-accent-tint text-bw-accent"
                    >
                      <Icon name={pillar.iconName} size={18} strokeWidth={1.9} />
                    </span>
                    <span
                      className="font-mono text-[10.5px] font-semibold uppercase text-bw-ink-2 text-right leading-tight min-w-0 truncate"
                      style={{ letterSpacing: '0.08em' }}
                    >
                      {pillar.index} · {pillar.meta}
                    </span>
                  </div>
                  <h3 className="mt-4 text-[16.5px] font-bold tracking-[-0.015em] text-bw-ink">
                    {pillar.title}
                  </h3>
                  <p className="mt-2 text-[13.5px] leading-[1.65] text-bw-ink-2">{pillar.copy}</p>
                </div>

                <div className="mt-5 pt-3 border-t border-bw-line-soft flex flex-col gap-1 text-[11px] min-w-0">
                  <span className="font-medium text-bw-accent-deep tracking-tight min-w-0">
                    {pillar.highlight}
                  </span>
                  <span className="font-mono text-bw-ink-2 font-medium min-w-0">{pillar.specDetail}</span>
                </div>
              </motion.article>
            ))}
          </div>
        </div>
      </motion.div>
    </div>
  </section>
);
