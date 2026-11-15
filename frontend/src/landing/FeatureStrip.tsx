/**
 * FeatureStrip.tsx — The platform's six core engineering capabilities.
 * Presents analytical capabilities with real code telemetry, provenance benchmarks,
 * and high-contrast accessible typography.
 */
import React from 'react';
import { motion } from 'framer-motion';
import { fadeRise, staggerParent, SETTLE_VIEWPORT } from './motion';
import { SectionHeading } from './SectionHeading';
import { ScrollRule } from './ScrollRule';
import { Icon } from '../components/Icon';

interface Feature {
  title: string;
  copy: string;
  /** The standard, method or artefact behind the capability. */
  meta: string;
  telemetry: string;
  specDetail: string;
  icon: React.ReactNode;
}

const FEATURES: ReadonlyArray<Feature> = [
  {
    title: 'Land suitability',
    meta: 'MCDA',
    telemetry: 'Score 87/100 · 4 Terrain Layers',
    specDetail: 'USGS 3DEP & Cop-DEM',
    copy: 'Multi-criteria scoring over topography, land use, and environmental data, with the weightings disclosed.',
    icon: <Icon name="mountain" size={17} strokeWidth={1.9} />,
  },
  {
    title: 'Seismic and flood risk',
    meta: 'IS 1893',
    telemetry: 'Zone III · 0.16g PGA · 100-yr Discharge',
    specDetail: 'IS 1893:2016 · Open-Meteo',
    copy: 'Zone and inundation stress from the code plus historical event and river-discharge telemetry.',
    icon: <Icon name="activity" size={17} strokeWidth={1.9} />,
  },
  {
    title: 'Cost estimation',
    meta: 'CPWD DSR',
    telemetry: 'Benchmark ₹2,450 / sq.ft',
    specDetail: 'CPWD DSR 2023 Rates',
    copy: 'Benchmarked construction cost by elemental head, with terrain and quality surcharges shown separately.',
    icon: <Icon name="currency-rupee" size={17} strokeWidth={1.9} />,
  },
  {
    title: 'Vastu orientation',
    meta: '9-zone mandala',
    telemetry: '88/100 · NE Ishanya Entrance',
    specDetail: 'Solar & Wind Alignments',
    copy: 'Orientation and placement guidance scored per zone, alongside the solar and wind bearings that drive it.',
    icon: <Icon name="compass" size={17} strokeWidth={1.9} />,
  },
  {
    title: 'Generative blueprints',
    meta: 'Spatial CSP',
    telemetry: 'Slicing-Tree CSP · Invariants Solved',
    specDetail: 'Topological Non-Overlap',
    copy: 'Floor plans solved against a placement knowledge base and non-negotiable topological invariants.',
    icon: <Icon name="blueprint" size={17} strokeWidth={1.9} />,
  },
  {
    title: 'Print-ready dossier',
    meta: 'Vector PDF',
    telemetry: '174mm Vector Stamp · Arch D',
    specDetail: 'Pure-Python Vector Engine',
    copy: 'One click compiles the scorecard, risk matrices, benchmarks, and a 174mm vector blueprint.',
    icon: <Icon name="printer" size={17} strokeWidth={1.9} />,
  },
];

const CapabilityCard: React.FC<{ feature: Feature }> = ({ feature }) => (
  <motion.article
    variants={fadeRise}
    className="bw-surface p-4 sm:p-5 flex flex-col justify-between transition-[border-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 min-w-0 w-full"
  >
    <div className="min-w-0">
      <div className="flex items-start justify-between gap-3">
        <span
          aria-hidden
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] border border-bw-line-soft bg-bw-accent-tint text-bw-accent"
        >
          {feature.icon}
        </span>
        <span
          className="mt-1 px-2 py-0.5 rounded-full bg-bw-accent-tint border border-bw-line-soft text-[10.5px] font-semibold uppercase text-bw-accent-deep shrink-0"
          style={{ letterSpacing: '0.08em' }}
        >
          {feature.meta}
        </span>
      </div>
      <h3 className="mt-4 text-[16px] font-bold tracking-[-0.015em] text-bw-ink">{feature.title}</h3>
      <p className="mt-2 text-[14px] leading-[1.6] text-bw-ink-2">{feature.copy}</p>
    </div>

    {/* Technical Telemetry Footer */}
    <div className="mt-5 pt-3.5 border-t border-bw-line-soft flex flex-col gap-1.5 xs:flex-row xs:items-center xs:justify-between text-[11px] min-w-0">
      <span className="font-mono text-bw-ink-2 font-medium tracking-tight truncate min-w-0">
        {feature.telemetry}
      </span>
      <span className="inline-flex items-center gap-1 font-semibold text-bw-accent-deep shrink-0 text-[10.5px]">
        <Icon name="check" size={11} strokeWidth={2.4} />
        <span>{feature.specDetail}</span>
      </span>
    </div>
  </motion.article>
);

export const FeatureStrip: React.FC = () => (
  <section id="capabilities" aria-label="Platform capabilities" className="relative scroll-mt-24 py-24 sm:py-28">
    <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-10">
      <motion.div variants={staggerParent(0.06)} initial="hidden" whileInView="show" viewport={SETTLE_VIEWPORT}>
        <SectionHeading
          eyebrow="Capabilities"
          title="Six analyses behind every pin"
          copy="The same run produces suitability, hazard, cost, orientation, and a buildable plan — grounded in Indian code and open data."
        />
        {/* The section boundary draws with the wheel */}
        <ScrollRule className="mt-10" />
        <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 min-w-0">
          {FEATURES.map((f) => (
            <CapabilityCard key={f.title} feature={f} />
          ))}
        </div>
      </motion.div>
    </div>
  </section>
);