import React, { useState, useRef, useEffect } from 'react';
import { Icon } from './Icon';

interface AppHeaderProps {
  backendConnected: boolean;
  activeAiProvider: string;
  serverStatus?: { groq: boolean; gemini: boolean } | null;
  onOpenMethodology: () => void;
  onReset: () => void;
  warnings?: string[];
  isWarningDismissed?: boolean;
  onRestoreWarning?: () => void;
  theme?: 'light' | 'dark';
  onToggleTheme?: () => void;
  isMobileControlOpen?: boolean;
  onToggleMobileControl?: () => void;
  isMobileResultsOpen?: boolean;
  onToggleMobileResults?: () => void;
  hasResults?: boolean;
  /** Focus-return targets for the compact-tier drawers. */
  headerControlToggleRef?: React.Ref<HTMLButtonElement>;
  headerResultsToggleRef?: React.Ref<HTMLButtonElement>;
}

export type EngineBadgeState = 'live' | 'deterministic' | 'offline' | 'unverified';

/**
 * What the header may claim about the authoring engine, derived at RENDER time
 * from the two probes the app actually has: `/api/status` (backend reachable +
 * which hosted keys are configured) and the selected provider. Nothing here is
 * a static label: if the backend stops answering, the badge says Offline; if the
 * selected hosted provider has no key, it says Deterministic (the engine that
 * really authors the text) instead of the old "Engine Offline (Local Mock)",
 * which called a working deterministic engine offline. Ollama has no probe, so
 * it is reported as Unverified rather than guessed either way.
 */
export function engineBadge(
  backendConnected: boolean,
  activeAiProvider: string,
  serverStatus?: { groq: boolean; gemini: boolean } | null,
): { state: EngineBadgeState; label: string; dotClass: string; title: string } {
  if (!backendConnected) {
    return {
      state: 'offline',
      label: 'Offline',
      dotClass: 'bg-[var(--semantic-red)]',
      title: 'AI engine: Offline — the backend did not answer the health probe.',
    };
  }

  const hosted =
    activeAiProvider === 'groq'
      ? { name: 'Groq', available: Boolean(serverStatus?.groq) }
      : activeAiProvider === 'gemini'
        ? { name: 'Gemini', available: Boolean(serverStatus?.gemini) }
        : null;

  if (hosted?.available) {
    return {
      state: 'live',
      label: `Live · ${hosted.name}`,
      dotClass: 'bg-[var(--semantic-green)] animate-pulse',
      title: `AI engine: Live — the ${hosted.name} key is configured. Key presence is probed; upstream reachability is not.`,
    };
  }

  if (hosted) {
    return {
      state: 'deterministic',
      label: 'Deterministic',
      dotClass: 'bg-[var(--semantic-amber)]',
      title: `AI engine: Deterministic — no ${hosted.name} key is configured, so the built-in engine authors the commentary and programme.`,
    };
  }

  if (activeAiProvider === 'ollama') {
    return {
      state: 'unverified',
      label: 'Unverified · Ollama',
      dotClass: 'bg-[var(--semantic-amber)]',
      title:
        'AI engine: Unverified — Ollama has no health probe. If it is unreachable the built-in engine authors the text and the response discloses the fallback.',
    };
  }

  return {
    state: 'deterministic',
    label: 'Deterministic',
    dotClass: 'bg-[var(--semantic-amber)]',
    title:
      'AI engine: Deterministic — the built-in engine authors the commentary and programme; no hosted key is in use.',
  };
}

export const AppHeader: React.FC<AppHeaderProps> = ({
  backendConnected,
  activeAiProvider,
  serverStatus,
  onOpenMethodology,
  onReset,
  warnings = [],
  isWarningDismissed = false,
  onRestoreWarning,
  theme = 'light',
  onToggleTheme,
  isMobileControlOpen = false,
  onToggleMobileControl,
  isMobileResultsOpen = false,
  onToggleMobileResults,
  hasResults = false,
  headerControlToggleRef,
  headerResultsToggleRef,
}) => {
  const [isPopoverOpen, setIsPopoverOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);
  const triggerBtnRef = useRef<HTMLButtonElement>(null);

  // Close popover on outside click or Escape
  useEffect(() => {
    if (!isPopoverOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsPopoverOpen(false);
        triggerBtnRef.current?.focus();
      }
    };
    const handleClickOutside = (e: MouseEvent) => {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target as Node) &&
        triggerBtnRef.current &&
        !triggerBtnRef.current.contains(e.target as Node)
      ) {
        setIsPopoverOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isPopoverOpen]);

  return (
    <header
      className="fixed top-2 sm:top-3 left-2 sm:left-3 right-2 sm:right-3 h-[48px] sm:h-[52px] rounded-[14px] sm:rounded-[16px] vibrancy-panel z-[1001] px-2.5 sm:px-4 flex items-center justify-between pointer-events-auto border border-[var(--panel-border-color)] shadow-md select-none"
    >
      {/* Brand identity: BuildWise AI Logo */}
      <div className="flex items-center gap-2 sm:gap-2.5 min-w-0">
        <div className="w-7 h-7 rounded-[8px] bg-white dark:bg-white/10 flex items-center justify-center shrink-0 border border-slate-200/90 dark:border-white/10 overflow-hidden shadow-xs">
          <img
            src={theme === 'dark' ? '/brand/BuildWise_logo_square_white.png' : '/brand/BuildWise_logo_square.png'}
            alt="BuildWise AI Logo"
            className="w-[21px] h-[21px] object-contain select-none"
          />
        </div>
        <div className="min-w-0 flex items-center gap-1.5 sm:gap-2">
          <h1 className="text-[14px] sm:text-[15px] font-semibold text-[var(--text-1)] tracking-tight whitespace-nowrap truncate">
            BuildWise AI
          </h1>
          <span className="hidden sm:inline-block text-[11px] font-medium bg-[var(--fill)] text-[var(--text-2)] px-2 py-0.5 rounded-full shrink-0">
            v1.0
          </span>
          <span className="text-[12px] text-[var(--text-2)] hidden xl:inline-block truncate max-w-xs">
            Geo-Based Feasibility & Site Planning
          </span>
        </div>
      </div>

      {/* Right controls: Theme toggle, Telemetry notice, Methodology, Reset, Engine Status */}
      <div className="flex items-center gap-1 sm:gap-2 shrink-0">
        {/* Mobile Panel Toggles (hidden on desktop >=1024px) */}
        <div className="flex lg:hidden items-center gap-1 sm:gap-1.5">
          {onToggleMobileControl && (
            <button
              type="button"
              id="controls-toggle"
              ref={headerControlToggleRef}
              onClick={onToggleMobileControl}
              aria-expanded={isMobileControlOpen}
              aria-controls="controls-drawer"
              className={`relative px-2 sm:px-2.5 py-1.5 sm:py-2 text-[12px] font-medium rounded-[10px] transition-colors flex items-center justify-center gap-1 min-h-[32px] sm:min-h-[36px] min-w-[32px] bw-touch-target ${
                isMobileControlOpen
                  ? 'bg-[var(--accent)] text-white'
                  : 'bg-[var(--fill)] text-[var(--text-1)] hover:bg-[var(--fill-hover)]'
              }`}
              title="Toggle Parameters Panel"
              aria-label="Toggle Parameters Panel"
            >
              <Icon name="sliders" size={13} />
              <span className="hidden sm:inline">Controls</span>
            </button>
          )}

          {onToggleMobileResults && (
            <button
              type="button"
              id="results-toggle"
              ref={headerResultsToggleRef}
              onClick={onToggleMobileResults}
              aria-expanded={isMobileResultsOpen}
              aria-controls="results-drawer"
              className={`relative px-2 sm:px-2.5 py-1.5 sm:py-2 text-[12px] font-medium rounded-[10px] transition-colors flex items-center justify-center gap-1 min-h-[32px] sm:min-h-[36px] min-w-[32px] bw-touch-target ${
                isMobileResultsOpen
                  ? 'bg-[var(--accent)] text-white'
                  : 'bg-[var(--fill)] text-[var(--text-1)] hover:bg-[var(--fill-hover)]'
              }`}
              title="Toggle Results Panel"
              aria-label="Toggle Results Panel"
            >
              <Icon name="layers" size={13} />
              <span className="hidden sm:inline">{hasResults ? 'Results' : 'Overview'}</span>
            </button>
          )}
        </div>

        {/* Warning Indicator Badge & Accessible Popover */}
        {warnings.length > 0 && (
          <div className="relative">
            <button
              ref={triggerBtnRef}
              type="button"
              onClick={() => setIsPopoverOpen(!isPopoverOpen)}
              aria-haspopup="dialog"
              aria-expanded={isPopoverOpen}
              className="flex items-center gap-1 sm:gap-1.5 px-2 sm:px-2.5 py-1 text-[11px] sm:text-[12px] font-medium text-[var(--semantic-amber-ink)] bg-[var(--fill)] hover:bg-[var(--fill-hover)] rounded-[10px] transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--semantic-amber)]/30 min-h-[32px]"
              title={`Telemetry Notices (${warnings.length}): Click or press Enter to view details`}
              aria-label={`View ${warnings.length} telemetry notices`}
            >
              <Icon name="alert-triangle" size={13} className="text-[var(--semantic-amber-ink)] shrink-0" />
              <span className="font-semibold">{warnings.length}</span>
              <span className="hidden sm:inline">Notice{warnings.length > 1 ? 's' : ''}</span>
            </button>

            {/* Keyboard & Mouse Accessible Telemetry Popover */}
            {isPopoverOpen && (
              <div
                ref={popoverRef}
                role="dialog"
                aria-label="Telemetry Warning Details"
                className="absolute right-0 top-full mt-2 w-80 sm:w-96 max-w-[calc(100vw-32px)] vibrancy-panel rounded-[16px] shadow-2xl z-[1050] p-4 space-y-3 text-[12px] border border-[var(--panel-border-color)]"
              >
                <div className="flex items-center justify-between border-b border-[var(--hairline)] pb-2.5">
                  <div className="flex items-center gap-1.5 text-[var(--semantic-amber-ink)] font-semibold">
                    <Icon name="alert-triangle" size={14} />
                    <span>Active Telemetry Notices ({warnings.length})</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setIsPopoverOpen(false)}
                    className="text-[var(--text-3)] hover:text-[var(--text-1)] p-1 rounded transition-colors"
                    aria-label="Close telemetry details"
                  >
                    <Icon name="x" size={14} />
                  </button>
                </div>

                <div className="space-y-2 max-h-60 overflow-y-auto scrollbar-apple pr-1">
                  {warnings.map((w, idx) => (
                    <div
                      key={idx}
                      className="bg-[var(--fill)] p-2.5 rounded-[10px] text-[var(--text-1)] leading-relaxed whitespace-normal break-words flex items-start gap-2"
                    >
                      <span className="font-bold text-[11px] text-[var(--semantic-amber-ink)] mt-0.5 shrink-0">
                        {idx + 1}.
                      </span>
                      <p className="flex-1 text-[12px]">{w}</p>
                    </div>
                  ))}
                </div>

                {isWarningDismissed && onRestoreWarning && (
                  <div className="pt-2 border-t border-[var(--hairline)] flex justify-end">
                    <button
                      type="button"
                      onClick={() => {
                        onRestoreWarning();
                        setIsPopoverOpen(false);
                      }}
                      className="px-3 py-1 bg-[var(--fill)] hover:bg-[var(--fill-hover)] text-[var(--text-1)] font-medium rounded-[8px] transition-colors text-[12px]"
                    >
                      Restore Banner to Top
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Theme toggle icon button */}
        {onToggleTheme && (
          <button
            type="button"
            onClick={onToggleTheme}
            className="relative w-8 h-8 rounded-[10px] bg-[var(--fill)] hover:bg-[var(--fill-hover)] text-[var(--text-1)] flex items-center justify-center transition-colors active:brightness-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
            title="Toggle light / dark theme"
            aria-label="Toggle light / dark theme"
            aria-keyshortcuts="T"
          >
            <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={15} />
          </button>
        )}

        {/* Secondary action: Methodology button */}
        <button
          type="button"
          onClick={onOpenMethodology}
          className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-medium text-[var(--text-1)] bg-[var(--fill)] hover:bg-[var(--fill-hover)] rounded-[10px] transition-colors shrink-0 active:brightness-95"
          title="View engineering calculation methodology"
        >
          <Icon name="info" size={14} className="text-[var(--text-2)] shrink-0" />
          <span>Methodology</span>
        </button>

        {/* Secondary action: Reset button */}
        <button
          type="button"
          onClick={onReset}
          className="relative flex items-center justify-center gap-1.5 w-8 h-8 sm:w-auto sm:px-3 sm:py-1.5 text-[12px] font-medium text-[var(--text-1)] bg-[var(--fill)] hover:bg-[var(--fill-hover)] rounded-[10px] transition-colors shrink-0 active:brightness-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
          title="Reset the site analysis"
          aria-label="Reset the site analysis"
          aria-keyshortcuts="R"
        >
          <Icon name="refresh" size={14} className="text-[var(--text-2)] shrink-0" />
          <span className="hidden sm:inline">Reset</span>
        </button>

        {/* Engine state pill: ONE derivation from the health/key probes at
            render time. Old copy called the deterministic engine
            "Offline (Local Mock)", which mislabelled a working engine. */}
        {(() => {
          const badge = engineBadge(backendConnected, activeAiProvider, serverStatus);
          return (
            <div
              data-testid="engine-state"
              data-engine-state={badge.state}
              aria-label={`AI engine state: ${badge.state}`}
              className="hidden md:flex items-center gap-1.5 px-2.5 py-1.5 rounded-[10px] bg-[var(--fill)] text-[12px] font-medium text-[var(--text-2)] shrink-0"
              title={badge.title}
            >
              <span className={`w-2 h-2 rounded-full shrink-0 ${badge.dotClass}`} />
              <span data-testid="engine-state-label" className="whitespace-nowrap">{badge.label}</span>
            </div>
          );
        })()}
      </div>
    </header>
  );
};
