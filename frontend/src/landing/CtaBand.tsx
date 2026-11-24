/**
 * CtaBand.tsx — the closing band (#blueprint) plus the site footer.
 * Presents an interactive Feasibility Dossier preview inside macOS window chrome,
 * alongside the primary CTA and provenance-derived footer columns.
 */
import React, { useRef, useState } from 'react';
import { motion, useReducedMotion, useTransform } from 'framer-motion';
import { fadeRise, staggerParent, timed, SETTLE_VIEWPORT } from './motion';
import { useEntryProgress } from './scrollLink';
import { APP_PATH, SIGN_IN_PATH, SIGN_UP_PATH, FORGOT_PASSWORD_PATH, navigate } from './router';
import { scrollToId } from './scroll';
import { Icon } from '../components/Icon';
import type { IconName } from '../components/Icon';
import { SectionHeading } from './SectionHeading';
import { GROUP_LABELS, GROUP_ORDER, sourcesIn } from './standards';
import { WindowBar } from './WindowBar';
import { LANDING } from './theme';
import { LOGO_SRC, LOGO_SRCSET, LOGO_WHITE_SRC, LOGO_WHITE_SRCSET } from './logo';
import { CountUp } from './CountUp';

interface DossierRow {
  id: string;
  label: string;
  meta: string;
  icon: IconName;
  summary: string;
  metrics: ReadonlyArray<{ k: string; v: string }>;
}

const DOSSIER_ROWS: ReadonlyArray<DossierRow> = [
  {
    id: 'scorecard',
    label: 'Executive scorecard',
    meta: 'MCDA',
    icon: 'mountain',
    summary: 'Multi-criteria land suitability across slope, elevation, land use, and drainage.',
    metrics: [
      { k: 'Suitability', v: '87 / 100' },
      { k: 'Plot Area', v: '317.8 m²' },
      { k: 'Buildable', v: '191.5 m²' },
    ],
  },
  {
    id: 'risk',
    label: 'Risk matrix',
    meta: 'IS 1893',
    icon: 'activity',
    summary: 'Codified seismic zone factor paired with historical precipitation and river-discharge telemetry.',
    metrics: [
      { k: 'Seismic Zone', v: 'Zone II' },
      { k: 'Design PGA', v: '0.10 g' },
      { k: 'Flood Horizon', v: '100-yr' },
    ],
  },
  {
    id: 'cost',
    label: 'Cost benchmark',
    meta: 'CPWD DSR',
    icon: 'currency-rupee',
    summary: 'Elemental schedule across structural frame, masonry finishes, and MEP services.',
    metrics: [
      { k: 'Rate Basis', v: 'DSR 2023' },
      { k: 'Benchmark', v: '₹2,450 / sq.ft' },
      { k: 'Schedule', v: 'Elemental' },
    ],
  },
  {
    id: 'blueprint',
    label: 'Vector blueprint',
    meta: '174 mm',
    icon: 'blueprint',
    summary: 'Dimensioned G+1 floorplan solved by slicing-tree CSP with topological invariants.',
    metrics: [
      { k: 'Sheet Plate', v: '174 mm PDF' },
      { k: 'Footprint', v: '13.5 × 9.0 m' },
      { k: 'Rule Layers', v: '11 / 15 Pass' },
    ],
  },
];

/* ------------------------------------------------------------------ */
/* #blueprint — the output band                                        */
/* ------------------------------------------------------------------ */

export const CtaBand: React.FC = () => {
  const reduced = useReducedMotion();
  const [selectedRowId, setSelectedRowId] = useState<string>('scorecard');
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const activeRow = DOSSIER_ROWS.find((r) => r.id === selectedRowId) ?? DOSSIER_ROWS[0];

  const onTabKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    let nextIndex = -1;
    if (e.key === 'ArrowDown' || e.key === 'ArrowRight') {
      nextIndex = (index + 1) % DOSSIER_ROWS.length;
    } else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') {
      nextIndex = (index - 1 + DOSSIER_ROWS.length) % DOSSIER_ROWS.length;
    } else if (e.key === 'Home') {
      nextIndex = 0;
    } else if (e.key === 'End') {
      nextIndex = DOSSIER_ROWS.length - 1;
    }
    if (nextIndex < 0) return;
    e.preventDefault();
    setSelectedRowId(DOSSIER_ROWS[nextIndex].id);
    tabRefs.current[nextIndex]?.focus();
  };

  const windowRef = useRef<HTMLDivElement>(null);
  const entry = useEntryProgress(windowRef);
  const windowY = useTransform(entry, [0, 1], [18, -8]);

  return (
    <section id="blueprint" aria-label="Print-ready output" className="relative scroll-mt-24 pb-12 pt-4 md:pb-20 md:pt-6 lg:pb-28">
      <motion.div
        variants={staggerParent(0.08)}
        initial="hidden"
        whileInView="show"
        viewport={SETTLE_VIEWPORT}
        className="mx-auto grid max-w-7xl items-center gap-8 md:gap-12 px-4 sm:px-6 lg:grid-cols-[1.02fr_0.98fr] lg:gap-16 lg:px-10"
      >
        <div>
          <SectionHeading
            eyebrow="Output"
            title="Every analysis becomes a buildable dossier"
            copy="One click compiles the executive scorecard, risk matrices, the CPWD cost benchmark, Vastu notes, and the 174mm vector blueprint — as a print-ready PDF."
          />

          <motion.div variants={fadeRise} className="mt-8 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => navigate(APP_PATH)}
              className="group inline-flex h-12 items-center gap-2 rounded-full bg-bw-cta px-6 text-[15px] font-semibold text-bw-cta-ink transition-[background-color,transform] duration-200 hover:bg-bw-cta-hover active:scale-[0.98] cursor-pointer"
              style={{ boxShadow: LANDING.shadow.dark }}
            >
              Open the app
              <span
                aria-hidden
                className="transition-transform duration-200 group-hover:translate-x-1 motion-reduce:transform-none"
              >
                <Icon name="chevron-right" size={15} />
              </span>
            </button>
            <button
              type="button"
              onClick={() => scrollToId('standards')}
              className="inline-flex h-12 items-center rounded-full border border-bw-line bg-bw-surface px-5 text-[15px] font-semibold text-bw-ink transition-[background-color,border-color,transform] duration-200 hover:bg-bw-line-soft active:scale-[0.98] cursor-pointer"
            >
              Standards and data
            </button>
          </motion.div>
        </div>

        {/* The dossier preview inside macOS window chrome */}
        <motion.div ref={windowRef} style={{ y: windowY }}>
          <motion.div
            variants={
              reduced
                ? { hidden: { opacity: 1 }, show: { opacity: 1, transition: timed(0.3) } }
                : { hidden: { opacity: 1, y: 16 }, show: { opacity: 1, y: 0, transition: timed(0.55) } }
            }
            className="bw-window"
          >
            <WindowBar
              title="Feasibility Dossier"
              subtitle="Bengaluru · 317.8 m² · GEN-T1-2F"
              toolbar={
                <span className="bw-window-chip gap-1.5">
                  <span className="text-[11px] font-bold tabular-nums text-bw-accent">
                    <CountUp value={87} />
                  </span>
                  <span className="text-[10.5px] font-semibold uppercase text-bw-ink-3" style={{ letterSpacing: '0.06em' }}>
                    score
                  </span>
                </span>
              }
            />

            <div className="rounded-b-[14px] bg-bw-porcelain p-3.5 sm:p-4">
              {/* Executive quick indicators */}
              <div className="grid grid-cols-3 gap-2 mb-3 text-center text-[11px]">
                <div className="p-2 rounded-[8px] bg-bw-surface border border-bw-line-soft">
                  <span className="text-bw-ink-2 block text-[10px] uppercase font-mono">NBC 2016</span>
                  <span className="font-bold text-bw-green-ink mt-0.5 block">Compliant</span>
                </div>
                <div className="p-2 rounded-[8px] bg-bw-surface border border-bw-line-soft">
                  <span className="text-bw-ink-2 block text-[10px] uppercase font-mono">IS 1893</span>
                  <span className="font-bold text-bw-ink mt-0.5 block">Zone II</span>
                </div>
                <div className="p-2 rounded-[8px] bg-bw-surface border border-bw-line-soft">
                  <span className="text-bw-ink-2 block text-[10px] uppercase font-mono">Vastu</span>
                  <span className="font-bold text-bw-accent mt-0.5 block">
                    <CountUp value={88} /> / 100
                  </span>
                </div>
              </div>

              {/* Interactive deliverable sections list */}
              <div role="tablist" aria-label="Dossier sections" aria-orientation="vertical" className="flex flex-col gap-1.5">
                {DOSSIER_ROWS.map((row, index) => {
                  const isSelected = row.id === activeRow.id;
                  return (
                    <button
                      key={row.id}
                      ref={(el) => {
                        tabRefs.current[index] = el;
                      }}
                      id={`dossier-tab-${row.id}`}
                      type="button"
                      role="tab"
                      aria-selected={isSelected}
                      aria-controls={`dossier-panel-${row.id}`}
                      tabIndex={isSelected ? 0 : -1}
                      onClick={() => setSelectedRowId(row.id)}
                      onKeyDown={(e) => onTabKeyDown(e, index)}
                      className={`w-full min-h-11 flex items-center justify-between gap-3 rounded-[9px] border px-3 py-2 text-left transition-colors duration-150 cursor-pointer ${
                        isSelected
                          ? 'border-bw-accent bg-bw-surface'
                          : 'border-bw-line-soft bg-bw-surface/70 hover:bg-bw-surface hover:border-bw-line'
                      }`}
                    >
                      <span className="flex items-center gap-2.5 min-w-0">
                        <span
                          className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full transition-colors duration-150 ${
                            isSelected
                              ? 'bg-bw-accent text-bw-cta-ink'
                              : 'bg-bw-accent-tint text-bw-accent'
                          }`}
                          aria-hidden
                        >
                          <Icon name={isSelected ? 'check' : row.icon} size={12} strokeWidth={2.2} />
                        </span>
                        <span className="text-[13px] font-semibold text-bw-ink truncate">{row.label}</span>
                      </span>
                      <span
                        className={`font-mono text-[10.5px] font-semibold uppercase shrink-0 ${
                          isSelected ? 'text-bw-accent-deep' : 'text-bw-ink-2'
                        }`}
                        style={{ letterSpacing: '0.08em' }}
                      >
                        {row.meta}
                      </span>
                    </button>
                  );
                })}
              </div>

              {/* Active Dossier Section Preview Panel */}
              <div
                id={`dossier-panel-${activeRow.id}`}
                role="tabpanel"
                aria-labelledby={`dossier-tab-${activeRow.id}`}
                tabIndex={0}
                className="mt-2.5 rounded-[10px] border border-bw-line-soft bg-bw-surface p-3"
              >
                <p className="text-[12px] leading-[1.55] text-bw-ink-2">{activeRow.summary}</p>
                <dl className="mt-2.5 grid grid-cols-1 xs:grid-cols-3 gap-2.5 border-t border-bw-line-soft pt-2.5">
                  {activeRow.metrics.map((m) => (
                    <div key={m.k} className="flex items-baseline justify-between xs:block min-w-0">
                      <dt className="font-mono text-[9.5px] uppercase text-bw-ink-3">{m.k}</dt>
                      <dd className="xs:mt-0.5 ui-font-tabular text-[12px] font-semibold text-bw-ink">{m.v}</dd>
                    </div>
                  ))}
                </dl>
              </div>

              <p className="mt-3 flex items-center justify-between gap-2 px-1 text-[12px] text-bw-ink-2">
                <span>PDF · Vector drawings · Room schedule</span>
                <span className="inline-flex items-center gap-1.5 font-semibold text-bw-green-ink shrink-0">
                  <Icon name="printer" size={12} />
                  <span>Ready to print</span>
                </span>
              </p>
            </div>
          </motion.div>
        </motion.div>
      </motion.div>
    </section>
  );
};

/* ------------------------------------------------------------------ */
/* Footer — the closing summary and provenance credits                 */
/* ------------------------------------------------------------------ */

export const Footer: React.FC = () => (
  <footer id="footer" className="scroll-mt-24 border-t border-bw-line-soft bg-bw-surface">
    <div className="mx-auto max-w-7xl px-4 py-10 md:py-14 sm:px-6 lg:px-10">
      <div className="grid gap-8 md:gap-10 md:grid-cols-2 lg:grid-cols-[1.2fr_1fr_1fr_1fr]">
        <div>
          <div className="flex items-center gap-2.5">
            <img
              src={LOGO_SRC}
              srcSet={LOGO_SRCSET}
              alt=""
              width={30}
              height={30}
              className="rounded-[8px] dark:hidden"
              decoding="async"
            />
            <img
              src={LOGO_WHITE_SRC}
              srcSet={LOGO_WHITE_SRCSET}
              alt=""
              width={30}
              height={30}
              className="rounded-[8px] hidden dark:block"
              decoding="async"
            />
            <p className="text-[15px] font-bold text-bw-ink">BuildWise</p>
          </div>
          <p className="mt-3 max-w-sm text-[13px] leading-[1.6] text-bw-ink-2">
            AI-powered construction planning and blueprint generation platform. From a map pin to a buildable plan, grounded in codified civil standards.
          </p>
          <button
            type="button"
            onClick={() => navigate(APP_PATH)}
            className="group mt-5 inline-flex h-11 items-center gap-1.5 rounded-full border border-bw-line bg-bw-surface px-4 text-[13px] font-semibold text-bw-ink transition-[background-color,border-color] duration-200 hover:bg-bw-line-soft cursor-pointer"
          >
            Open the app
            <span aria-hidden className="transition-transform duration-200 group-hover:translate-x-0.5 motion-reduce:transform-none">
              <Icon name="chevron-right" size={13} />
            </span>
          </button>

          {/* Quick Authentication & Overview Links */}
          <div className="mt-3 flex flex-wrap items-center gap-1 text-[12px] text-bw-ink-2">
            <a
              href="#about"
              onClick={(e) => {
                e.preventDefault();
                scrollToId('about');
              }}
              className="min-h-[44px] min-w-[44px] px-2.5 inline-flex items-center justify-center hover:text-bw-ink hover:underline cursor-pointer"
            >
              About
            </a>
            <span aria-hidden="true" className="text-bw-line">·</span>
            <button
              type="button"
              onClick={() => navigate(SIGN_IN_PATH)}
              className="min-h-[44px] min-w-[44px] px-2.5 inline-flex items-center justify-center hover:text-bw-ink hover:underline cursor-pointer"
            >
              Sign In
            </button>
            <span aria-hidden="true" className="text-bw-line">·</span>
            <button
              type="button"
              onClick={() => navigate(SIGN_UP_PATH)}
              className="min-h-[44px] min-w-[44px] px-2.5 inline-flex items-center justify-center hover:text-bw-ink hover:underline cursor-pointer"
            >
              Create Account
            </button>
            <span aria-hidden="true" className="text-bw-line">·</span>
            <button
              type="button"
              onClick={() => navigate(FORGOT_PASSWORD_PATH)}
              className="min-h-[44px] min-w-[44px] px-2.5 inline-flex items-center justify-center hover:text-bw-ink hover:underline cursor-pointer"
            >
              Password Recovery
            </button>
          </div>
        </div>

        {/* The index of the #standards sheet */}
        {GROUP_ORDER.map((group) => (
          <div key={group}>
            <p className="text-[11px] font-semibold uppercase text-bw-ink-2" style={{ letterSpacing: '0.14em' }}>
              {GROUP_LABELS[group]}
            </p>
            <ul className="mt-3 flex flex-col gap-2">
              {sourcesIn(group).map((source) => (
                <li key={source.name} className="text-[13px] leading-[1.5] text-bw-ink-2">
                  {source.name}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <div className="mt-8 md:mt-12 flex flex-col gap-3 border-t border-bw-line-soft pt-6 text-[12px] text-bw-ink-2 sm:flex-row sm:items-center sm:justify-between">
        <p>© 2026 BuildWise AI · MIT License</p>
        <p>
          Press{' '}
          <kbd className="rounded-[5px] border border-bw-line bg-bw-surface px-1.5 py-0.5 text-[11px] font-semibold text-bw-ink-2">
            ?
          </kbd>{' '}
          inside the app for keyboard shortcuts.
        </p>
      </div>
    </div>
  </footer>
);
