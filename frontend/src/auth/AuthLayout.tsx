/**
 * AuthLayout.tsx — Cohesive architectural backdrop and frame for BuildWise authentication screens.
 * Aligns with the core design language: precision typography, translucency, and structured layout.
 */
import React from 'react';
import { LANDING_PATH, navigate } from '../landing/router';

interface AuthLayoutProps {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}

export const AuthLayout: React.FC<AuthLayoutProps> = ({ title, subtitle, children }) => {
  return (
    <div className="min-h-screen w-full flex flex-col justify-between bg-[var(--bg-page)] text-[var(--text-1)] select-none relative overflow-x-hidden">
      {/* Background technical grid pattern */}
      <div
        className="fixed inset-0 pointer-events-none opacity-40 dark:opacity-20"
        style={{
          backgroundImage:
            'radial-gradient(circle at 1px 1px, rgba(100, 116, 139, 0.16) 1px, transparent 0)',
          backgroundSize: '24px 24px',
        }}
      />

      {/* Floating brand header */}
      <header className="relative z-10 w-full max-w-5xl mx-auto px-4 sm:px-6 py-6 flex items-center justify-between">
        <button
          type="button"
          onClick={() => navigate(LANDING_PATH)}
          className="flex items-center gap-2.5 group cursor-pointer transition-transform duration-150 active:scale-98"
          title="Return to BuildWise home"
        >
          <div className="w-8 h-8 rounded-[10px] bg-white dark:bg-white/10 flex items-center justify-center shrink-0 border border-slate-200 dark:border-white/10 shadow-xs overflow-hidden">
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
          <span className="text-[15px] font-bold tracking-tight text-[var(--text-1)] group-hover:text-[var(--accent)] transition-colors">
            BuildWise AI
          </span>
        </button>

        <button
          type="button"
          onClick={() => navigate(LANDING_PATH)}
          className="text-[12px] font-medium text-[var(--text-2)] hover:text-[var(--text-1)] px-3 py-1.5 rounded-full hover:bg-[var(--fill)] transition-colors cursor-pointer"
        >
          Back to Overview
        </button>
      </header>

      {/* Centered Form Card */}
      <main className="relative z-10 flex-1 flex items-center justify-center px-4 sm:px-6 py-8">
        <div className="w-full max-w-[440px] bg-white dark:bg-slate-900 rounded-[20px] p-6 sm:p-8 shadow-2xl border border-slate-200/80 dark:border-slate-800/80 backdrop-blur-xl">
          {/* Header */}
          <div className="mb-6 text-center">
            <h1 className="text-[20px] sm:text-[22px] font-bold tracking-tight text-[var(--text-1)] mb-1.5">
              {title}
            </h1>
            <p className="text-[13px] text-[var(--text-2)] leading-relaxed">{subtitle}</p>
          </div>

          {/* Form Content */}
          {children}
        </div>
      </main>

      {/* Footer */}
      <footer className="relative z-10 py-6 text-center text-[12px] text-[var(--text-3)] border-t border-[var(--hairline)]">
        <p>&copy; {new Date().getFullYear()} BuildWise AI · Intelligent Construction Planning & Site Feasibility</p>
      </footer>
    </div>
  );
};
