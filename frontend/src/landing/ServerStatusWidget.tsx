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
        className={`group relative inline-flex ${
          status === 'WAKING_UP' ? 'flex-wrap' : 'flex-nowrap'
        } items-center gap-1.5 sm:gap-2 rounded-full border border-bw-line bg-bw-surface px-3 sm:px-3.5 py-1.5 text-[11.5px] sm:text-[12px] font-medium text-bw-ink-2 transition-colors duration-200 hover:border-bw-ink-3 max-w-full min-h-[44px]`}
        style={{ boxShadow: 'var(--bw-shadow-1)' }}
      >
        {/* Status Indicator Icon / Dot */}
        <div className="flex items-center gap-2 min-w-0 flex-1 sm:flex-initial">
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
                className={`relative inline-flex h-2 w-2 rounded-full bg-bw-green ${
                  reduced ? '' : 'animate-pulse'
                }`}
              />
            </span>
          )}

          {status === 'OFFLINE' && (
            <span
              className="relative flex h-2 w-2"
              title="Server is sleeping"
              aria-hidden="true"
            >
              <span className="relative inline-flex h-2 w-2 rounded-full bg-bw-amber" />
            </span>
          )}

          {status === 'WAKING_UP' && (
            <span
              className="relative flex h-2.5 w-2.5 text-bw-accent flex-shrink-0"
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
                <span className="hidden xs:inline ml-1">· Free tier cold start</span>
              </span>
            )}

            {status === 'WAKING_UP' && (
              <span className="text-bw-ink font-semibold truncate">
                {elapsedSeconds > estimatedTotalSeconds
                  ? 'Finalizing server startup...'
                  : 'Waking up server...'}
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
              className="h-full bg-bw-accent rounded-full"
              initial={{ width: '6%' }}
              animate={{ width: `${Math.max(6, progressPercent)}%` }}
              transition={{ duration: 0.8, ease: 'easeOut' }}
            />
          </div>
        )}

        {/* Action Controls — every control keeps >= 44px hit height */}
        <div className="flex items-center gap-0.5 ml-auto flex-shrink-0 -my-1.5">
          {status === 'OFFLINE' && (
            <button
              type="button"
              onClick={() => void wakeUp()}
              className="inline-flex min-h-11 items-center gap-1.5 rounded-full bg-bw-cta px-3.5 text-[11.5px] font-semibold text-bw-cta-ink transition-[background-color,transform] duration-150 hover:bg-bw-cta-hover active:scale-95 cursor-pointer"
              style={{ boxShadow: 'var(--bw-shadow-1)' }}
              aria-label="Wake up BuildWise backend server"
            >
              <Icon name="zap" size={12} className="text-bw-amber" />
              <span>Wake Up Server</span>
            </button>
          )}

          {status === 'ERROR' && (
            <button
              type="button"
              onClick={() => void wakeUp()}
              className="inline-flex min-h-11 items-center gap-1 rounded-full bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/50 px-3 text-[11.5px] font-semibold text-rose-700 dark:text-rose-300 transition-colors duration-150 hover:bg-rose-100 dark:hover:bg-rose-900/60 active:scale-95 cursor-pointer"
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
