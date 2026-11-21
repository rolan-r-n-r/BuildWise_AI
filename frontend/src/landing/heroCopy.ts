/**
 * landing/heroCopy.ts — the hero's first screen, as data.
 *
 * ONE SOURCE, TWO RENDERERS. The strings below are rendered twice: by React in
 * Hero.tsx once the landing route has mounted, and by the BUILD, into
 * index.html as a static shell (the `bw-landing-boot` plugin in vite.config.ts).
 * They live here rather than inline in the JSX so the two renderers cannot drift
 * — a headline edited in one place and not the other would show as a visible
 * text change the moment React replaced the shell.
 *
 * WHY A STATIC SHELL EXISTS AT ALL. The landing is a client-rendered SPA, so
 * nothing in it can paint until ~142 KB gz of JavaScript has been downloaded,
 * parsed, evaluated and rendered. Measured on the mobile preset: FCP 1.7 s, and
 * an LCP of 4.2 s whose breakdown was TTFB 453 ms + **render delay 3 820 ms
 * (89 %)**. The largest paint on the first screen was waiting on the bundle.
 * The shell is the first screen shipped as HTML, so it paints with the document
 * and React adopts the page underneath it; the plugin hides the shell the moment
 * #root has children, and until then it is the hero.
 *
 * WHAT THE SHELL IS NOT. It is not a second design. `firstScreenCss()` is
 * generated from the same tokens Hero.tsx uses, so the two paints are the same
 * pixels; the shell is absolutely positioned and out of flow, so its removal
 * cannot shift anything (CLS stays a property of the reserved boxes). And it
 * carries no focusable nodes, so it cannot add a tab stop.
 *
 * HIDDEN BY DEFAULT, REVEALED BY ROUTE. index.html is one document serving both
 * `/` and `/app`, so the shell is in the HTML for both — which means the default
 * state has to be `display: none` and the LANDING route has to be what turns it
 * on. The alternative (visible by default, hidden on the landing) would have put
 * a marketing hero on top of the application for every /app visitor. The switch
 * is the `bw-boot-landing` class the boot script adds to <html> in the head, on
 * `/` only, before anything paints.
 */
/* `./theme.ts` carries its extension on purpose: this module is also imported by
   vite.config.ts, which is typechecked under `moduleResolution: nodenext` and
   therefore requires explicit extensions. theme.ts itself imports nothing, so
   the chain stops there and no other import in the landing has to change. */
import { LANDING } from './theme.ts';

/** The first screen's copy. Whitespace-significant characters are explicit. */
export const HERO_COPY = {
  eyebrow: 'BuildWise · AI Construction Planning & Blueprint Platform',
  headlineFirst: 'From ideas to',
  /**
   * The LEADING SPACE IS LOAD-BEARING. Each headline fragment is its own
   * `display: block` span, so at the end of a line a space would be collapsed
   * away visually — but `textContent` (what a screen reader reads, and what
   * selecting the headline to copy produces) contains no line break at all.
   * A block-level leading space collapses under `white-space: normal`, so this
   * changes nothing that is rendered visually.
   */
  headlineSecondLead: ' ',
  headlineSecondAccent: 'intelligent building plans',
  headlineSecondTrail: '.',
  subcopy:
    'BuildWise is an AI-powered construction planning and blueprint generation platform. ' +
    'From ideas to intelligent building plans: architects, civil engineers, builders, and landowners draw a plot on the map ' +
    'to generate construction blueprints, elemental cost estimates, material requirements, and a\u00a0complete IS 1893 site feasibility dossier.',
} as const;

/** Display stack, mirroring FONT_DISPLAY in theme.ts (the landing's `font-sans`). */
const FONT_STACK =
  "-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Inter', 'Segoe UI', Roboto, sans-serif";

/**
 * Critical CSS for the shell.
 *
 * This is deliberately NOT the app's stylesheet. The shell has to be able to
 * paint before that stylesheet exists, which is what makes the plugin free to
 * stop the landing's first paint from waiting on 17.6 KB gz of Tailwind. Only
 * the first screen's own rules are here, all of them derived from `LANDING`.
 */
export function firstScreenCss(): string {
  // Every rule is scoped to the landing route; the shell is `display:none`
  // anywhere else (see the note above).
  const p = 'html.bw-boot-landing [data-boot-hero]';
  return `
${p}{display:block;position:absolute;top:0;left:0;right:0;z-index:1;font-family:${FONT_STACK};color:${LANDING.color.ink}}
${p} .bh-wrap{margin:0 auto;max-width:80rem;padding:8rem 1.5rem 5rem}
${p} .bh-h1{margin:0;font-size:${LANDING.type.hero};font-weight:700;letter-spacing:${LANDING.type.trackingHero};line-height:1.04;color:${LANDING.color.ink}}
${p} .bh-h1 span{display:block}
${p} .bh-sub{margin:1.5rem 0 0;max-width:38rem;font-size:17px;line-height:1.6;color:${LANDING.color.slate}}
[data-boot-hero]{display:none}
@media (min-width:640px){${p} .bh-wrap{padding-top:9rem}}
@media (min-width:1024px){${p} .bh-wrap{padding:10rem 2.5rem 5rem}}
/* THE SWAP IS CSS, NOT A TIMER. The :has() selector below is true the instant
   React has committed a child, so the shell leaves in the SAME style
   recalculation the real hero arrives in — one paint, no frame where both exist,
   and nothing to fail.

   The first version did this from a MutationObserver in a head script, and it
   never fired: that script ran while the document was still in the head, so the
   shell element it looked for did not exist yet, the whole block was skipped,
   and the shell stayed visible UNDER the real hero for the life of the page —
   a duplicated headline, found by the evidence harness rather than by looking at
   it. :has() is the mechanism now (Chrome 105+, Safari 15.4+, Firefox 121+);
   the boot script keeps an observer as a fallback for engines without it.

   visibility, not display, so the element is never removed: an LCP candidate
   that leaves the DOM invalidates the paint it already earned. */
${p}[data-boot-done],
html.bw-boot-landing:has(#root > *) [data-boot-hero]{visibility:hidden}
html.bw-boot-landing,html.bw-boot-landing body{background-color:${LANDING.color.porcelain1}}
@media (prefers-color-scheme: dark){html.bw-boot-landing:not([data-theme='light']),html.bw-boot-landing:not([data-theme='light']) body{background-color:rgb(9,13,22)}html.bw-boot-landing:not([data-theme='light']) [data-boot-hero]{color:rgb(248,250,252)}html.bw-boot-landing:not([data-theme='light']) .bh-h1{color:rgb(248,250,252)}html.bw-boot-landing:not([data-theme='light']) .bh-sub{color:rgb(148,163,184)}}
html.bw-boot-landing[data-theme='dark'],html.bw-boot-landing[data-theme='dark'] body,html.bw-boot-landing.dark,html.bw-boot-landing.dark body{background-color:rgb(9,13,22)}
html.bw-boot-landing[data-theme='dark'] [data-boot-hero],html.bw-boot-landing.dark [data-boot-hero]{color:rgb(248,250,252)}
html.bw-boot-landing[data-theme='dark'] .bh-h1,html.bw-boot-landing.dark .bh-h1{color:rgb(248,250,252)}
html.bw-boot-landing[data-theme='dark'] .bh-sub,html.bw-boot-landing.dark .bh-sub{color:rgb(148,163,184)}
/* RESERVE THE SCROLLBAR GUTTER FROM THE FIRST LAYOUT. The landing paints one
   screen tall (this shell) and then React fills in ~3 300px of content, so on a
   platform with CLASSIC scrollbars the scrollbar does not exist at first paint
   and does exist a moment later — which takes 15px off the layout width and
   slides every centred column left by half of it. Lighthouse's desktop run
   measured that as the landing's only layout shift (CLS 0.011, attributed to the
   hero's own container), and it is invisible to any test run on a platform with
   overlay scrollbars, which is why five puppeteer viewports and the mobile
   Lighthouse run all read 0.000. Reserving the gutter here — in the boot CSS,
   which is in the head and in force before the first layout — means the width
   never changes, so nothing moves when the content arrives. */
html.bw-boot-landing{scrollbar-gutter:stable}`.trim();
}

/** The shell markup. Text is escaped — this string is written into the document verbatim. */
export function firstScreenHtml(): string {
  const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const c = HERO_COPY;
  return (
    `<div data-boot-hero><div class="bh-wrap">` +
    `<h1 class="bh-h1"><span>${esc(c.headlineFirst)}</span>` +
    `<span>${esc(c.headlineSecondLead)}<span>${esc(c.headlineSecondAccent)}</span>${esc(c.headlineSecondTrail)}</span></h1>` +
    `<p class="bh-sub">${esc(c.subcopy)}</p>` +
    `</div></div>`
  );
}
