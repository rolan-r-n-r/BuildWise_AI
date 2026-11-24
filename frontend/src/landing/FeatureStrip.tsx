/**
 * FeatureStrip.tsx — The platform's six core engineering benchmarks.
 * Uses a two-tier asymmetric layout: a wide featured Spatial CSP blueprint card
 * paired with the Print-ready Dossier card on top, followed by four categorized
 * engineering benchmark cards (Financial, Terrain, Hazard, Orientation).
 */
import React from 'react';
import { motion } from 'framer-motion';
import { fadeRise, staggerParent, SETTLE_VIEWPORT } from './motion';
import { SectionHeading } from './SectionHeading';
import { ScrollRule } from './ScrollRule';
import { Icon } from '../components/Icon';
import type { IconName } from '../components/Icon';

type BenchmarkTone = 'accent' | 'green' | 'amber';

interface Feature {
  title: string;
  copy: string;
  /** The standard, method or artefact behind the capability. */
  meta: string;
  category: string;
  telemetry: string;
  specDetail: string;
  tone: BenchmarkTone;
  iconName: IconName;
}

const TONE_CLASSES: Record<BenchmarkTone, { iconBox: string; badge: string }> = {
  accent: {
    iconBox: 'bg-bw-accent-tint text-bw-accent',
    badge: 'text-bw-accent-deep',
  },
  green: {
    iconBox: 'bg-bw-green-tint text-bw-green-ink',
    badge: 'text-bw-green-ink',
  },
  amber: {
    iconBox: 'bg-bw-amber-tint text-bw-amber-ink',
    badge: 'text-bw-amber-ink',
  },
};

const FEATURED_BLUEPRINT: Feature = {
  title: 'BuildWise Blueprint Generator',
  meta: 'Spatial CSP',
  category: 'Generative Layout',
  telemetry: 'Slicing-Tree CSP · Invariants Solved',
  specDetail: 'Topological Non-Overlap',
  tone: 'accent',
  iconName: 'blueprint',
  copy: 'Generates preliminary floor plans using an algorithmic Constraint Satisfaction Problem (CSP) solver enforcing room adjacencies, circulation, and statutory setbacks.',
};

const FEATURED_DOSSIER: Feature = {
  title: 'Print-ready engineering dossier',
  meta: 'Vector PDF',
  category: 'Deliverable Output',
  telemetry: '174mm Vector Stamp · Arch D',
  specDetail: 'Pure-Python Vector Engine',
  tone: 'green',
  iconName: 'printer',
  copy: 'One click compiles the executive scorecard, hazard matrices, cost benchmarks, and a 174mm vector blueprint into a contractor-ready PDF.',
};

const BENCHMARKS: ReadonlyArray<Feature> = [
  {
    title: 'Construction cost & materials',
    meta: 'CPWD DSR',
    category: 'Cost Benchmark',
    telemetry: 'Benchmark ₹2,450 / sq.ft',
    specDetail: 'CPWD DSR 2023 Rates',
    tone: 'green',
    iconName: 'currency-rupee',
    copy: 'Benchmarked construction cost and material requirements by elemental head (structural, finishes, services), with terrain and quality surcharges shown separately.',
  },
  {
    title: 'Land suitability & terrain',
    meta: 'MCDA',
    category: 'Geospatial Score',
    telemetry: 'Score 87/100 · 4 Terrain Layers',
    specDetail: 'USGS 3DEP & Cop-DEM',
    tone: 'accent',
    iconName: 'mountain',
    copy: 'Multi-criteria scoring over slope, elevation, land use, and environmental data, with the weightings disclosed.',
  },
  {
    title: 'Seismic and flood hazard',
    meta: 'IS 1893',
    category: 'Hazard Matrix',
    telemetry: 'Zone II · 0.10g PGA · 100-yr',
    specDetail: 'IS 1893:2016 · Open-Meteo',
    tone: 'amber',
    iconName: 'activity',
    copy: 'Zone and inundation stress from codified Indian standards plus historical event and river-discharge telemetry.',
  },
  {
    title: 'Vastu orientation & solar',
    meta: '9-zone mandala',
    category: 'Site Orientation',
    telemetry: '88/100 · NE Ishanya Entrance',
    specDetail: 'Solar & Wind Alignments',
    tone: 'accent',
    iconName: 'compass',
    copy: 'Orientation and room placement guidance scored per zone, alongside the solar and wind bearings that drive it.',
  },
];

/** Schematic slicing-tree CSP zoning illustration (pure architectural hairlines, no fabricated figures). */
const SchematicCspDiagram: React.FC = () => (
  <div
    aria-hidden="true"
    className="rounded-[10px] border border-bw-line-soft bg-bw-porcelain p-3"
  >
    <div className="mb-2 flex items-center justify-between font-mono text-[9.5px] uppercase text-bw-ink-2">
      <span>CSP Partition Tree</span>
      <span className="text-bw-accent-deep">N ↑</span>
    </div>
    <svg viewBox="0 0 220 132" className="h-auto w-full" fill="none">
      {/* Setback boundary */}
      <rect
        x="6"
        y="6"
        width="208"
        height="120"
        rx="2"
        stroke="var(--bw-line)"
        strokeWidth="1"
        strokeDasharray="3 3"
      />
      {/* Envelope */}
      <rect
        x="18"
        y="16"
        width="184"
        height="100"
        fill="var(--bw-white)"
        stroke="var(--bw-ink)"
        strokeWidth="1.4"
      />
      {/* Living zone */}
      <rect x="18" y="16" width="102" height="58" fill="var(--bw-accent-tint)" stroke="var(--bw-accent)" strokeWidth="1" />
      <text x="69" y="48" textAnchor="middle" fill="var(--bw-ink)" fontSize="9" fontFamily="ui-monospace, monospace" fontWeight="600">
        LIVING
      </text>
      {/* Kitchen / Dining */}
      <rect x="120" y="16" width="82" height="58" stroke="var(--bw-line)" strokeWidth="1" />
      <text x="161" y="48" textAnchor="middle" fill="var(--bw-ink-2)" fontSize="8.5" fontFamily="ui-monospace, monospace">
        DINING / KIT
      </text>
      {/* Corridor spine */}
      <rect x="18" y="74" width="184" height="12" fill="var(--bw-porcelain-2)" stroke="var(--bw-line)" strokeWidth="0.8" />
      {/* Bedrooms & Wet core */}
      <rect x="18" y="86" width="66" height="30" stroke="var(--bw-line)" strokeWidth="1" />
      <text x="51" y="104" textAnchor="middle" fill="var(--bw-ink-2)" fontSize="8" fontFamily="ui-monospace, monospace">
        BED 01
      </text>
      <rect x="84" y="86" width="52" height="30" stroke="var(--bw-line)" strokeWidth="1" />
      <text x="110" y="104" textAnchor="middle" fill="var(--bw-ink-2)" fontSize="8" fontFamily="ui-monospace, monospace">
        CORE
      </text>
      <rect x="136" y="86" width="66" height="30" fill="var(--bw-green-tint)" stroke="var(--bw-green-ink)" strokeWidth="0.9" />
      <text x="169" y="104" textAnchor="middle" fill="var(--bw-green-ink)" fontSize="8" fontFamily="ui-monospace, monospace" fontWeight="600">
        ENTRY
      </text>
    </svg>
  </div>
);

const BenchmarkCard: React.FC<{ feature: Feature; compact?: boolean }> = ({ feature, compact = false }) => {
  const tone = TONE_CLASSES[feature.tone];
  return (
    <motion.article
      variants={fadeRise}
      className={`bw-surface ${
        compact ? 'p-4 sm:p-5' : 'p-5 sm:p-6'
      } flex flex-col justify-between rounded-[14px] min-w-0 w-full`}
    >
      <div className="min-w-0">
        <div className="flex items-start justify-between gap-2.5">
          <span
            aria-hidden
            className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] border border-bw-line-soft ${tone.iconBox}`}
          >
            <Icon name={feature.iconName} size={17} strokeWidth={1.9} />
          </span>
          <div className="text-right min-w-0">
            <span
              className={`block font-mono text-[10px] font-semibold uppercase ${tone.badge}`}
              style={{ letterSpacing: '0.1em' }}
            >
              {feature.meta}
            </span>
            <span className="block text-[10.5px] text-bw-ink-2 truncate">{feature.category}</span>
          </div>
        </div>
        <h3 className="mt-4 text-[16px] font-bold tracking-[-0.015em] text-bw-ink">{feature.title}</h3>
        <p className="mt-2 text-[13.5px] leading-[1.6] text-bw-ink-2">{feature.copy}</p>
      </div>

      {/* Technical Telemetry Footer */}
      <div className="mt-5 pt-3 border-t border-bw-line-soft flex flex-col gap-1 text-[11px] min-w-0">
        <span className="font-mono text-bw-ink font-medium tracking-tight truncate min-w-0">
          {feature.telemetry}
        </span>
        <span className={`inline-flex items-center gap-1 font-semibold ${tone.badge} text-[10.5px]`}>
          <Icon name="check" size={11} strokeWidth={2.4} />
          <span className="truncate">{feature.specDetail}</span>
        </span>
      </div>
    </motion.article>
  );
};

export const FeatureStrip: React.FC = () => {
  const blueprintTone = TONE_CLASSES[FEATURED_BLUEPRINT.tone];
  return (
    <section id="capabilities" aria-label="Platform capabilities" className="relative scroll-mt-24 py-8 md:py-16 lg:py-24">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-10">
        <motion.div variants={staggerParent(0.06)} initial="hidden" whileInView="show" viewport={SETTLE_VIEWPORT}>
          <SectionHeading
            eyebrow="Core Capabilities"
            title="Six engineering benchmarks, calculated live"
            copy="The same run produces blueprints, site suitability, hazard risks, CPWD cost schedules, and Vastu orientation — grounded in Indian code and open data."
          />
          <ScrollRule className="mt-5 md:mt-8" />

          {/* Tier 1: Featured Blueprint Generator (7 cols) + Engineering Dossier (5 cols) */}
          <div className="mt-6 md:mt-8 grid grid-cols-1 gap-4 lg:grid-cols-12 min-w-0">
            <motion.article
              variants={fadeRise}
              className="bw-surface lg:col-span-7 p-5 sm:p-6 rounded-[14px] grid grid-cols-1 sm:grid-cols-[1.15fr_0.85fr] gap-5 items-center min-w-0"
            >
              <div className="flex flex-col justify-between h-full min-w-0">
                <div>
                  <div className="flex items-center justify-between gap-2.5">
                    <span
                      aria-hidden
                      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] border border-bw-line-soft ${blueprintTone.iconBox}`}
                    >
                      <Icon name={FEATURED_BLUEPRINT.iconName} size={18} strokeWidth={1.9} />
                    </span>
                    <span
                      className={`font-mono text-[10.5px] font-semibold uppercase ${blueprintTone.badge}`}
                      style={{ letterSpacing: '0.1em' }}
                    >
                      {FEATURED_BLUEPRINT.meta} · {FEATURED_BLUEPRINT.category}
                    </span>
                  </div>
                  <h3 className="mt-4 text-[18px] font-bold tracking-[-0.02em] text-bw-ink">
                    {FEATURED_BLUEPRINT.title}
                  </h3>
                  <p className="mt-2 text-[14px] leading-[1.6] text-bw-ink-2">{FEATURED_BLUEPRINT.copy}</p>
                </div>

                <div className="mt-5 pt-3 border-t border-bw-line-soft flex flex-wrap items-center justify-between gap-2 text-[11px]">
                  <span className="font-mono text-bw-ink font-medium">{FEATURED_BLUEPRINT.telemetry}</span>
                  <span className={`inline-flex items-center gap-1 font-semibold ${blueprintTone.badge}`}>
                    <Icon name="check" size={11} strokeWidth={2.4} />
                    <span>{FEATURED_BLUEPRINT.specDetail}</span>
                  </span>
                </div>
              </div>

              <SchematicCspDiagram />
            </motion.article>

            <div className="lg:col-span-5 flex">
              <BenchmarkCard feature={FEATURED_DOSSIER} />
            </div>
          </div>

          {/* Tier 2: Four Categorized Benchmark Cards (2 cols tablet, 4 cols >=1200px) */}
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 min-[1200px]:grid-cols-4 min-w-0">
            {BENCHMARKS.map((f) => (
              <BenchmarkCard key={f.title} feature={f} compact />
            ))}
          </div>
        </motion.div>
      </div>
    </section>
  );
};
