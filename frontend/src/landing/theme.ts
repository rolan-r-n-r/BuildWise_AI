/**
 * landing/theme.ts — BuildWise AI marketing-site tokens.
 * Mirrors the macOS-premium language of the app (design/tokens.ts) at
 * display scale: porcelain ground, ink, one accent, Apple easing curves.
 *
 * Two rules hold this file together:
 *
 *  1. ELEVATION IS A VOCABULARY, NOT A DECISION. Every shadow here is one of
 *     the three elevations declared once in index.css (--bw-shadow-1/2/3) plus
 *     the window shell. A marketing page that invents a shadow per surface
 *     ends up with five subtly different depths, which the eye reads as five
 *     different materials.
 *  2. THE ACCENT IS ONE COLOUR. --bw-accent with a single deeper stop
 *     (--bw-accent-deep) for the headline; no second hue, no light-blue
 *     partner hue competing with it.
 *
 * All values are landing-local; nothing here overrides the app's tokens.
 */

export const LANDING = {
  color: {
    porcelain1: '#eef2f7',
    porcelain2: '#e2e9f2',
    ink: '#0b1220',
    slate: '#46536a',
    slateSoft: '#6b7787',
    accent: '#2f6fed',
    accentDeep: '#1b53c4',
    green: '#1fa955',
    amber: '#8a5300',
    white: '#ffffff',
  },
  /** Material recipes (strings are consumed inline for single-use surfaces) */
  glass: {
    blur: 'blur(20px) saturate(180%)',
    blurDeep: 'blur(32px) saturate(180%)',
    fill: 'rgba(255, 255, 255, 0.55)',
    fillStrong: 'rgba(255, 255, 255, 0.72)',
    hairline: 'rgba(255, 255, 255, 0.18)',
    topLight: 'inset 0 1px 0 rgba(255, 255, 255, 0.25)',
  },
  shadow: {
    /** Resting card (--bw-shadow-1) */
    card: 'var(--bw-shadow-1)',
    /** Floating element: nav pill, mockup shell (--bw-shadow-2) */
    float: 'var(--bw-shadow-2)',
    /** Window shell: contact ring + wide ambient (--bw-shadow-window) */
    window: 'var(--bw-shadow-window)',
    /** Solid dark CTA: a tight drop, never the window's ambient spread */
    dark: '0 1px 2px rgba(11, 18, 32, 0.28), 0 6px 16px -6px rgba(11, 18, 32, 0.4)',
  },
  radius: {
    /** macOS window corner (index.css --bw-radius-window) */
    window: 14,
    /** Panel inside a window (--bw-radius-panel) */
    panel: 11,
    card: 11,
    pill: 999,
  },
  type: {
    hero: 'clamp(2.15rem, 5.6vw, 4.75rem)',
    sectionTitle: 'clamp(1.65rem, 3vw, 2.5rem)',
    trackingHero: '-0.04em',
    trackingEyebrow: '0.16em',
  },
} as const;

/** Display stack used across the landing (SF-first, like the app). */
export const FONT_DISPLAY =
  "-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Inter', 'Segoe UI', Roboto, sans-serif";
