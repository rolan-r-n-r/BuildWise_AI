/**
 * Navbar.tsx — floating glass pill navigation.
 *
 * Three things this file deliberately does NOT do any more:
 *
 *  1. It does not render on scroll. The condensed state used to be React state
 *     driven by framer-motion's scroll listener (setState inside a scroll
 *     frame); it is now a `data-condensed` attribute toggled straight on the
 *     DOM by one rAF-throttled passive listener, with the two visual states
 *     declared in CSS. Scrolling the page costs one style recalc of one
 *     element instead of a React commit.
 *  2. It does not underline links on hover. Hover reveals the label; the
 *     PILL behind the label marks where you are. Two indicators for one
 *     question made the section marker read as decoration.
 *  3. It does not link to destinations that do not exist. The old row pointed
 *     "Blueprint" and "Reports" at a section and a card nested inside that same
 *     section — two links, one place. Every link here names a section the page
 *     actually has.
 *
 * The section marker itself is discovered by an IntersectionObserver watching a
 * thin band across the middle of the viewport, so it stays correct without any
 * per-scroll hit-testing.
 */
import React, { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { EASE_APPLE, SPRING_SOFT } from './motion';
import { scrollToId } from './scroll';
import { APP_PATH, SIGN_IN_PATH, navigate } from './router';
import { Icon } from '../components/Icon';
import { LANDING } from './theme';
/* The brandmark is imported from landing/logo.ts, which owns the two density
   files and the note on why the 512 px master is not used. */
import { LOGO_SRC, LOGO_SRCSET } from './logo';

/* Listed in PAGE ORDER, which is the same order the scroll-spy reads them in
   when it decides which section is current. "Standards" used to target the
   footer — a summary of its own content, and, from the closing band's button,
   a target that was already on screen. It now targets the #standards section
   the page actually has, which is also why it moved ahead of Blueprint: the
   nav order must match the document order or the marker lies.

   "Platform" used to lead this list, pointing at the product-preview section
   between the hero and the capabilities. That section has been removed (see
   LandingPage), and an item pointing at a section that no longer exists is a
   link to nothing, so the item went with it rather than being re-pointed at a
   neighbouring section under a label that would then be wrong. */
const LINKS: ReadonlyArray<{ label: string; target: string }> = [
  { label: 'Capabilities', target: 'capabilities' },
  { label: 'Standards', target: 'standards' },
  { label: 'Blueprint', target: 'blueprint' },
];

/**
 * MenuIcon — three-line hamburger that morphs into an x.
 * Integer-pixel geometry only (16px box, 2px lines, 4px gaps): fractional
 * offsets snap differently at each device pixel ratio and render as uneven
 * spacing, so every value here stays on the whole-pixel grid.
 */
const MenuIcon: React.FC<{ open: boolean }> = ({ open }) => (
  <span aria-hidden className="flex h-4 w-4 flex-col items-center justify-center gap-[4px]">
    {/* Top line to upper-right arm of the x (drops 6px, rotates 45deg) */}
    <motion.span
      className="block h-[2px] w-full rounded-full bg-current"
      initial={false}
      animate={open ? { rotate: 45, y: 6 } : { rotate: 0, y: 0 }}
      transition={{ duration: 0.2, ease: EASE_APPLE }}
    />
    {/* Middle line fades away as the x takes shape */}
    <motion.span
      className="block h-[2px] w-full rounded-full bg-current"
      initial={false}
      animate={open ? { opacity: 0, x: -2 } : { opacity: 1, x: 0 }}
      transition={{ duration: 0.15, ease: EASE_APPLE }}
    />
    {/* Bottom line to lower-right arm of the x (rises 6px, rotates -45deg) */}
    <motion.span
      className="block h-[2px] w-full rounded-full bg-current"
      initial={false}
      animate={open ? { rotate: -45, y: -6 } : { rotate: 0, y: 0 }}
      transition={{ duration: 0.2, ease: EASE_APPLE }}
    />
  </span>
);

export const Navbar: React.FC = () => {
  const [menuOpen, setMenuOpen] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const navRef = useRef<HTMLElement>(null);

  /* Condense the pill past the hero's first 24px of scroll. Written directly to
     the DOM (no state) and throttled to one rAF per scroll burst. */
  useEffect(() => {
    const el = navRef.current;
    if (!el) return;
    let raf = 0;
    const apply = () => {
      el.dataset.condensed = window.scrollY > 24 ? 'true' : 'false';
    };
    const onScroll = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(apply);
    };
    apply();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      window.removeEventListener('scroll', onScroll);
      cancelAnimationFrame(raf);
    };
  }, []);

  /* Which section am I in? A band across the viewport's middle is the honest
     answer: a section counts as current only while it occupies the reading
     position, so the marker never claims a section that is barely peeking. */
  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return;
    const sections = LINKS.map((l) => document.getElementById(l.target)).filter(
      (el): el is HTMLElement => Boolean(el)
    );
    if (sections.length === 0) return;

    /* The observer's job is a SET, not a notification. Reading the first
       intersecting entry out of the callback (as this did) cannot express
       "none of them": once a section had been marked current, scrolling back to
       the hero left its marker lit, so the nav claimed you were in Blueprint
       while the headline filled the screen. Tracking the set and deriving the
       marker from it in LINKS order means the hero — which is not an observed
       target — correctly produces no marker at all. */
    const visible = new Set<string>();
    const order = LINKS.map((l) => l.target);
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) visible.add(entry.target.id);
          else visible.delete(entry.target.id);
        }
        setActive(order.find((t) => visible.has(t)) ?? null);
      },
      { rootMargin: '-40% 0px -50% 0px', threshold: 0 }
    );
    sections.forEach((s) => io.observe(s));
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [menuOpen]);

  const go = (target: string) => {
    setMenuOpen(false);
    scrollToId(target);
  };

  return (
    <>
      <motion.header
        initial={{ y: -64, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ type: 'spring', stiffness: 300, damping: 28, delay: 0.1 }}
        className="fixed inset-x-0 top-0 z-50 flex justify-center px-4 pt-4"
      >
        <nav
          ref={navRef}
          aria-label="Primary"
          className="bw-nav relative flex w-full max-w-[46rem] items-center gap-1 rounded-full"
        >
          {/* Brand */}
          <a
            href="#top"
            onClick={(e) => {
              e.preventDefault();
              go('top');
            }}
            className="flex min-h-11 min-w-11 shrink-0 items-center justify-center gap-2 rounded-full"
            aria-label="BuildWise AI — back to top"
          >
            <img
              src={LOGO_SRC}
              srcSet={LOGO_SRCSET}
              alt=""
              width={26}
              height={26}
              className="rounded-[8px]"
              decoding="async"
            />
            <span className="text-[15px] font-bold tracking-[-0.02em] text-bw-ink max-[420px]:hidden">
              BuildWise AI
            </span>
          </a>

          <span aria-hidden className="hidden h-5 w-px shrink-0 bg-bw-line md:block" />

          {/* Links (desktop) */}
          <ul className="hidden flex-1 items-center justify-center gap-0.5 md:flex">
            {LINKS.map((l) => {
              const isActive = active === l.target;
              return (
                <li key={l.label}>
                  <a
                    href={`#${l.target}`}
                    onClick={(e) => {
                      e.preventDefault();
                      go(l.target);
                    }}
                    aria-current={isActive ? 'true' : undefined}
                    className="bw-nav-link inline-flex h-11 items-center rounded-full px-3 text-[14px] font-medium text-bw-ink-2 transition-colors duration-150 hover:text-bw-ink"
                  >
                    {isActive && (
                      <motion.span layoutId="bw-nav-active" className="bw-nav-active" transition={SPRING_SOFT} />
                    )}
                    <span className="relative">{l.label}</span>
                  </a>
                </li>
              );
            })}
          </ul>

          {/* CTA */}
          <div className="ml-auto flex items-center gap-1.5 md:ml-0">
            <button
              type="button"
              onClick={() => navigate(SIGN_IN_PATH)}
              className="hidden sm:inline-flex h-11 items-center rounded-full px-3 text-[13px] font-medium text-bw-ink-2 hover:text-bw-ink transition-colors cursor-pointer"
            >
              Sign in
            </button>
            <button
              type="button"
              onClick={() => navigate(APP_PATH)}
              className="group inline-flex h-11 shrink-0 items-center gap-1 rounded-full border border-bw-line bg-bw-surface pl-3.5 pr-3 text-[13px] font-semibold text-bw-ink transition-[background-color,border-color,transform] duration-200 hover:bg-bw-line-soft active:scale-[0.97]"
            >
              Open the app
              <span
                aria-hidden
                className="transition-transform duration-200 group-hover:translate-x-0.5 motion-reduce:transform-none"
              >
                <Icon name="chevron-right" size={14} />
              </span>
            </button>

            {/* Mobile menu button */}
            <button
              type="button"
              onClick={() => setMenuOpen((p) => !p)}
              aria-expanded={menuOpen}
              aria-controls="bw-mobile-menu"
              aria-label={menuOpen ? 'Close menu' : 'Open menu'}
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-bw-ink transition-colors duration-150 hover:bg-bw-line-soft md:hidden"
            >
              <MenuIcon open={menuOpen} />
            </button>
          </div>

          {/* Mobile sheet */}
          <AnimatePresence>
            {menuOpen && (
              <motion.div
                id="bw-mobile-menu"
                initial={{ opacity: 0, y: -8, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -6, scale: 0.99 }}
                transition={SPRING_SOFT}
                style={{ transformOrigin: 'top center', boxShadow: LANDING.shadow.window }}
                className="absolute inset-x-0 top-[calc(100%+8px)] rounded-[18px] border border-bw-line-soft bg-bw-surface p-1.5 md:hidden"
              >
                <ul className="flex flex-col">
                  {LINKS.map((l) => (
                    <li key={l.label}>
                      <a
                        href={`#${l.target}`}
                        onClick={(e) => {
                          e.preventDefault();
                          go(l.target);
                        }}
                        aria-current={active === l.target ? 'true' : undefined}
                        className="flex min-h-11 items-center justify-between rounded-[12px] px-3.5 py-2.5 text-[15px] font-medium text-bw-ink transition-colors duration-150 hover:bg-bw-line-soft"
                      >
                        {l.label}
                        <span aria-hidden className="text-bw-ink-3">
                          <Icon name="chevron-right" size={14} />
                        </span>
                      </a>
                    </li>
                  ))}
                </ul>
              </motion.div>
            )}
          </AnimatePresence>
        </nav>
      </motion.header>

      {/* Scrim — a sibling of the header (z-40 under the header's z-50).
          It must never live inside <nav>: nav has backdrop-filter, which makes
          it a stacking context, so a negative-z child painted OVER the pill's
          background and greyed the whole navbar when open. */}
      <AnimatePresence>
        {menuOpen && (
          <motion.div
            key="bw-menu-scrim"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={() => setMenuOpen(false)}
            aria-hidden
            className="fixed inset-0 z-40 bg-[rgba(11,18,32,0.24)] md:hidden"
          />
        )}
      </AnimatePresence>
    </>
  );
};
