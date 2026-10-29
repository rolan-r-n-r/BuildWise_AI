/**
 * preview/PreviewTrace.tsx — the route shell for the centrepiece prototype.
 *
 * DELIBERATELY UNLINKED AND `noindex`. Nothing in the landing, the nav or the
 * footer points here; the route exists so the idea can be reviewed on a real
 * device at a real address, and it is excluded from indexing two ways — a
 * `robots` meta tag set when this route mounts, and `public/robots.txt`
 * disallowing `/preview/`. It ships as its own lazy chunk, so `/` and `/app` pay
 * nothing for it while it is being decided on.
 *
 * WHY IT REUSES THE LANDING'S MATERIAL LAYER. It wears the same `--bw-*` tokens,
 * the same `bw-surface` hairline and the same `bw-window` chrome as the marketing
 * page, because the question this prototype answers is not "can this be built"
 * but "does this belong on THAT page" — and that question can only be answered
 * against the page's own materials.
 */
import React, { useEffect } from 'react';
import { TraceStage } from './TraceStage';
import { APP_PATH, LANDING_PATH, navigate } from '../landing/router';
import { Icon } from '../components/Icon';

const TITLE = 'Trace stage — centrepiece prototype (unlinked)';

export const PreviewTrace: React.FC = () => {
  useEffect(() => {
    document.title = TITLE;
    document.body.classList.add('bw-landing-open');
    document.documentElement.classList.add('bw-landing-open');
    /* noindex, applied at runtime because index.html is one document serving
       every route and a static tag there would de-index the landing too. */
    const meta = document.createElement('meta');
    meta.name = 'robots';
    meta.content = 'noindex, nofollow';
    document.head.appendChild(meta);
    return () => {
      document.body.classList.remove('bw-landing-open');
      document.documentElement.classList.remove('bw-landing-open');
      meta.remove();
      window.scrollTo(0, 0);
    };
  }, []);

  return (
    <div className="bw-landing min-h-screen font-sans text-bw-ink antialiased">
      <header className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-6 pb-2 pt-6 lg:px-10">
        <button
          type="button"
          onClick={() => navigate(LANDING_PATH)}
          className="group inline-flex h-9 items-center gap-1.5 rounded-full border border-bw-line bg-white px-3.5 text-[13px] font-semibold text-bw-ink transition-colors hover:bg-bw-line-soft"
        >
          {/* The icon set has one chevron; the back state is the same glyph turned,
              which keeps the two directions the same weight. */}
          <span
            aria-hidden
            className="rotate-180 transition-transform duration-200 group-hover:-translate-x-0.5 motion-reduce:transform-none"
          >
            <Icon name="chevron-right" size={14} />
          </span>
          Landing
        </button>
        <span className="inline-flex h-9 items-center gap-2 rounded-full border border-bw-amber/40 bg-bw-amber/[0.08] px-3 text-[12px] font-semibold text-bw-amber-ink">
          <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-bw-amber" />
          Prototype · unlinked · noindex
        </span>
        <span className="ml-auto hidden text-[12px] text-bw-ink-2 sm:block">
          Centrepiece option (a), rendered as option (c)
        </span>
      </header>

      <main className="mx-auto max-w-7xl px-6 pb-24 pt-6 lg:px-10">
        {/* The route's own H1, INSIDE `main` — the stage below is a section with
            an H2. The page needs exactly one top-level heading, and the stage must
            not be it: the same stage becomes a section of the landing page, where
            the H1 belongs to the hero. (A page-level heading that sat between
            `<header>` and `<main>` was axe's `region` violation — content outside
            every landmark.) */}
        <h1 className="max-w-3xl text-[clamp(1.5rem,2.7vw,2.15rem)] font-bold tracking-[-0.03em] text-bw-ink">
          The trace stage — the centrepiece prototype.
        </h1>
        <p className="mt-3 max-w-2xl text-[14.5px] leading-[1.6] text-bw-ink-2">
          One plot, two real engine generations, and the product's own measurements. Everything here is reviewed
          against the landing page's materials before it is allowed anywhere near them.
        </p>

        <div className="mt-10">
          <TraceStage />
        </div>
      </main>

      <footer className="border-t border-bw-line-soft bg-white/70">
        <div className="mx-auto grid max-w-7xl gap-8 px-6 py-10 lg:grid-cols-[1.4fr_1fr_1fr] lg:px-10">
          <div>
            <p className="text-[12px] font-semibold uppercase text-bw-ink-2" style={{ letterSpacing: '0.14em' }}>
              What this prototype claims
            </p>
            <ul className="mt-3 flex flex-col gap-2 text-[12.5px] leading-[1.55] text-bw-ink-2">
              <li>Area, perimeter, shape class, edge bearings and the EC gate: computed by the SHIPPED client module — no re-implementation.</li>
              <li>Setback band, buildable polygon, footprint, floors, shafts and zones: copied out of real engine captures.</li>
              <li>Nothing here implies a client-side statutory solver. Server-derivation is named where it happens.</li>
            </ul>
          </div>
          <div>
            <p className="text-[12px] font-semibold uppercase text-bw-ink-2" style={{ letterSpacing: '0.14em' }}>
              What it does not claim
            </p>
            <ul className="mt-3 flex flex-col gap-2 text-[12.5px] leading-[1.55] text-bw-ink-2">
              <li>No certificate all-PASS claim: both captures are WARN and the layer chips say so.</li>
              <li>No 3D viewer of the product: there is no orbit, no walkthrough, no mesh in the shipped tool.</li>
              <li>No invented figures. Every number traces to a capture or to the shared geometry module.</li>
            </ul>
          </div>
          <div>
            <p className="text-[12px] font-semibold uppercase text-bw-ink-2" style={{ letterSpacing: '0.14em' }}>
              Continue
            </p>
            <button
              type="button"
              onClick={() => navigate(`${APP_PATH}?start=capture`)}
              className="mt-3 inline-flex h-10 items-center gap-2 rounded-full bg-bw-ink px-4 text-[13.5px] font-semibold text-white transition-colors hover:bg-bw-ink-hover"
            >
              Open the real trace tool
              <span aria-hidden>
                <Icon name="chevron-right" size={14} />
              </span>
            </button>
            <p className="mt-3 text-[11.5px] leading-[1.55] text-bw-ink-2">
              The same URL the landing's primary CTA uses: <span className="font-mono">/app?start=capture</span>
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default PreviewTrace;
