/**
 * AuthLayout.tsx — Architectural Canvas & Frame for BuildWise Authentication.
 * Features an engineering-grade technical blueprint showcase on desktop and
 * a clean, focused, responsive form container on mobile.
 */
import React, { useState, useEffect } from 'react';
import { LANDING_PATH, navigate } from '../landing/router';
import { Icon } from '../components/Icon';

interface AuthLayoutProps {
  title: string;
  subtitle: string;
  badge?: string;
  children: React.ReactNode;
}

export const AuthLayout: React.FC<AuthLayoutProps> = ({
  title,
  subtitle,
  badge = 'Civil & Spatial AI',
  children,
}) => {
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
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
  });

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    document.documentElement.classList.toggle('dark', theme === 'dark');
    try {
      localStorage.setItem('bw-theme', theme);
    } catch {
      // storage unavailable
    }
  }, [theme]);

  const toggleTheme = () => {
    setTheme((prev) => (prev === 'light' ? 'dark' : 'light'));
  };

  return (
    <div className="min-h-screen w-full flex flex-col justify-between bg-slate-50 dark:bg-slate-950 text-[var(--text-1)] select-none relative overflow-x-hidden transition-colors duration-200">
      {/* Background technical architectural grid pattern */}
      <div
        className="fixed inset-0 pointer-events-none opacity-40 dark:opacity-15"
        style={{
          backgroundImage:
            'radial-gradient(circle at 1px 1px, rgba(100, 116, 139, 0.2) 1px, transparent 0)',
          backgroundSize: '24px 24px',
        }}
      />

      {/* Top Navigation Bar */}
      <header className="relative z-20 w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-5 flex items-center justify-between">
        <button
          type="button"
          onClick={() => navigate(LANDING_PATH)}
          className="flex items-center gap-2.5 group cursor-pointer transition-transform duration-150 active:scale-98"
          title="Return to BuildWise Overview"
        >
          <div className="w-8 h-8 rounded-[10px] bg-white dark:bg-slate-900 flex items-center justify-center shrink-0 border border-slate-200 dark:border-slate-800 shadow-xs overflow-hidden">
            <img
              src="/brand/BuildWise_logo_square.png"
              alt="BuildWise Logo"
              className="w-5 h-5 object-contain dark:hidden"
            />
            <img
              src="/brand/BuildWise_logo_square_white.png"
              alt="BuildWise Logo"
              className="w-5 h-5 object-contain hidden dark:block"
            />
          </div>
          <div className="flex flex-col text-left">
            <span className="text-[15px] font-bold tracking-tight text-[var(--text-1)] group-hover:text-[var(--accent)] transition-colors">
              BuildWise AI
            </span>
            <span className="text-[10px] font-medium text-[var(--text-3)] tracking-wider uppercase">
              Spatial Intelligence
            </span>
          </div>
        </button>

        <div className="flex items-center gap-2.5">
          {/* Light / Dark Mode Toggle */}
          <button
            type="button"
            onClick={toggleTheme}
            aria-label={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}
            title={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}
            className="w-9 h-9 rounded-full bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-[var(--text-2)] hover:text-[var(--text-1)] flex items-center justify-center transition-colors cursor-pointer shadow-xs hover:border-slate-300 dark:hover:border-slate-700"
          >
            <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={15} />
          </button>

          {/* Back to Home Link */}
          <button
            type="button"
            onClick={() => navigate(LANDING_PATH)}
            className="inline-flex items-center gap-1.5 text-[12px] font-medium text-[var(--text-2)] hover:text-[var(--text-1)] px-3.5 py-1.5 rounded-full bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700 transition-colors cursor-pointer shadow-xs"
          >
            <span aria-hidden className="text-[var(--text-3)]">
              &larr;
            </span>
            <span>Overview</span>
          </button>
        </div>
      </header>

      {/* Main Split Layout: Technical Stage on Left (lg+), Auth Form on Right */}
      <main className="relative z-10 flex-1 flex items-center justify-center px-4 sm:px-6 lg:px-8 py-6 lg:py-10">
        <div className="w-full max-w-5xl grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-12 items-center">
          {/* ---------------- Left Technical Architectural Showcase (lg+) ---------------- */}
          <div className="hidden lg:flex lg:col-span-6 flex-col justify-between space-y-6 select-none pr-4">
            {/* Top Credibility Tag */}
            <div>
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-50 dark:bg-blue-950/50 border border-blue-200 dark:border-blue-900/60 text-blue-700 dark:text-blue-300 text-[11px] font-semibold tracking-wide uppercase mb-4">
                <span className="w-2 h-2 rounded-full bg-blue-600 dark:bg-blue-400 animate-pulse" />
                <span>Deterministic Civil Engineering Core</span>
              </div>
              <h2 className="text-[26px] xl:text-[28px] font-bold text-[var(--text-1)] tracking-tight leading-snug">
                From satellite coordinates to buildable structural plans.
              </h2>
              <p className="mt-2 text-[14px] text-[var(--text-2)] leading-relaxed">
                Instant geotechnical hazard scoring, CPWD cost benchmarks, and generative floor plan layouts
                grounded in Indian civil codes.
              </p>
            </div>

            {/* Interactive Vector Blueprint Cadastral Preview */}
            <div className="relative rounded-[16px] bg-white dark:bg-slate-900 border border-slate-200/90 dark:border-slate-800 p-5 bw-glass-dialog shadow-lg overflow-hidden">
              {/* Header Bar */}
              <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3 mb-3">
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-emerald-500" />
                  <span className="text-[12px] font-mono font-semibold text-[var(--text-1)]">
                    SITE-2026-BLR-048
                  </span>
                  <span className="text-[11px] text-[var(--text-3)]">· 2,450 m²</span>
                </div>
                <div className="flex items-center gap-1.5 text-[11px] font-mono text-[var(--text-2)]">
                  <span>12.9716° N</span>
                  <span>77.5946° E</span>
                </div>
              </div>

              {/* Architectural CAD Schematic drawing */}
              <div className="relative w-full h-[190px] bg-slate-50 dark:bg-slate-950 rounded-[10px] border border-slate-200/60 dark:border-slate-800/80 p-3 flex flex-col justify-between overflow-hidden">
                {/* Blueprint grid lines */}
                <div
                  className="absolute inset-0 opacity-20 pointer-events-none"
                  style={{
                    backgroundImage:
                      'linear-gradient(to right, rgba(59, 130, 246, 0.3) 1px, transparent 1px), linear-gradient(to bottom, rgba(59, 130, 246, 0.3) 1px, transparent 1px)',
                    backgroundSize: '16px 16px',
                  }}
                />

                {/* SVG Floorplan Geometry */}
                <svg
                  className="w-full h-full text-slate-400 dark:text-slate-600 relative z-10"
                  viewBox="0 0 360 160"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  {/* Outer boundary polygon */}
                  <rect
                    x="20"
                    y="10"
                    width="320"
                    height="140"
                    rx="4"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeDasharray="4 2"
                    className="opacity-40"
                  />
                  {/* Setback area */}
                  <rect
                    x="40"
                    y="25"
                    width="280"
                    height="110"
                    rx="3"
                    stroke="var(--accent)"
                    strokeWidth="1.5"
                    fill="var(--accent)"
                    fillOpacity="0.04"
                  />
                  {/* Living Room */}
                  <rect
                    x="40"
                    y="25"
                    width="140"
                    height="70"
                    stroke="currentColor"
                    strokeWidth="1"
                    className="opacity-60"
                  />
                  <text
                    x="50"
                    y="45"
                    fontSize="9"
                    fontWeight="600"
                    fill="currentColor"
                    className="text-slate-700 dark:text-slate-300"
                  >
                    Living Room
                  </text>
                  <text x="50" y="58" fontSize="8" fill="currentColor" className="opacity-60">
                    24.5 m² · Vastu E
                  </text>

                  {/* Kitchen & Dining */}
                  <rect
                    x="180"
                    y="25"
                    width="140"
                    height="70"
                    stroke="currentColor"
                    strokeWidth="1"
                    className="opacity-60"
                  />
                  <text
                    x="190"
                    y="45"
                    fontSize="9"
                    fontWeight="600"
                    fill="currentColor"
                    className="text-slate-700 dark:text-slate-300"
                  >
                    Kitchen & Dining
                  </text>
                  <text x="190" y="58" fontSize="8" fill="currentColor" className="opacity-60">
                    22.0 m² · Agni SE
                  </text>

                  {/* Master Suite */}
                  <rect
                    x="40"
                    y="95"
                    width="160"
                    height="40"
                    stroke="currentColor"
                    strokeWidth="1"
                    className="opacity-60"
                  />
                  <text
                    x="50"
                    y="112"
                    fontSize="9"
                    fontWeight="600"
                    fill="currentColor"
                    className="text-slate-700 dark:text-slate-300"
                  >
                    Master Suite
                  </text>
                  <text x="50" y="124" fontSize="8" fill="currentColor" className="opacity-60">
                    18.2 m² · SW
                  </text>

                  {/* Verandah / Open Courtyard */}
                  <rect
                    x="200"
                    y="95"
                    width="120"
                    height="40"
                    stroke="currentColor"
                    strokeWidth="1"
                    className="opacity-60"
                  />
                  <text
                    x="210"
                    y="112"
                    fontSize="9"
                    fontWeight="600"
                    fill="currentColor"
                    className="text-slate-700 dark:text-slate-300"
                  >
                    Open Courtyard
                  </text>
                  <text x="210" y="124" fontSize="8" fill="currentColor" className="opacity-60">
                    14.8 m² · Brahmasthan
                  </text>

                  {/* Dimension markers */}
                  <path d="M40 18 L320 18" stroke="currentColor" strokeWidth="0.8" className="opacity-50" />
                  <path d="M40 15 L40 21 M320 15 L320 21" stroke="currentColor" strokeWidth="0.8" className="opacity-50" />
                  <text x="165" y="15" fontSize="7.5" textAnchor="middle" fill="currentColor" className="opacity-75 font-mono">
                    14.00 m
                  </text>

                  <path d="M330 25 L330 135" stroke="currentColor" strokeWidth="0.8" className="opacity-50" />
                  <path d="M327 25 L333 25 M327 135 L333 135" stroke="currentColor" strokeWidth="0.8" className="opacity-50" />
                  <text x="345" y="82" fontSize="7.5" textAnchor="middle" fill="currentColor" className="opacity-75 font-mono" transform="rotate(90 345 82)">
                    11.00 m
                  </text>
                </svg>

                {/* Corner Status Pill */}
                <div className="flex items-center justify-between text-[10px] text-[var(--text-3)] font-mono z-10 pt-1">
                  <span>SCALE 1:100</span>
                  <span className="text-emerald-600 dark:text-emerald-400 font-semibold inline-flex items-center gap-1">
                    <Icon name="check" size={10} className="text-emerald-600 dark:text-emerald-400" />
                    <span>PASS: NBC 2016 SETBACKS</span>
                  </span>
                </div>
              </div>

              {/* Compliance Chip Bar */}
              <div className="grid grid-cols-3 gap-2 mt-3 pt-2 text-[11px]">
                <div className="p-2 rounded-[8px] bg-slate-50 dark:bg-slate-800/60 border border-slate-100 dark:border-slate-800 text-center">
                  <span className="block text-[10px] text-[var(--text-3)] uppercase font-semibold">
                    Seismic
                  </span>
                  <span className="font-bold text-[var(--text-1)]">IS 1893 Zone III</span>
                </div>
                <div className="p-2 rounded-[8px] bg-slate-50 dark:bg-slate-800/60 border border-slate-100 dark:border-slate-800 text-center">
                  <span className="block text-[10px] text-[var(--text-3)] uppercase font-semibold">
                    CPWD Rate
                  </span>
                  <span className="font-bold text-[var(--text-1)]">₹2,450 / sq.ft</span>
                </div>
                <div className="p-2 rounded-[8px] bg-slate-50 dark:bg-slate-800/60 border border-slate-100 dark:border-slate-800 text-center">
                  <span className="block text-[10px] text-[var(--text-3)] uppercase font-semibold">
                    Vastu Score
                  </span>
                  <span className="font-bold text-emerald-600 dark:text-emerald-400">88 / 100</span>
                </div>
              </div>
            </div>

            {/* Testimonial Quote */}
            <div className="border-l-2 border-[var(--accent)] pl-4 py-1">
              <p className="text-[12.5px] italic text-[var(--text-2)] leading-relaxed">
                &ldquo;BuildWise compressed our preliminary civil feasibility and setback compliance
                from three weeks of manual CAD and municipal back-and-forth into forty-five seconds on
                site.&rdquo;
              </p>
              <p className="mt-1 text-[11px] font-semibold text-[var(--text-1)]">
                Ar. Vikramaditya Rao <span className="font-normal text-[var(--text-3)]">· Principal Architect & Urban Planner</span>
              </p>
            </div>
          </div>

          {/* ---------------- Right Authentication Form Column ---------------- */}
          <div className="w-full lg:col-span-6 flex justify-center min-w-0">
            <div className="w-full max-w-[440px] bg-white dark:bg-slate-900 rounded-[20px] p-6 sm:p-8 bw-glass-dialog shadow-xl border border-slate-200/90 dark:border-slate-800 transition-colors min-w-0">
              {/* Header */}
              <div className="mb-6 text-left">
                {badge && (
                  <span className="inline-block text-[11px] font-semibold text-[var(--accent)] uppercase tracking-wider mb-1.5">
                    {badge}
                  </span>
                )}
                <h1 className="text-[22px] sm:text-[24px] font-bold tracking-tight text-[var(--text-1)] mb-1">
                  {title}
                </h1>
                <p className="text-[13px] text-[var(--text-2)] leading-relaxed">{subtitle}</p>
              </div>

              {/* Form Content */}
              {children}
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="relative z-10 py-5 text-center text-[12px] text-[var(--text-3)] border-t border-slate-200/60 dark:border-slate-800/80">
        <p className="max-w-7xl mx-auto px-4 flex flex-col sm:flex-row items-center justify-between gap-2">
          <span>&copy; {new Date().getFullYear()} BuildWise AI · Intelligent Construction Planning</span>
          <span className="inline-flex items-center gap-1.5 text-[11px] text-[var(--text-3)]">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            Argon2id & Scrypt Constant-Time Security · Private Tenant Isolation
          </span>
        </p>
      </footer>
    </div>
  );
};