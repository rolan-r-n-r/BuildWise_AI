/**
 * Navbar.tsx — Floating Glass Pill Navigation with Session Awareness.
 * Supports smooth scroll-spy section markers, desktop & mobile account navigation,
 * and high-performance compositor-only condensed transition.
 */
import React, { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { EASE_APPLE, SPRING_SOFT } from './motion';
import { scrollToId } from './scroll';
import { APP_PATH, SIGN_IN_PATH, SIGN_UP_PATH, navigate } from './router';
import { useSession } from '../lib/auth-client';
import { Icon } from '../components/Icon';
import { LANDING } from './theme';
import { LOGO_SRC, LOGO_SRCSET, LOGO_WHITE_SRC, LOGO_WHITE_SRCSET } from './logo';

const LINKS: ReadonlyArray<{ label: string; target: string }> = [
  { label: 'About', target: 'about' },
  { label: 'Capabilities', target: 'capabilities' },
  { label: 'Standards', target: 'standards' },
  { label: 'Blueprint', target: 'blueprint' },
];

/** Read active or preferred theme */
const getInitialTheme = (): 'light' | 'dark' => {
  if (typeof window === 'undefined') return 'light';
  try {
    const saved = localStorage.getItem('bw-theme');
    if (saved === 'dark' || saved === 'light') return saved;
  } catch {}
  if (document.documentElement.getAttribute('data-theme') === 'dark') return 'dark';
  if (document.documentElement.classList.contains('dark')) return 'dark';
  if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    return 'dark';
  }
  return 'light';
};

/**
 * MenuIcon — three-line hamburger that morphs into an x.
 * Integer-pixel geometry only (16px box, 2px lines, 4px gaps).
 */
const MenuIcon: React.FC<{ open: boolean }> = ({ open }) => (
  <span aria-hidden className="flex h-4 w-4 flex-col items-center justify-center gap-[4px]">
    <motion.span
      className="block h-[2px] w-full rounded-full bg-current"
      initial={false}
      animate={open ? { rotate: 45, y: 6 } : { rotate: 0, y: 0 }}
      transition={{ duration: 0.2, ease: EASE_APPLE }}
    />
    <motion.span
      className="block h-[2px] w-full rounded-full bg-current"
      initial={false}
      animate={open ? { opacity: 0, x: -2 } : { opacity: 1, x: 0 }}
      transition={{ duration: 0.15, ease: EASE_APPLE }}
    />
    <motion.span
      className="block h-[2px] w-full rounded-full bg-current"
      initial={false}
      animate={open ? { rotate: -45, y: -6 } : { rotate: 0, y: 0 }}
      transition={{ duration: 0.2, ease: EASE_APPLE }}
    />
  </span>
);

export const Navbar: React.FC = () => {
  const { data: session } = useSession();
  const user = session?.user;
  const [menuOpen, setMenuOpen] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const [theme, setTheme] = useState<'light' | 'dark'>(getInitialTheme);
  const navRef = useRef<HTMLElement>(null);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [theme]);

  const toggleTheme = () => {
    const nextTheme = theme === 'light' ? 'dark' : 'light';
    setTheme(nextTheme);
    document.documentElement.setAttribute('data-theme', nextTheme);
    if (nextTheme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
    try {
      localStorage.setItem('bw-theme', nextTheme);
    } catch {}
  };

  /* Condense the pill past the hero's first 24px of scroll. */
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

  /* IntersectionObserver for scroll-spy active link */
  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return;
    const sections = LINKS.map((l) => document.getElementById(l.target)).filter(
      (el): el is HTMLElement => Boolean(el)
    );
    if (sections.length === 0) return;

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
    const onResize = () => {
      if (window.innerWidth >= 768) setMenuOpen(false);
    };
    window.addEventListener('keydown', onKey);
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', onResize);
    };
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
          className="bw-nav relative flex w-full max-w-[48rem] items-center gap-1 rounded-full"
        >
          {/* Brand */}
          <a
            href="#top"
            onClick={(e) => {
              e.preventDefault();
              go('top');
            }}
            className="flex min-h-11 min-w-11 shrink-0 items-center justify-center gap-2 rounded-full pl-1"
            aria-label="BuildWise AI — back to top"
          >
            <img
              src={LOGO_SRC}
              srcSet={LOGO_SRCSET}
              alt=""
              width={26}
              height={26}
              className="rounded-[8px] dark:hidden"
              decoding="async"
            />
            <img
              src={LOGO_WHITE_SRC}
              srcSet={LOGO_WHITE_SRCSET}
              alt=""
              width={26}
              height={26}
              className="rounded-[8px] hidden dark:block"
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

          {/* Actions / CTA */}
          <div className="ml-auto flex items-center gap-1.5 md:ml-0">
            {user ? (
              <button
                type="button"
                onClick={() => navigate(APP_PATH)}
                className="hidden sm:inline-flex h-11 items-center gap-2 rounded-full px-3 text-[13px] font-medium text-bw-ink-2 hover:text-bw-ink transition-colors cursor-pointer"
                title={`Logged in as ${user.name || user.email}`}
              >
                <span className="w-5 h-5 rounded-full bg-slate-900 text-white text-[10px] font-bold flex items-center justify-center">
                  {(user.name || user.email || 'U').charAt(0).toUpperCase()}
                </span>
                <span className="max-w-[100px] truncate">{user.name?.split(' ')[0] || 'App'}</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={() => navigate(SIGN_IN_PATH)}
                className="hidden sm:inline-flex h-11 items-center rounded-full px-3 text-[13px] font-medium text-bw-ink-2 hover:text-bw-ink transition-colors cursor-pointer"
              >
                Sign in
              </button>
            )}

            {/* Theme Toggle (Desktop) */}
            <button
              type="button"
              onClick={toggleTheme}
              aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
              className="hidden sm:inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-bw-ink-2 hover:text-bw-ink transition-colors duration-150 hover:bg-bw-line-soft cursor-pointer"
              title={theme === 'dark' ? 'Light mode' : 'Dark mode'}
            >
              <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={17} />
            </button>

            <button
              type="button"
              onClick={() => navigate(APP_PATH)}
              className="group inline-flex h-11 shrink-0 items-center gap-1 rounded-full border border-bw-line bg-bw-surface pl-3.5 pr-3 text-[13px] font-semibold text-bw-ink transition-[background-color,border-color,transform] duration-200 hover:bg-bw-line-soft active:scale-[0.97] cursor-pointer"
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
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-bw-ink transition-colors duration-150 hover:bg-bw-line-soft md:hidden cursor-pointer"
            >
              <MenuIcon open={menuOpen} />
            </button>
          </div>

          {/* Mobile Sheet Dropdown */}
          <AnimatePresence>
            {menuOpen && (
              <motion.div
                id="bw-mobile-menu"
                initial={{ opacity: 0, y: -8, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -6, scale: 0.99 }}
                transition={SPRING_SOFT}
                style={{ transformOrigin: 'top center', boxShadow: LANDING.shadow.window }}
                className="absolute inset-x-0 top-[calc(100%+8px)] rounded-[18px] border border-bw-line-soft bg-bw-surface p-2 md:hidden"
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

                {/* Mobile Menu Action Suite */}
                <div className="mt-2 pt-2 border-t border-bw-line-soft flex flex-col gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setMenuOpen(false);
                      navigate(APP_PATH);
                    }}
                    className="w-full min-h-11 rounded-[12px] bg-bw-cta text-bw-cta-ink text-[14px] font-semibold flex items-center justify-center gap-2 transition-colors cursor-pointer"
                  >
                    <span>Open the app</span>
                    <Icon name="chevron-right" size={14} />
                  </button>

                  {!user ? (
                    <div className="grid grid-cols-2 gap-2">
                      <button
                        type="button"
                        onClick={() => {
                          setMenuOpen(false);
                          navigate(SIGN_IN_PATH);
                        }}
                        className="min-h-11 rounded-[12px] border border-bw-line bg-bw-surface text-bw-ink text-[13px] font-medium flex items-center justify-center transition-colors cursor-pointer hover:bg-bw-line-soft"
                      >
                        Sign in
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setMenuOpen(false);
                          navigate(SIGN_UP_PATH);
                        }}
                        className="min-h-11 rounded-[12px] border border-bw-line bg-bw-surface text-bw-ink text-[13px] font-medium flex items-center justify-center transition-colors cursor-pointer hover:bg-bw-line-soft"
                      >
                        Create account
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => {
                        setMenuOpen(false);
                        navigate(APP_PATH);
                      }}
                      className="w-full min-h-11 rounded-[12px] border border-bw-line bg-bw-surface text-bw-ink text-[13px] font-medium flex items-center justify-between px-3.5 transition-colors cursor-pointer hover:bg-bw-line-soft"
                    >
                      <span className="truncate">{user.name || user.email}</span>
                      <span className="text-[11px] text-bw-accent font-semibold">Active Session &rarr;</span>
                    </button>
                  )}

                  {/* Theme Switcher Row (Mobile) */}
                  <div className="flex items-center justify-between px-3 py-1.5 rounded-[12px] bg-bw-line-soft/60">
                    <span className="text-[13px] font-medium text-bw-ink-2">Appearance</span>
                    <button
                      type="button"
                      onClick={toggleTheme}
                      aria-label={theme === 'dark' ? 'Dark theme' : 'Light theme'}
                      className="inline-flex h-11 items-center gap-2 rounded-full px-3 text-[13px] font-medium text-bw-ink bg-bw-surface border border-bw-line transition-colors cursor-pointer"
                    >
                      <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={15} />
                      <span>{theme === 'dark' ? 'Dark theme' : 'Light theme'}</span>
                    </button>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </nav>
      </motion.header>

      {/* Scrim for Mobile Menu */}
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