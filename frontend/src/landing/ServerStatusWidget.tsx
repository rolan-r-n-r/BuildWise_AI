/**
 * ServerStatusWidget.tsx — Live Server Availability & Smart Wake-Up Widget.
 *
 * Implements Apple HIG translucency, glassmorphism, responsive alignment,
 * accessible screen-reader status announcements, and progress indication.
 * Fits seamlessly into the BuildWise landing page hero without visual clutter.
 */
import React, { useEffect, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { useServerHealth } from '../hooks/useServerHealth';
import { Icon } from '../components/Icon';

interface ServerStatusWidgetProps {
  className?: string;
  onServerReady?: () => void;
}

export const ServerStatusWidget: React.FC<ServerStatusWidgetProps> = ({
  className = '',
  onServerReady,
}) => {
  const reduced = useReducedMotion();
  const [showDetails, setShowDetails] = useState<boolean>(false);

  const {
    status,
    justWokeUp,
    latencyMs,
    elapsedSeconds,
    estimatedTotalSeconds,
    progressPercent,
    wakeUp,
    checkHealth,
  } = useServerHealth({
    autoCheck: true,
    onOnline: onServerReady,
  });

  // Close details on Escape key press
  useEffect(() => {
    if (!showDetails) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setShowDetails(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [showDetails]);

  // Format seconds to mm:ss
  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m}:${s < 10 ? '0' : ''}${s}`;
  };

  const isWaking = status === 'WAKING_UP';
  const isActionBar = status === 'OFFLINE' || status === 'ERROR';

  return (
    <div
      role="region"
      aria-label="BuildWise Backend Server Status"
      className={`inline-flex flex-col gap-2 max-w-full ${
        isWaking || isActionBar ? 'w-full xs:w-auto' : ''
      } ${className}`}
    >
      <div
        className={`group relative ${
          isWaking
            ? 'grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2 gap-y-2 rounded-[18px] px-3.5 py-2.5 md:inline-flex md:flex-nowrap md:gap-2.5 md:rounded-full md:py-1 md:pl-3.5 md:pr-1.5'
            : isActionBar
              ? 'grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2 gap-y-2 rounded-[18px] px-3.5 py-2.5 xs:inline-flex xs:flex-nowrap xs:gap-2 xs:rounded-full xs:py-0.5 xs:pl-3.5 xs:pr-1'
              : 'inline-grid grid-cols-[minmax(0,1fr)_auto] items-center gap-1.5 sm:gap-2 rounded-full pl-3.5 pr-1 py-0.5'
        } border border-bw-line bg-bw-surface text-[12px] font-medium text-bw-ink-2 transition-colors duration-200 hover:border-bw-ink-3 max-w-full min-h-[44px]`}
        style={{ boxShadow: 'var(--bw-shadow-1)' }}
      >
        {/* Status Indicator Icon / Dot + Message */}
        <div className="flex items-center gap-2 min-w-0">
          {status === 'CHECKING' && (
            <span
              className="relative flex h-2 w-2 shrink-0"
              title="Checking server status"
              aria-hidden="true"
            >
              <span className="relative inline-flex h-2 w-2 rounded-full bg-bw-ink-3/60" />
            </span>
          )}

          {status === 'ONLINE' && (
            <span
              className="relative flex h-2 w-2 shrink-0"
              title="Server is operational"
              aria-hidden="true"
            >
              <span
                className={`relative inline-flex h-2 w-2 rounded-full bg-bw-green ${
                  reduced ? '' : 'animate-pulse'
                }`}
              />
            </span>
          )}

          {status === 'OFFLINE' && (
            <span
              className="relative flex h-2 w-2 shrink-0"
              title="Server is sleeping"
              aria-hidden="true"
            >
              <span className="relative inline-flex h-2 w-2 rounded-full bg-bw-amber" />
            </span>
          )}

          {status === 'WAKING_UP' && (
            <span
              className="relative flex h-2.5 w-2.5 text-bw-accent shrink-0"
              title="Server is starting up"
              aria-hidden="true"
            >
              <span className={`inline-block h-2.5 w-2.5 rounded-full border-2 border-bw-accent border-t-transparent ${
                reduced ? '' : 'animate-spin'
              }`} />
            </span>
          )}

          {status === 'ERROR' && (
            <span
              className="relative flex h-2 w-2 shrink-0"
              title="Connection error"
              aria-hidden="true"
            >
              <span className="relative inline-flex h-2 w-2 rounded-full bg-rose-500" />
            </span>
          )}

          {/* Contextual Status Message with ARIA live announcement */}
          <div
            role="status"
            aria-live="polite"
            className="flex items-center gap-1.5 min-w-0"
          >
            {status === 'ONLINE' && (
              <span className="truncate">
                {justWokeUp ? (
                  <span className="text-bw-green-ink font-semibold inline-flex items-center gap-1">
                    <Icon name="check-circle" size={12} className="text-bw-green-ink" />
                    <span>Server Ready! · All systems operational</span>
                  </span>
                ) : (
                  <>
                    <span className="font-semibold text-bw-ink">BuildWise AI</span>
                    <span className="text-bw-ink-2 ml-1">
                      · <span className="hidden xs:inline">All Systems </span>Operational
                    </span>
                    {latencyMs !== null && latencyMs > 0 && (
                      <span className="ml-1.5 font-normal text-bw-ink-3 ui-font-tabular">
                        ({latencyMs}ms)
                      </span>
                    )}
                  </>
                )}
              </span>
            )}

            {status === 'CHECKING' && (
              <span className="text-bw-ink-2 truncate">
                <span className="font-semibold text-bw-ink">BuildWise AI</span>
                <span className="ml-1">· Checking availability...</span>
              </span>
            )}

            {status === 'OFFLINE' && (
              <span className="text-bw-ink-2 truncate">
                <span className="font-semibold text-bw-ink">Server Sleeping</span>
                <span className="ml-1 md:hidden">· Cold start</span>
                <span className="hidden md:inline ml-1">· Free tier cold start</span>
              </span>
            )}

            {status === 'WAKING_UP' && (
              <span className="flex items-baseline gap-1.5 min-w-0">
                <span className="text-bw-ink font-semibold truncate">
                  {elapsedSeconds > estimatedTotalSeconds
                    ? 'Finalizing server startup...'
                    : 'Waking up server...'}
                </span>
                <span className="font-normal text-bw-ink-3 ui-font-tabular shrink-0 text-[11px]">
                  <span className="md:hidden">({formatTime(elapsedSeconds)})</span>
                  <span className="hidden md:inline">
                    ({formatTime(elapsedSeconds)} / ~{formatTime(estimatedTotalSeconds)})
                  </span>
                </span>
              </span>
            )}

            {status === 'ERROR' && (
              <span className="text-rose-600 dark:text-rose-400 font-medium truncate">
                Server wake-up delayed
              </span>
            )}
          </div>
        </div>

        {/* Info / Refresh Utility Controls — always top-right; every control keeps >= 44px hit box */}
        <div
          className={`flex items-center gap-0.5 justify-self-end shrink-0 ${
            isWaking || isActionBar ? '-my-1.5 xs:my-0' : ''
          } ${isActionBar ? 'xs:order-3' : 'md:order-3'}`}
        >
          {status === 'ONLINE' && (
            <button
              type="button"
              onClick={() => void checkHealth()}
              className="inline-flex h-11 w-11 items-center justify-center text-bw-ink-3 hover:text-bw-ink rounded-full transition-colors duration-150 hover:bg-bw-line-soft active:scale-90 cursor-pointer"
              title="Refresh server status"
              aria-label="Refresh server status"
            >
              <Icon name="refresh" size={13} />
            </button>
          )}

          {/* Info toggle button */}
          <button
            type="button"
            onClick={() => setShowDetails((prev) => !prev)}
            aria-expanded={showDetails}
            aria-label="Toggle server architecture details"
            className="inline-flex h-11 w-11 items-center justify-center text-bw-ink-3 hover:text-bw-ink rounded-full transition-colors duration-150 hover:bg-bw-line-soft active:scale-90 cursor-pointer"
            title="Why does the server sleep?"
          >
            <Icon name="info" size={14} />
          </button>
        </div>

        {/* Action CTA (row 2 full-width on narrow phones, centered h-8 pill inside 44px tap wrapper on xs+) */}
        {status === 'OFFLINE' && (
          <button
            type="button"
            onClick={() => void wakeUp()}
            className="group/btn col-span-full w-full xs:w-auto xs:order-2 inline-flex min-h-11 items-center justify-center rounded-[12px] xs:rounded-full cursor-pointer"
            aria-label="Wake Up Server — start BuildWise backend"
          >
            <span
              className="w-full xs:w-auto inline-flex h-10 xs:h-8 items-center justify-center gap-1.5 rounded-[11px] xs:rounded-full bg-bw-cta px-3.5 text-[11.5px] font-semibold text-bw-cta-ink transition-[background-color,transform] duration-150 group-hover/btn:bg-bw-cta-hover group-active/btn:scale-95 whitespace-nowrap"
              style={{ boxShadow: 'var(--bw-shadow-1)' }}
            >
              <Icon name="zap" size={12} className="text-bw-amber shrink-0" />
              <span>Wake Up Server</span>
            </span>
          </button>
        )}

        {status === 'ERROR' && (
          <button
            type="button"
            onClick={() => void wakeUp()}
            className="group/btn col-span-full w-full xs:w-auto xs:order-2 inline-flex min-h-11 items-center justify-center rounded-[12px] xs:rounded-full cursor-pointer"
            aria-label="Retry server wake-up"
          >
            <span className="w-full xs:w-auto inline-flex h-10 xs:h-8 items-center justify-center gap-1.5 rounded-[11px] xs:rounded-full bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/50 px-3.5 text-[11.5px] font-semibold text-rose-700 dark:text-rose-300 transition-colors duration-150 group-hover/btn:bg-rose-100 dark:group-hover/btn:bg-rose-900/60 group-active/btn:scale-95 whitespace-nowrap">
              <Icon name="refresh" size={11} />
              <span>Retry</span>
            </span>
          </button>
        )}

        {/* Progress Bar (full bottom track on mobile/narrow tablet, inline on md+) */}
        {status === 'WAKING_UP' && (
          <div
            className="col-span-full w-full md:order-2 md:w-32 h-1.5 bg-bw-line rounded-full overflow-hidden shrink-0"
            role="progressbar"
            aria-valuenow={progressPercent}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Server wake-up progress"
          >
            <motion.div
              className="h-full bg-bw-accent rounded-full"
              initial={{ width: '6%' }}
              animate={{ width: `${Math.max(6, progressPercent)}%` }}
              transition={{ duration: 0.8, ease: 'easeOut' }}
            />
          </div>
        )}
      </div>

      {/* Expandable Info Popover / Disclosure */}
      <AnimatePresence>
        {showDetails && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15 }}
            className="rounded-xl border border-bw-line bg-bw-surface p-3.5 text-[12px] leading-relaxed text-bw-ink-2 max-w-md"
            style={{ boxShadow: 'var(--bw-shadow-2)' }}
          >
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="font-semibold text-bw-ink">
                  About BuildWise Cloud Infrastructure
                </p>
                <p className="mt-1">
                  To provide 100% free site feasibility and architectural blueprints with zero paid APIs, BuildWise backend instances automatically sleep after 15 minutes of inactivity.
                </p>
                <p className="mt-1.5 text-bw-ink-3">
                  Waking up triggers a container cold-start that typically completes in 50–70 seconds. Once online, subsequent requests respond in milliseconds.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowDetails(false)}
                className="inline-flex h-11 w-11 shrink-0 items-center justify-center text-bw-ink-3 hover:text-bw-ink -mr-2 -mt-2 rounded-full transition-colors duration-150 hover:bg-bw-line-soft cursor-pointer"
                aria-label="Close information"
              >
                <Icon name="x" size={14} />
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};
