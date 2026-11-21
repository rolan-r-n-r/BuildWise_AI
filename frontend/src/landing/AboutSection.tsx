/**
 * AboutSection.tsx — Brand Positioning & Platform Architecture for BuildWise.
 * Addresses the 6 foundational questions for new visitors and search engines:
 *   1. What is BuildWise? (AI-Powered Construction Planning and Blueprint Generation Platform).
 *   2. What problem does it solve? (Pre-construction uncertainty, manual drafting delays, structural/cost surprises).
 *   3. Who should use it? / Who is it built for? (Architects, civil engineers, builders, property developers, landowners).
 *   4. What makes BuildWise different? (Deterministic civil code compliance: NBC 2016, IS 1893, CPWD DSR; zero paid APIs).
 *   5. How does AI assist construction planning? (Spatial constraint reasoning, room program synthesis, topological invariants).
 *   6. What features are available? (BuildWise Blueprint Generator, Cost Benchmarks, Hazard Modeling, Vastu, Vector Dossier).
 */
import React from 'react';
import { motion } from 'framer-motion';
import { fadeRise, staggerParent, SETTLE_VIEWPORT } from './motion';
import { SectionHeading } from './SectionHeading';
import { ScrollRule } from './ScrollRule';
import { Icon } from '../components/Icon';
import type { IconName } from '../components/Icon';

interface ValuePillar {
  title: string;
  meta: string;
  copy: string;
  highlight: string;
  specDetail: string;
  iconName: IconName;
}

const PILLARS: ReadonlyArray<ValuePillar> = [
  {
    title: 'What is BuildWise?',
    meta: 'Platform Identity',
    copy: 'BuildWise is an AI-powered construction planning and blueprint generation platform. From a single map pin or plot boundary, it synthesizes dimensioned building plans, elemental cost estimates, material requirements, and site risk profiles in seconds.',
    highlight: 'BuildWise AI Platform',
    specDetail: 'Web Platform · Desktop & Field',
    iconName: 'blueprint',
  },
  {
    title: 'What problem does it solve?',
    meta: 'The Problem Solved',
    copy: 'Traditional pre-construction feasibility takes weeks of siloed GIS research, manual zoning cross-checks, and iterative CAD drafting. BuildWise eliminates pre-construction blindspots by revealing slope liabilities, seismic hazard zones, and flood stress before land acquisition or foundation design.',
    highlight: 'Pre-Purchase Feasibility',
    specDetail: 'MCDA · 100-Yr Discharge',
    iconName: 'shield-check',
  },
  {
    title: 'Who is it built for?',
    meta: 'Target Users',
    copy: 'BuildWise is built for architects, civil engineers, general contractors, real estate developers, and individual land owners who need rapid, technically sound building plans, site analyses, and construction quantity takeoffs.',
    highlight: 'Architects, Engineers & Builders',
    specDetail: 'Multi-Role Workflows',
    iconName: 'sparkles',
  },
  {
    title: 'What makes BuildWise different?',
    meta: 'Engineering Grounding',
    copy: 'Unlike generic generative AI tools that hallucinate unbuildable concepts, BuildWise grounds all calculations in codified standards — National Building Code (NBC 2016), IS 1893:2016 seismic zoning, and CPWD Delhi Schedule of Rates (DSR) with zero paid third-party map APIs.',
    highlight: 'Zero Black Boxes · Full Provenance',
    specDetail: 'NBC 2016 · IS 1893 · CPWD DSR',
    iconName: 'zap',
  },
  {
    title: 'How does AI assist construction planning?',
    meta: 'Spatial Intelligence',
    copy: 'AI operates as a spatial intelligence layer and constraint solver — interpreting natural-language client briefs, synthesizing room hierarchies, solving slicing-tree topologies for non-overlapping spaces, and verifying statutory setbacks and Vastu alignments without guessing numbers.',
    highlight: 'Constraint Satisfaction (CSP)',
    specDetail: 'Slicing-Tree Topology',
    iconName: 'cpu',
  },
  {
    title: 'What features are available?',
    meta: 'Feature Suite',
    copy: 'The BuildWise Blueprint Generator creates dimensioned floor plans with room zoning and circulation. The platform also delivers elemental cost schedules (CPWD DSR 2023), multi-hazard environmental stress modeling, Vastu directional audits, and audit-ready PDF/SVG dossiers.',
    highlight: 'BuildWise Blueprint Generator',
    specDetail: 'Plans · Costs · Hazards · Dossiers',
    iconName: 'layers',
  },
];

const PillarCard: React.FC<{ pillar: ValuePillar }> = ({ pillar }) => (
  <motion.article
    variants={fadeRise}
    className="bw-surface p-5 sm:p-6 flex flex-col justify-between transition-[border-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 min-w-0 w-full rounded-[14px]"
  >
    <div className="min-w-0">
      <div className="flex items-start justify-between gap-3">
        <span
          aria-hidden
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px] border border-bw-line-soft bg-bw-accent-tint text-bw-accent"
        >
          <Icon name={pillar.iconName} size={19} strokeWidth={1.9} />
        </span>
        <span
          className="mt-1 px-2.5 py-0.5 rounded-full bg-bw-accent-tint border border-bw-line-soft text-[10.5px] font-semibold uppercase text-bw-accent-deep shrink-0"
          style={{ letterSpacing: '0.08em' }}
        >
          {pillar.meta}
        </span>
      </div>
      <h3 className="mt-4 text-[17px] font-bold tracking-[-0.015em] text-bw-ink">{pillar.title}</h3>
      <p className="mt-2.5 text-[14px] leading-[1.65] text-bw-ink-2">{pillar.copy}</p>
    </div>

    <div className="mt-6 pt-3.5 border-t border-bw-line-soft flex flex-col gap-1.5 xs:flex-row xs:items-center xs:justify-between text-[11px] min-w-0">
      <span className="font-medium text-bw-accent-deep tracking-tight truncate min-w-0">
        {pillar.highlight}
      </span>
      <span className="font-mono text-bw-ink-2 font-medium shrink-0">
        {pillar.specDetail}
      </span>
    </div>
  </motion.article>
);

export const AboutSection: React.FC = () => (
  <section id="about" aria-label="About BuildWise" className="relative scroll-mt-24 py-20 sm:py-24">
    <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-10">
      <motion.div variants={staggerParent(0.06)} initial="hidden" whileInView="show" viewport={SETTLE_VIEWPORT}>
        <SectionHeading
          eyebrow="Platform Overview"
          title="From ideas to intelligent building plans"
          copy="BuildWise is an AI-powered construction planning and blueprint generation platform that pairs deterministic civil engineering code with algorithmic spatial layout synthesis."
        />
        <ScrollRule className="mt-10" />
        <div className="mt-8 grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3 min-w-0">
          {PILLARS.map((p) => (
            <PillarCard key={p.title} pillar={p} />
          ))}
        </div>
      </motion.div>
    </div>
  </section>
);
