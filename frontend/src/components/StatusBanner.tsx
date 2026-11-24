import React, { useEffect, useRef, useState } from 'react';
import { Icon } from './Icon';
import { triggerServerWakeUp, checkBackendHealth } from '../services/serverHealthService';

interface TelemetryStripProps {
  warnings: string[];
  isDismissed: boolean;
  onDismiss: () => void;
}

export const TelemetryStrip: React.FC<TelemetryStripProps> = ({
  warnings,
  isDismissed,
  onDismiss,
}) => {
  if (isDismissed || !warnings || warnings.length === 0) {
    return null;
  }

  // Concatenate multiple warnings into a single sentence, truncated with ellipsis
  const combinedText = warnings.join(' • ');

  return (
    <div
      role="status"
      className="vibrancy-panel rounded-[12px] border border-[var(--panel-border-color)] text-[var(--semantic-amber-ink)] px-3.5 py-2 text-[12px] flex items-center justify-between gap-3 shrink-0 z-[1000]"
    >
      <div className="flex items-center gap-2 min-w-0 flex-1">
        <Icon name="alert-triangle" size={14} className="text-[var(--semantic-amber-ink)] shrink-0" />
        <span className="font-semibold shrink-0 uppercase tracking-[0.08em] text-[11px]">
          Notice:
        </span>
        <span
          className="text-[var(--text-1)] text-[12px] min-w-0 flex-1 whitespace-normal break-words lg:truncate"
          title={combinedText}
        >
          {combinedText}
        </span>
      </div>
      <button
        type="button"
        onClick={onDismiss}
        className="text-[var(--text-3)] hover:text-[var(--text-1)] p-1 rounded-[6px] transition-colors shrink-0"
        title="Dismiss telemetry notice"
        aria-label="Dismiss telemetry notice"
      >
        <Icon name="x" size={13} />
      </button>
    </div>
  );
};

interface ErrorBannerProps {
  errorMessage: string | null;
  onDismiss?: () => void;
  onRetry?: () => void;
  onWakeUp?: () => void;
}

export const ErrorBanner: React.FC<ErrorBannerProps> = ({
  errorMessage,
  onDismiss,
  onRetry,
  onWakeUp,
}) => {
  const [waking, setWaking] = useState(false);
  const [wakeSuccess, setWakeSuccess] = useState(false);
  const pollTimerRef = useRef<number | null>(null);
  const isMountedRef = useRef<boolean>(true);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      if (pollTimerRef.current !== null) {
        window.clearTimeout(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, []);

  if (!errorMessage) return null;

  const msgLower = errorMessage.toLowerCase();
  const isServerIssue =
    msgLower.includes('sleeping') ||
    msgLower.includes('unreachable') ||
    msgLower.includes('unavailable') ||
    msgLower.includes('failed to fetch') ||
    msgLower.includes('502') ||
    msgLower.includes('503') ||
    msgLower.includes('504');

  const handleWakeUp = () => {
    if (onWakeUp) {
      onWakeUp();
      return;
    }
    if (pollTimerRef.current !== null) {
      window.clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    setWaking(true);

    // Fire wake-up probe non-blocking so active polling begins immediately
    void triggerServerWakeUp();

    const startTime = Date.now();
    const MAX_WAIT_MS = 120000; // 2 minutes window to match Render free cold-starts

    const poll = async () => {
      if (!isMountedRef.current) return;
      const res = await checkBackendHealth({ timeoutMs: 14000, skipCache: true });
      if (!isMountedRef.current) return;

      if (res.isOnline) {
        setWaking(false);
        setWakeSuccess(true);
        if (pollTimerRef.current !== null) {
          window.clearTimeout(pollTimerRef.current);
          pollTimerRef.current = null;
        }
        return;
      }

      if (Date.now() - startTime < MAX_WAIT_MS) {
        pollTimerRef.current = window.setTimeout(poll, 2500);
      } else {
        setWaking(false);
        if (pollTimerRef.current !== null) {
          window.clearTimeout(pollTimerRef.current);
          pollTimerRef.current = null;
        }
      }
    };

    pollTimerRef.current = window.setTimeout(poll, 1500);
  };

  return (
    <div
      role="alert"
      className="bg-[var(--fill)] border border-[var(--hairline)] text-[var(--text-1)] p-3 rounded-[12px] text-[12px] flex items-start justify-between gap-3 shadow-sm"
    >
      <div className="flex items-start gap-2.5 flex-1 min-w-0">
        <Icon name="shield-alert" size={15} className="text-[var(--semantic-red-ink)] mt-0.5 shrink-0" />
        <div className="space-y-1 min-w-0 flex-1">
          <span className="font-semibold block text-[12px] text-[var(--semantic-red-ink)]">
            System Alert
          </span>
          <p className="text-[12px] text-[var(--text-2)] leading-normal">{errorMessage}</p>

          {wakeSuccess ? (
            <div className="flex items-center gap-2 pt-1 text-[var(--semantic-green-ink)] font-medium">
              <Icon name="check-circle" size={13} />
              <span>Server is operational! You can now retry your request.</span>
              {onRetry && (
                <button
                  type="button"
                  onClick={onRetry}
                  className="ml-2 underline font-semibold cursor-pointer"
                >
                  Retry now
                </button>
              )}
            </div>
          ) : (
            isServerIssue && (
              <div className="flex items-center gap-2 pt-1.5 flex-wrap">
                <button
                  type="button"
                  onClick={handleWakeUp}
                  disabled={waking}
                  className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white text-[11px] font-semibold transition-transform active:scale-95 disabled:opacity-60 cursor-pointer"
                >
                  {waking ? (
                    <>
                      <Icon name="loader" size={11} className="animate-spin" />
                      <span>Waking up server...</span>
                    </>
                  ) : (
                    <>
                      <Icon name="zap" size={11} className="text-amber-300" />
                      <span>Wake Up Server</span>
                    </>
                  )}
                </button>
                {onRetry && !waking && (
                  <button
                    type="button"
                    onClick={onRetry}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-[var(--surface-overlay)] border border-[var(--panel-border-color)] text-[var(--text-1)] text-[11px] font-medium transition-colors hover:bg-[var(--fill-hover)] active:scale-95 cursor-pointer"
                  >
                    <Icon name="refresh" size={11} />
                    <span>Retry</span>
                  </button>
                )}
              </div>
            )
          )}
        </div>
      </div>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          className="text-[var(--text-3)] hover:text-[var(--text-1)] p-1 rounded-[6px] transition-colors focus:outline-none shrink-0"
          title="Dismiss error"
          aria-label="Dismiss error"
        >
          <Icon name="x" size={13} />
        </button>
      )}
    </div>
  );
};
