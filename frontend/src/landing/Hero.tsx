/**
 * Hero.tsx — the marketing page's first screen.
 *
 * WHAT THIS FILE IS. The landing's first screen, as a copy-led statement: eyebrow,
 * headline, subcopy, the two calls to action and the spec bar. There is no stage
 * under it, and there is nothing here to reserve a box for. The scenic photograph,
 * its two scrims, the filmic grain layer and the 90-second mist loop were removed
 * first, and their combined cost went with them: the mobile trace measured that
 * preloaded 565 KB JPEG as the LCP element at 7.7 s, and measured the mist loop
 * as roughly doubling the per-frame interval during scroll.
 *
 * TWO 3D HEROES WERE BUILT OUT OF THIS FILE AND BOTH WERE REMOVED, FOR DIFFERENT
 * REASONS. The first was a live WebGL massing model — orbit, drag, hotspots — which
 * implied a 3D architectural viewer the product does not ship, and printed the
 * sample's certificate WARN state under the heading of a product statistic. The
 * second was a scroll-driven CSS-3D corridor of real engine sheets: it claimed no
 * feature the product lacks, but it read cheap and spent 300vh of the reader's
 * attention on itself. Both were parked under `frontend/quarantine/landing-3d/` — and
 * that folder has since been deleted, so neither survives anywhere but this note — and
 * this file is the baseline they were measured against.
 *
 * THE THIRD CENTREPIECE IS BELOW THE SPEC BAR, AND IT ANSWERS BOTH FAILURES. It is
 * `HeroModel.tsx`: a transform-only massing of one captured generation, standing ON
 * the plot rather than floating in a viewer (no orbit, no canvas, no GPU library),
 * one screen tall with no pinning (no runway), and it claims nothing the engine did
 * not return — the storeys are its envelopes, the openings on the facades are its
 * window schedule, and the caption prints the generation id and the certificate it
 * actually returned, WARN layers included. The copy above still paints with the
 * document and is still the whole first screen; the model is the second beat, and a
 * reader who never scrolls past it has lost nothing.
 *
 * COPY. The subcopy leads with the artefact and names who it is for. The previous
 * line ("AI-powered site feasibility, risk analysis, cost estimation, and
 * generative architectural planning — one pin on a map, one report you can build
 * from") was a 26-word clause stack that named the category but left the reader's
 * own situation and the thing they receive until the very last clause. The
 * strings themselves live in `heroCopy.ts`, because the build renders this same
 * first screen into index.html as a static shell — see the note above.
 *
 * CTA. `Trace your site` is a real `<a href="/app?start=capture">` — it works with
 * JavaScript off, it can be middle-clicked into a tab, and `/app` opens the
 * capture wizard from that parameter. A plain left click is upgraded to the SPA's
 * own pushState navigation so the reader is not made to wait for a document load
 * the router can do itself.
 *
 * WHY THE HEADLINE HAS NO ENTRANCE ANIMATION. It had one: the eyebrow, the h1
 * (each line translated 112% inside an `overflow-hidden` clip) and the subcopy
 * each started at `opacity: 0` and animated in. Every one of those is the LCP
 * candidate at some viewport, and an element that is transparent or clipped out
 * of its box is NOT PAINTED — so the browser could not record the largest
 * contentful paint until a JavaScript animation ran. Measured consequence at the
 * mobile preset: LCP 6.3 s against an FCP of 1.7 s, on a page whose first screen
 * is text that had been in the HTML all along. On a phone that is not an
 * animation, it is three seconds of an empty first screen. The copy now paints
 * with the document and only the things BELOW it (CTA row, spec bar, stage,
 * ledger) animate — none of them can hold the LCP hostage.
 */
import React, { useRef } from 'react';
import { motion, useReducedMotion, useTransform } from 'framer-motion';
import { useDampedFollow, useOnScreen } from './interaction';
import { timed } from './motion';
import { useDrift, usePageScroll } from './scrollLink';
import { APP_PATH, currentPath, navigate } from './router';
import { scrollToId } from './scroll';
import { Icon } from '../components/Icon';
import { LANDING } from './theme';
import { HERO_COPY } from './heroCopy';
import { oneLine } from './standards';
import { HeroModel } from './HeroModel';
import { Bearing } from './Bearing';

/** The primary CTA's destination: the app, with the capture wizard asked for. */
export const CAPTURE_HREF = `${APP_PATH}?start=capture`;

/** One fact in the hero's spec bar. */
interface Spec {
  label: string;
  value: string;
}

/* The first two facts are the same list the #standards sheet renders and the
   footer indexes, joined from landing/standards.ts rather than retyped here. */
const SPECS: ReadonlyArray<Spec> = [
  { label: 'Standards', value: oneLine('standards') },
  { label: 'Site data', value: oneLine('siteData') },
  { label: 'Cost to run', value: 'No paid API keys' },
];

export const Hero: React.FC = () => {
  const reduced = useReducedMotion();

  /* The copy column's share of the scroll. The model below is scrubbed by the
     same wheel, so the two layers separate as the reader descends — the copy on
     the near plane, the plot gaining height behind it. `useDrift` rounds to
     whole pixels so the type never resamples across subpixels. */
  const { scrollY, progress } = usePageScroll();
  const copyDrift = useDrift(scrollY, -0.045);
  const copyY = useTransform(copyDrift, (v) => (reduced ? 0 : v));

  /* The site-bearing dial's card turns with the WHOLE document, so it follows
     the page's progress rather than a band of its own — through the damped
     follow, so it trails the wheel by ~0.4s and eases into its angle after a
     fling instead of being pinned to the scrollbar. `enabled` on visibility is
     the idle contract: once the first screen is behind the reader the loop is
     off, and the dial keeps whatever angle it reached. */
  const heroRef = useRef<HTMLElement>(null);
  const heroOnScreen = useOnScreen(heroRef, '10% 0px');
  const dialProgress = useDampedFollow(progress, { enabled: heroOnScreen });

  /**
   * Real anchor, SPA speed. Only an unmodified primary click is intercepted:
   * middle-click, ⌘/Ctrl-click and "open in new tab" keep the browser's own
   * behaviour, because the href is real and always was.
   */
  const onPrimaryClick = (event: React.MouseEvent<HTMLAnchorElement>) => {
    if (event.defaultPrevented) return;
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (currentPath().startsWith(APP_PATH)) return;
    event.preventDefault();
    navigate(CAPTURE_HREF);
  };

  /* The first screen's instrument. One element, one mount: it is the TOP of the
     right-hand column at every width where that column exists (lg and up), so it
     cannot be present in one layout and absent in the next — the earlier version
     was an absolutely-positioned dial that switched off at `xl`, which meant the
     same page showed a bearing dial at 1265px and none at 1440px. */
  const siteBearing = (
    <Bearing
      progress={dialProgress}
      sweep={72}
      bearing={42}
      caption="Site bearing"
      footnote="Datum WGS 84"
      readout
      dialOpacity={0.5}
      className="text-bw-accent"
    />
  );

  return (
    <section
      ref={heroRef}
      id="top"
      className="relative overflow-hidden"
      aria-label="BuildWise AI — intelligent construction planning"
    >
      <div className="relative mx-auto max-w-7xl px-6 pb-20 pt-32 sm:pt-36 lg:px-10 lg:pt-40">
        {/* The copy column takes a small share of the scroll (0.045x) so the
            first screen has depth against the model below it, which is the
            thing the scrub actually builds. Transform-only: no layout, no
            repaint, and reduced motion pins it at 0. */}
        <motion.div
          className="lg:grid lg:grid-cols-12 lg:items-center lg:gap-x-12"
          style={{ y: copyY }}
        >
          <div className="lg:col-span-8">
            <p className="inline-flex h-8 items-center gap-2 rounded-full border border-bw-line bg-bw-surface pl-2.5 pr-3.5 text-bw-ink-2">
              <span aria-hidden className="h-[6px] w-[6px] shrink-0 rounded-full bg-bw-accent" />
              <span
                className="text-[11px] font-semibold uppercase"
                style={{ letterSpacing: LANDING.type.trackingEyebrow }}
              >
                {HERO_COPY.eyebrow}
              </span>
            </p>

            <h1
              className="mt-6 font-bold text-bw-ink"
              style={{ fontSize: LANDING.type.hero, letterSpacing: LANDING.type.trackingHero, lineHeight: 1.04 }}
            >
              <span className="block">{HERO_COPY.headlineFirst}</span>
              <span className="block">
                {HERO_COPY.headlineSecondLead}
                <span className="bw-gradient-text">{HERO_COPY.headlineSecondAccent}</span>
                {HERO_COPY.headlineSecondTrail}
              </span>
            </h1>

            <p className="mt-6 max-w-[38rem] text-[17px] leading-[1.6] text-bw-ink-2">
              {HERO_COPY.subcopy}
            </p>

            {/* CTA row. Full-width below `sm`: two buttons of different widths stacked
                on a phone leave the primary action narrower than the eye expects. */}
            <div className="mt-9 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
              <motion.a
                href={CAPTURE_HREF}
                onClick={onPrimaryClick}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={reduced ? timed(0.3, 0.5) : { type: 'spring', stiffness: 320, damping: 26, delay: 0.54 }}
                className="group inline-flex h-12 w-full items-center justify-center gap-2 rounded-full bg-bw-cta px-6 text-[15px] font-semibold text-bw-cta-ink transition-[background-color,transform] duration-200 hover:bg-bw-cta-hover active:scale-[0.98] sm:w-auto"
                style={{ boxShadow: LANDING.shadow.dark }}
              >
                Trace your site
                <span aria-hidden className="transition-transform duration-200 group-hover:translate-x-1 motion-reduce:transform-none">
                  <Icon name="chevron-right" size={15} />
                </span>
              </motion.a>

              <motion.button
                type="button"
                onClick={() => scrollToId('capabilities')}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={reduced ? timed(0.3, 0.6) : { type: 'spring', stiffness: 320, damping: 26, delay: 0.62 }}
                className="group inline-flex h-12 w-full items-center justify-center gap-2 rounded-full border border-bw-line bg-bw-surface px-5 text-[15px] font-semibold text-bw-ink transition-[background-color,border-color,transform] duration-200 hover:bg-bw-line-soft active:scale-[0.98] sm:w-auto"
              >
                <span aria-hidden className="transition-transform duration-200 group-hover:translate-y-0.5 motion-reduce:transform-none">
                  <Icon name="chevron-down" size={15} />
                </span>
                See the platform
              </motion.button>
            </div>

  
          </div>

        {/* THE RIGHT-HAND COLUMN — dial over spec bar, at every width from `lg`.
            Below `lg` the two halves are still one flow: the spec bar is the
            three-up row it always was, under the copy.

            WHY THE DIAL IS IN THE COLUMN AND NOT ABSOLUTE. It was an
            absolutely-placed dial over the empty right third of the
            sub-`xl` layout, which left the page with an instrument at 1265px and
            none at 1440px — the same page, two products. Giving the column a
            real occupant at every one of its widths is what makes the first
            screen complete rather than patched: measured at 1440px, the spec
            list used to hang on a 440px-tall divider with 300px of bare paper
            above it. */}
        <div className="mt-12 max-w-4xl lg:col-span-4 lg:col-start-9 lg:mt-0 lg:flex lg:max-w-none lg:flex-col lg:justify-center lg:gap-7 lg:self-stretch lg:border-l lg:border-bw-line lg:pl-8">
          <div className="pointer-events-none hidden w-[min(100%,264px)] lg:block xl:w-[min(100%,300px)]">{siteBearing}</div>

          {/* Spec bar — the three facts that decide a technical evaluation. */}
          <motion.dl
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={timed(0.6, 0.7)}
            className="grid gap-x-10 gap-y-6 border-t border-bw-line pt-7 sm:grid-cols-3 lg:grid-cols-1 lg:gap-y-7 lg:border-t-0 lg:pt-0"
          >
            {SPECS.map((spec) => (
              <div key={spec.label}>
                {/* `text-bw-ink-2`, not ink-3: at 10.5px uppercase this label is small
                    text under WCAG, and `--bw-ink-3` (#6b7787) resolves to 4.05:1 on the
                    porcelain ground — a real axe failure on the page's first screen.
                    `--bw-ink-2` (#46536a) is 6.9:1 on the same ground and is already the
                    colour of the values beside these labels, so the pair still reads as
                    one unit rather than as two. */}
                <dt className="text-[10.5px] font-semibold uppercase text-bw-ink-2" style={{ letterSpacing: '0.14em' }}>
                  {spec.label}
                </dt>
                <dd className="mt-1.5 text-[13.5px] font-medium leading-[1.5] text-bw-ink-2">{spec.value}</dd>
              </div>
            ))}
          </motion.dl>
        </div>
        </motion.div>

        {/* ---------------- the second beat: the plot, extruded ---------------- */}
        <div className="mt-16 flex flex-col gap-4 border-t border-bw-line pt-8 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p
              className="flex items-center gap-3 text-[11px] font-semibold uppercase text-bw-ink-2"
              style={{ letterSpacing: '0.16em' }}
            >
              <span aria-hidden className="h-[1.5px] w-7 rounded-full bg-bw-accent" />
              From the capture
            </p>
            {/* An h2, not a decorative line: this is the page's second subject, and
                the landing audit checks the heading order rather than the styling. */}
            <h2 className="mt-2.5 text-[clamp(1.35rem,2.2vw,1.8rem)] font-bold tracking-[-0.03em] text-bw-ink">
              The plot, extruded
            </h2>
          </div>
          <p className="max-w-sm text-[13px] leading-[1.6] text-bw-ink-2">
            The first floor rises as you scroll and the roof lands on it. Every opening on it is one the engine
            placed; the figures under the drawing are the capture's own.
          </p>
        </div>
        <div className="mt-6">
          <HeroModel />
        </div>

      </div>
    </section>
  );
};
