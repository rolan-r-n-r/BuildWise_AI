/**
 * CtaBand.tsx — the closing band (#blueprint) plus the site footer.
 *
 * Left: heading and CTAs. Right: the printable dossier the platform produces,
 * presented as a second macOS window so the page's two artefacts share one
 * language — the app you use, and the document it hands you.
 *
 * The window body is opaque and unblurred on purpose. This card scrolls over
 * the fixed porcelain backdrop, where a backdrop-filter is imperceptible while
 * still re-blurring its own area on every frame of the scroll.
 *
 * The footer is a real footer: the standards the product implements and the
 * sources it consumes, each in its own column, above a baseline row. It
 * SUMMARISES the #standards section that now sits mid-page — the detail lives
 * there, and both "Standards" doorways (the nav link and this band's secondary
 * button) travel to it rather than to the footer that sits directly beneath
 * this band.
 *
 * The three columns are DERIVED from landing/standards.ts, the same module the
 * sheet renders from: labels and names, no roles and no credit lines. Those
 * lists used to be typed out here as well, in a different vocabulary from the
 * sheet's — "IS 1893 seismic zones" against "IS 1893 (Part 1): 2016", and an
 * imagery column that credited three providers the sheet had merged into one
 * row. A footer is where people look for the licence line, so it is the last
 * place that should be able to disagree with the section it summarises.
 */
import React, { useRef } from 'react';
import { motion, useReducedMotion, useTransform } from 'framer-motion';
import { EASE_APPLE, fadeRise, staggerParent, timed, SETTLE_VIEWPORT } from './motion';
import { useEntryProgress } from './scrollLink';
import { APP_PATH, SIGN_IN_PATH, SIGN_UP_PATH, FORGOT_PASSWORD_PATH, navigate } from './router';
import { scrollToId } from './scroll';
import { Icon } from '../components/Icon';
import { SectionHeading } from './SectionHeading';
import { GROUP_LABELS, GROUP_ORDER, sourcesIn } from './standards';
import { WindowBar } from './WindowBar';
import { LANDING } from './theme';
import { LOGO_SRC, LOGO_SRCSET, LOGO_WHITE_SRC, LOGO_WHITE_SRCSET } from './logo';

const DOSSIER_ROWS: ReadonlyArray<{ label: string; meta: string }> = [
  { label: 'Executive scorecard', meta: 'MCDA' },
  { label: 'Risk matrix', meta: 'IS 1893' },
  { label: 'Cost benchmark', meta: 'CPWD DSR' },
  { label: 'Vector blueprint', meta: '174 mm' },
];

/* ------------------------------------------------------------------ */
/* #blueprint — the output band                                        */
/* ------------------------------------------------------------------ */

export const CtaBand: React.FC = () => {
  const reduced = useReducedMotion();

  /* The dossier window's own entry band. It settles from +18px to -8px as the
     section crosses the reading position, i.e. the artefact keeps rising a
     little after the copy beside it has stopped. Transform-only. */
  const windowRef = useRef<HTMLDivElement>(null);
  const entry = useEntryProgress(windowRef);
  const windowY = useTransform(entry, [0, 1], [18, -8]);

  return (
    <section id="blueprint" aria-label="Print-ready output" className="relative scroll-mt-24 pb-28 pt-4 sm:pb-32">
      <motion.div
        variants={staggerParent(0.08)}
        initial="hidden"
        whileInView="show"
        viewport={SETTLE_VIEWPORT}
        className="mx-auto grid max-w-7xl items-center gap-12 px-6 lg:grid-cols-[1.05fr_0.95fr] lg:gap-16 lg:px-10"
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
              className="group inline-flex h-12 items-center gap-2 rounded-full bg-bw-cta px-6 text-[15px] font-semibold text-bw-cta-ink transition-[background-color,transform] duration-200 hover:bg-bw-cta-hover active:scale-[0.98]"
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
            {/* This button used to target the footer — which, from here, is
                already on screen: measured, it moved the page 121px and read as
                broken. It points at the #standards section instead, which is
                the content its label names and is far enough away to be an
                actual journey. */}
            <button
              type="button"
              onClick={() => scrollToId('standards')}
              className="inline-flex h-12 items-center rounded-full border border-bw-line bg-bw-surface px-5 text-[15px] font-semibold text-bw-ink transition-[background-color,border-color,transform] duration-200 hover:bg-bw-line-soft active:scale-[0.98]"
            >
              Standards and data
            </button>
          </motion.div>
        </div>

        {/* The dossier, as the window that produces it. The wrapper is the
            scroll layer: it rides a little faster than the copy beside it, so
            the row separates in depth. The inner motion.div still owns the
            one-shot entrance; the two transforms compose. */}
        <motion.div ref={windowRef} style={{ y: windowY }}>
          <motion.div
            /* The transition is stated, not inherited: without one this window
               animated on framer's default spring while the copy beside it moved
               on the Apple curve, so the two halves of the row arrived with
               visibly different weight. */
            variants={
              reduced
                ? { hidden: { opacity: 0 }, show: { opacity: 1, transition: timed(0.3) } }
                : { hidden: { opacity: 0, y: 24 }, show: { opacity: 1, y: 0, transition: timed(0.7) } }
            }
            className="bw-window"
          >
            <WindowBar
              title="Feasibility Dossier"
              subtitle="Bengaluru · 2,450 m²"
              toolbar={
                <span className="bw-window-chip gap-1.5">
                  <span className="text-[11px] font-bold tabular-nums text-bw-accent">87</span>
                  <span className="text-[11px] font-semibold uppercase text-bw-ink-3" style={{ letterSpacing: '0.06em' }}>
                    score
                  </span>
                </span>
              }
            />

            <div className="rounded-b-[14px] bg-bw-porcelain p-3.5">
              {/* Executive quick indicators */}
              <div className="grid grid-cols-3 gap-1.5 mb-2.5 text-center text-[10.5px]">
                <div className="p-1.5 rounded-[7px] bg-bw-surface border border-bw-line-soft">
                  <span className="text-bw-ink-2 block">NBC 2016</span>
                  <span className="font-bold text-bw-green-ink">Compliant</span>
                </div>
                <div className="p-1.5 rounded-[7px] bg-bw-surface border border-bw-line-soft">
                  <span className="text-bw-ink-2 block">IS 1893</span>
                  <span className="font-bold text-bw-ink">Zone III</span>
                </div>
                <div className="p-1.5 rounded-[7px] bg-bw-surface border border-bw-line-soft">
                  <span className="text-bw-ink-2 block">Vastu</span>
                  <span className="font-bold text-bw-accent">88 / 100</span>
                </div>
              </div>

              <ul className="flex flex-col gap-1.5">
                {DOSSIER_ROWS.map((row, i) => (
                  <motion.li
                    key={row.label}
                    initial={{ opacity: 0, x: -8 }}
                    whileInView={{ opacity: 1, x: 0 }}
                    viewport={{ once: true, amount: 0.6 }}
                    transition={{ duration: 0.45, delay: i * 0.07, ease: EASE_APPLE }}
                    className="flex items-center justify-between gap-3 rounded-[9px] border border-bw-line-soft bg-bw-surface px-3 py-2"
                  >
                    <span className="flex items-center gap-2">
                      <span className="flex h-4 w-4 items-center justify-center rounded-full bg-bw-accent-tint text-bw-accent" aria-hidden>
                        <Icon name="check" size={10} strokeWidth={2.4} />
                      </span>
                      <span className="text-[13px] font-semibold text-bw-ink">{row.label}</span>
                    </span>
                    <span className="text-[11px] font-semibold uppercase text-bw-ink-2" style={{ letterSpacing: '0.08em' }}>
                      {row.meta}
                    </span>
                  </motion.li>
                ))}
              </ul>
              <p className="mt-3 flex items-center justify-between rounded-[9px] px-1 text-[12px] text-bw-ink-2">
                <span>PDF · Vector drawings · Room schedule</span>
                <span className="font-semibold text-bw-green-ink">Ready to print</span>
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
    <div className="mx-auto max-w-7xl px-6 py-14 lg:px-10">
      <div className="grid gap-10 lg:grid-cols-[1.2fr_1fr_1fr_1fr]">
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
            AI-powered construction planning and blueprint generation platform. From ideas to intelligent building plans, grounded in codified civil standards.
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

        {/* The index of the #standards sheet: one column per group, in the
            sheet's own order, showing the names without the roles and credits
            the sheet renders in full. */}
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

      <div className="mt-12 flex flex-col gap-3 border-t border-bw-line-soft pt-6 text-[12px] text-bw-ink-2 sm:flex-row sm:items-center sm:justify-between">
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
