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

  return (
    <div
      role="region"
      aria-label="BuildWise Backend Server Status"
      className={`inline-flex flex-col gap-2 max-w-full ${className}`}
    >
      <div
        className="group relative inline-flex flex-wrap items-center gap-2.5 rounded-2xl sm:rounded-full border border-bw-line bg-bw-surface/90 px-3.5 py-1.5 text-[12px] font-medium text-bw-ink-2 shadow-xs backdrop-blur-md transition-colors hover:border-bw-line-soft max-w-full"
      >
        {/* Status Indicator Icon / Dot */}
        <div className="flex items-center gap-2 flex-shrink-0">
          {status === 'CHECKING' && (
            <span
              className="relative flex h-2 w-2"
              title="Checking server status"
              aria-hidden="true"
            >
              <span className="relative inline-flex h-2 w-2 rounded-full bg-bw-ink-3/60" />
            </span>
          )}

          {status === 'ONLINE' && (
            <span
              className="relative flex h-2 w-2"
              title="Server is operational"
              aria-hidden="true"
            >
              <span
                className={`absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75 ${
                  reduced ? '' : 'animate-ping'
                }`}
              />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
            </span>
          )}

          {status === 'OFFLINE' && (
            <span
              className="relative flex h-2 w-2"
              title="Server is sleeping"
              aria-hidden="true"
            >
              <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-500" />
            </span>
          )}

          {status === 'WAKING_UP' && (
            <span
              className="relative flex h-2.5 w-2.5 text-blue-500 flex-shrink-0"
              title="Server is starting up"
              aria-hidden="true"
            >
              <span className={`inline-block h-2.5 w-2.5 rounded-full border-2 border-blue-500 border-t-transparent ${
                reduced ? '' : 'animate-spin'
              }`} />
            </span>
          )}

          {status === 'ERROR' && (
            <span
              className="relative flex h-2 w-2"
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
                  <span className="text-emerald-600 dark:text-emerald-400 font-semibold inline-flex items-center gap-1">
                    <Icon name="check-circle" size={12} className="text-emerald-500" />
                    <span>Server Ready! · All systems operational</span>
                  </span>
                ) : (
                  <>
                    <span className="font-semibold text-bw-ink">BuildWise AI</span>
                    <span className="text-bw-ink-2 ml-1">· All Systems Operational</span>
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
                <span className="hidden xs:inline ml-1">· Free tier cold start</span>
              </span>
            )}

            {status === 'WAKING_UP' && (
              <span className="text-bw-ink font-semibold truncate">
                Waking up server...
                <span className="ml-1.5 font-normal text-bw-ink-3 ui-font-tabular hidden sm:inline">
                  ({formatTime(elapsedSeconds)} / ~{formatTime(estimatedTotalSeconds)})
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

        {/* Progress Bar (during WAKING_UP) */}
        {status === 'WAKING_UP' && (
          <div
            className="w-full xs:w-28 sm:w-32 h-1.5 bg-bw-line rounded-full overflow-hidden flex-shrink-0"
            role="progressbar"
            aria-valuenow={progressPercent}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Server wake-up progress"
          >
            <motion.div
              className="h-full bg-gradient-to-r from-blue-500 to-indigo-500 rounded-full"
              initial={{ width: '6%' }}
              animate={{ width: `${Math.max(6, progressPercent)}%` }}
              transition={{ duration: 0.8, ease: 'easeOut' }}
            />
          </div>
        )}

        {/* Action Controls */}
        <div className="flex items-center gap-1.5 ml-auto flex-shrink-0">
          {status === 'OFFLINE' && (
            <button
              type="button"
              onClick={() => void wakeUp()}
              className="inline-flex items-center gap-1.5 rounded-full bg-bw-cta px-3 py-1 text-[11.5px] font-semibold text-bw-cta-ink shadow-xs transition-transform duration-150 hover:bg-bw-cta-hover active:scale-95 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-bw-accent"
              aria-label="Wake up BuildWise backend server"
            >
              <Icon name="zap" size={12} className="text-amber-400" />
              <span>Wake Up Server</span>
            </button>
          )}

          {status === 'ERROR' && (
            <button
              type="button"
              onClick={() => void wakeUp()}
              className="inline-flex items-center gap-1 rounded-full bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/50 px-2.5 py-0.5 text-[11px] font-semibold text-rose-700 dark:text-rose-300 transition-colors hover:bg-rose-100 dark:hover:bg-rose-900/60 active:scale-95 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-500"
              aria-label="Retry server wake-up"
            >
              <Icon name="refresh" size={11} />
              <span>Retry</span>
            </button>
          )}

          {status === 'ONLINE' && (
            <button
              type="button"
              onClick={() => void checkHealth()}
              className="text-bw-ink-3 hover:text-bw-ink p-1 rounded-full transition-colors active:scale-90 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-bw-accent"
              title="Refresh server status"
              aria-label="Refresh server status"
            >
              <Icon name="refresh" size={11} />
            </button>
          )}

          {/* Info toggle button */}
          <button
            type="button"
            onClick={() => setShowDetails((prev) => !prev)}
            aria-expanded={showDetails}
            aria-label="Toggle server architecture details"
            className="text-bw-ink-3 hover:text-bw-ink p-1 rounded-full transition-colors active:scale-90 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-bw-accent"
            title="Why does the server sleep?"
          >
            <Icon name="info" size={12} />
          </button>
        </div>
      </div>

      {/* Expandable Info Popover / Disclosure */}
      <AnimatePresence>
        {showDetails && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15 }}
            className="rounded-xl border border-bw-line bg-bw-surface/95 p-3 text-[12px] leading-relaxed text-bw-ink-2 shadow-sm backdrop-blur-md max-w-md"
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
                  Waking up triggers a container cold-start that typically completes in 30–50 seconds. Once online, subsequent requests respond in milliseconds.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowDetails(false)}
                className="text-bw-ink-3 hover:text-bw-ink p-1 -mr-1 -mt-1 rounded-md transition-colors"
                aria-label="Close information"
              >
                <Icon name="x" size={13} />
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};
