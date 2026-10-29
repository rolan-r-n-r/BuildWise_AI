/**
 * StandardsSection.tsx — what the engine implements, and on what data.
 *
 * WHY THIS EXISTS. The nav's "Standards" link pointed at the footer, and the
 * closing band's "Standards and data" button pointed there too — while sitting
 * directly above it. Measured: that button moved the page 67px, because the
 * footer was already on screen. A control that promises a destination and moves
 * the page 67px reads as broken, and the fault was the label: it named a
 * SECTION THE PAGE DID NOT HAVE. This section is that destination — mid-page,
 * so both doorways can actually travel to it — and it carries the two things a
 * technical reader evaluates before believing any of the numbers above:
 * which code the calculations answer to, and whose data feeds them.
 *
 * IT IS THE DETAIL VIEW OF ONE LIST. The rows come from landing/standards.ts,
 * which also feeds the footer's three columns and the hero's spec bar. This file
 * used to hold its own copy of the facts, and the footer held a second: the
 * footer credited "Esri World Imagery / Copernicus Sentinel-2 / OpenTopoMap
 * terrain" while this sheet merged those three into the single row "Esri,
 * Sentinel-2, OpenTopoMap" — under a caption, "Open data", that was wrong for
 * all three of them (see the module's header). The sheet is where the detail
 * belongs, so it renders more per group than the footer does, not different
 * facts.
 *
 * THREE GROUPS, THREE DENSITIES OF THE SAME LIST: the codes the engine answers
 * to, the open data it measures with, and the imagery it draws on — the same
 * three columns the footer summarises, in the same order, plus each source's
 * own credit line. Provenance is the one place on a marketing page where a
 * table beats a paragraph, and a table with rows missing their rights column is
 * not a table: the closing sentence that used to do that job by hand covered
 * four of the seven providers and waved the rest through ("provider terms for
 * the basemaps"). A credit per row cannot go stale the way a summary sentence
 * can.
 *
 * The entrance follows the sheet's own logic — the caption, then the rows one
 * at a time, each on the tighter reveal (fadeRiseTight) because a 44px row
 * travelling 20px would look like the list coming apart. The three lists do
 * this in parallel, so the section assembles as three columns filing themselves
 * in rather than as one block arriving.
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

const SpecList: React.FC<{ group: SourceGroup; rows: ReadonlyArray<Source> }> = ({ group, rows }) => (
  /* A stagger group of its own: the caption, then each row. The `dl` between
     them is a plain element, which variant propagation passes straight through,
     so the rows still count as children of this motion.div. */
  <motion.div variants={staggerParent(0.05)}>
    {/* ink-2, not ink-3: at 10.5px uppercase this caption is small text under WCAG,
        and `--bw-ink-3` is 4.05:1 on the porcelain ground (it only clears 4.5:1 on
        white). Axe flagged these three captions at every width. */}
    <motion.h3
      variants={fadeRise}
      className="text-[10.5px] font-semibold uppercase text-bw-ink-2"
      style={{ letterSpacing: '0.14em' }}
    >
      {GROUP_LABELS[group]}
    </motion.h3>
    <dl className="mt-4 border-t border-bw-line-soft">
      {rows.map((row) => (
        <motion.div
          key={row.name}
          variants={fadeRiseTight}
          /* Three lines a row rather than the old name-left/role-right pair: the
             row has to carry its credit, and in a third-width column there is no
             room left for a two-column line. The hairline between rows is what
             keeps it reading as a table. */
          className="border-b border-bw-line-soft py-3.5"
        >
          <dt className="text-[13.5px] font-semibold text-bw-ink">{row.name}</dt>
          <dd className="mt-0.5 text-[13px] leading-[1.5] text-bw-ink-2">{row.role}</dd>
          <dd className="mt-1.5 text-[11.5px] leading-[1.5] text-bw-ink-3">{row.credit}</dd>
        </motion.div>
      ))}
    </dl>
  </motion.div>
);

export const StandardsSection: React.FC = () => {
  /* The header row's own entry band, shared by one instrument: the sheet's dial
     turns as this section arrives and comes to rest as the heading settles at the
     reading position.

     WHY THE SCRUB ENGINE RATHER THAN THE RAW BAND VALUE. `useEntryProgress` hands
     the rotation straight to the wheel, so the dial is a mirror of the scrollbar:
     it starts and stops with the wheel, and a fling snaps it to its end angle.
     The dial is the page's largest moving mass, and a mass that changes direction
     at the speed of the wheel reads as a spinner rather than as an instrument.
     `useDampedScrub` follows the same band through an exponential approach (see
     `dampedFollow`), so the card trails the hand slightly, carries a little way
     after the reader stops and settles into its bearing — no overshoot, because
     the engine uses a damped follow and not a spring, exactly for the reason
     springs.ts records for scrub values.

     `tau` 0.13s: the default 0.09 is tuned for a 6 m storey rising 30 px; this is
     a 200 px dial, so it gets a touch more mass and is back at rest ~0.4s after
     the wheel stops. `enabled` on visibility is the idle contract for scroll scrub — an
     off-screen instrument runs no animation frame and reads no geometry. */
  const sectionRef = useRef<HTMLDivElement>(null);
  const onScreen = useOnScreen(sectionRef);
  const entry = useDampedScrub(sectionRef, { enabled: onScreen, tau: 0.13 });

  return (
  <section id="standards" aria-label="Standards and data sources" className="scroll-mt-24 py-24 sm:py-28">
    <div ref={sectionRef} className="mx-auto max-w-7xl px-6 lg:px-10">
      <motion.div variants={staggerParent(0.12)} initial="hidden" whileInView="show" viewport={SETTLE_VIEWPORT}>
        {/* "code and named sources", not "code and open data": the sheet below
            credits a copyrighted publication publisher (BIS, CPWD) and a
            commercially licensed basemap (Esri), so "open data" was true of one
            of its three columns. The claim it replaces is the weaker one to
            make and the harder one to defend on a page like this. */}
        <div className="flex items-start justify-between gap-10">
          <div className="min-w-0">
            <SectionHeading
              eyebrow="Standards and data"
              title="Grounded in code and named sources"
              copy="Every figure in a dossier traces back to a published standard or a named dataset. Nothing is a black box, and nothing is behind a paid key."
            />
          </div>
          {/* The header's empty right column, carrying the section's own
              instrument: a dial that turns as the sheet arrives, captioned with
              the codes the rows below are cited against. Decorative, so it
              takes no tab stop and announces nothing — the facts it gestures at
              are the three lists underneath, which are real content. */}
          <div className="pointer-events-none hidden w-[clamp(152px,15vw,200px)] shrink-0 lg:block">
            <Bearing
              progress={entry}
              sweep={-58}
              counterSweep={108}
              bearing={189}
              caption="Survey datum"
              footnote="IS 1893 · NBC 2016"
              dialOpacity={0.62}
              className="text-bw-accent"
            />
          </div>
        </div>
        {/* Same drawn boundary as the capabilities grid: the rule is the section
            edge, and it reports the reader's travel as it draws. */}
        <ScrollRule className="mt-10" />
        <p
          data-testid="landing-certified-definition"
          className="mt-4 max-w-3xl text-[12.5px] leading-relaxed text-[var(--text-2)]"
        >
          {CERTIFIED_DEFINITION}
        </p>
        <div className="mt-8 grid gap-x-12 gap-y-10 md:grid-cols-2 lg:grid-cols-3">
          {GROUP_ORDER.map((group) => (
            <SpecList key={group} group={group} rows={sourcesIn(group)} />
          ))}
        </div>
        {/* The credits above are the sheet's; this line says where the same
            obligations are discharged in the product — the map's own attribution
            bar (MapCanvas) and each dossier's data sources panel
            (DataSourcesDisclosure, rendered per analysis tab in ReportSheet). */}
        <motion.p variants={fadeRise} className="mt-9 text-[12.5px] leading-[1.6] text-bw-ink-3">
          Attribution travels with the data: the map carries its own basemap credits, and every
          dossier carries a data sources panel.
        </motion.p>
      </motion.div>
    </div>
  </section>
  );
};
