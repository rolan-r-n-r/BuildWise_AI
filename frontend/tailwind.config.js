/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      /* Responsive breakpoints:
         xs <480 | sm 480-767 | md 768-1023 | lg 1024-1439 | xl >=1440.
         Tailwind screens are min-width edges, so sm/xs share the 480 edge;
         max-* variants give the "below" ranges. 2xl stays at default 1536. */
      screens: {
        xs: '480px',
        sm: '480px',
        md: '768px',
        lg: '1024px',
        xl: '1440px',
      },
      colors: {
        /* Landing (marketing) palette. Mirrors the --bw-* custom properties in
           index.css, which are the single source of the landing's colours:
           naming them here lets the JSX say `text-bw-ink` / `border-bw-line`
           instead of repeating hex literals that the token lint (rightly)
           counts against every file. */
        bw: {
          porcelain: 'var(--bw-porcelain-1)',
          'porcelain-2': 'var(--bw-porcelain-2)',
          surface: 'var(--bw-white)',
          ink: 'var(--bw-ink)',
          'ink-hover': 'var(--bw-ink-hover)',
          'ink-2': 'var(--bw-ink-2)',
          'ink-3': 'var(--bw-ink-3)',
          accent: 'var(--bw-accent)',
          'accent-deep': 'var(--bw-accent-deep)',
          'accent-tint': 'var(--bw-accent-tint)',
          green: 'var(--bw-green)',
          'green-ink': 'var(--bw-green-ink)',
          amber: 'var(--bw-amber)',
          'amber-ink': 'var(--bw-amber-ink)',
          line: 'var(--bw-line)',
          'line-soft': 'var(--bw-line-soft)',
          glass: 'var(--bw-glass)',
          /* Primary CTA pair. It must invert with the palette: "ink on
             porcelain" is dark-on-light in light mode and light-on-dark in
             dark mode, so a button that reuses --bw-ink as a FILL would turn
             light-on-light (audit F32 axe contrast 1.07:1). */
          cta: 'var(--bw-cta-bg)',
          'cta-ink': 'var(--bw-cta-ink)',
          'cta-hover': 'var(--bw-cta-bg-hover)',
        },
        apple: {
          panel: 'var(--panel)',
          border: 'var(--panel-border)',
          fill: 'var(--fill)',
          'fill-hover': 'var(--fill-hover)',
          hairline: 'var(--hairline)',
          'text-1': 'var(--text-1)',
          'text-2': 'var(--text-2)',
          'text-3': 'var(--text-3)',
          accent: 'var(--accent)',
          'accent-tint': 'var(--accent-tint)',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      letterSpacing: {
        apple: '-0.01em',
      },
      transitionDuration: {
        DEFAULT: '150ms',
        0: '0ms',
        75: '75ms',
        100: '100ms',
        150: '150ms',
        180: '180ms',
        200: '200ms',
        250: '250ms',
        280: '280ms',
        300: '300ms',
      },
      transitionTimingFunction: {
        apple: 'cubic-bezier(0.25, 0.1, 0.25, 1)',
        spatial: 'cubic-bezier(0.22, 0.61, 0.36, 1)',
      },
      keyframes: {
        'scrim-fade': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        'sheet-in': {
          from: { opacity: '0', transform: 'scale(0.97) translateY(6px)' },
          to: { opacity: '1', transform: 'scale(1) translateY(0)' },
        },
        'toast-in': {
          from: { opacity: '0', transform: 'translateY(8px) scale(0.98)' },
          to: { opacity: '1', transform: 'translateY(0) scale(1)' },
        },
      },
      animation: {
        'scrim': 'scrim-fade 150ms cubic-bezier(0.25, 0.1, 0.25, 1) forwards',
        'sheet-in': 'sheet-in 200ms cubic-bezier(0.25, 0.1, 0.25, 1) forwards',
        'toast-in': 'toast-in 200ms cubic-bezier(0.25, 0.1, 0.25, 1) forwards',
      },
    },
  },
  plugins: [
    require('@tailwindcss/container-queries'),
  ],
}
