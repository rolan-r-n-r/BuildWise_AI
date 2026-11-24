/**
 * useServerHealth.ts — Intelligent Server Availability & Health Polling Hook.
 * Manages states: CHECKING → ONLINE / OFFLINE → WAKING_UP → ONLINE / ERROR.
 * Conforms to Vercel React Best Practices: cleans up intervals, avoids redundant renders,
 * handles unmounts, and provides smooth progress telemetry.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  checkBackendHealth,
  triggerServerWakeUp,
  type ServerHealthStatus,
} from '../services/serverHealthService';

export interface ServerHealthState {
  status: ServerHealthStatus;
  isOnline: boolean;
  justWokeUp: boolean;
  latencyMs: number | null;
  message: string;
  elapsedSeconds: number;
  estimatedTotalSeconds: number;
  progressPercent: number;
  lastChecked: Date | null;
  errorDetail: string | null;
}

const ESTIMATED_COLD_START_SEC = 60;
const MAX_POLLING_DURATION_SEC = 120;
const PASSIVE_CHECK_TIMEOUT_MS = 5000;
const ACTIVE_POLL_TIMEOUT_MS = 14000;
const POLL_INTERVAL_MS = 2500;

export function useServerHealth(options?: {
  autoCheck?: boolean;
  onOnline?: () => void;
}) {
  const { autoCheck = true, onOnline } = options ?? {};

  const [status, setStatus] = useState<ServerHealthStatus>('CHECKING');
  const [justWokeUp, setJustWokeUp] = useState<boolean>(false);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [message, setMessage] = useState<string>('Checking backend status...');
  const [elapsedSeconds, setElapsedSeconds] = useState<number>(0);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const [errorDetail, setErrorDetail] = useState<string | null>(null);

  // Stable event handler ref following Vercel React Best Practices
  const onOnlineRef = useRef(onOnline);
  useEffect(() => {
    onOnlineRef.current = onOnline;
  }, [onOnline]);

  // References to prevent re-entrant calls, manage timers and aborts
  const isMountedRef = useRef<boolean>(true);
  const isWakingRef = useRef<boolean>(false);
  const pollTimerRef = useRef<number | null>(null);
  const tickerTimerRef = useRef<number | null>(null);
  const wakeStartTimeRef = useRef<number>(0);
  const successTimerRef = useRef<number | null>(null);

  const clearAllTimers = useCallback(() => {
    if (pollTimerRef.current !== null) {
      window.clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    if (tickerTimerRef.current !== null) {
      window.clearInterval(tickerTimerRef.current);
      tickerTimerRef.current = null;
    }
    if (successTimerRef.current !== null) {
      window.clearTimeout(successTimerRef.current);
      successTimerRef.current = null;
    }
  }, []);

  const checkHealth = useCallback(
    async (skipCache = false, customTimeoutMs?: number): Promise<boolean> => {
      if (!isMountedRef.current) return false;

      const timeoutMs = customTimeoutMs ?? PASSIVE_CHECK_TIMEOUT_MS;
      const result = await checkBackendHealth({ timeoutMs, skipCache });
      if (!isMountedRef.current) return false;

      setLastChecked(new Date(result.timestamp));
      setLatencyMs(result.latencyMs);

      if (result.isOnline) {
        setStatus('ONLINE');
        setMessage(result.message || 'BuildWise is ready. All systems operational.');
        setErrorDetail(null);
        return true;
      } else {
        if (!isWakingRef.current) {
          setStatus('OFFLINE');
          setMessage('Our backend server is currently sleeping.');
        }
        return false;
      }
    },
    []
  );

  const startPolling = useCallback(() => {
    clearAllTimers();
    wakeStartTimeRef.current = Date.now();
    setElapsedSeconds(0);

    // Ticker timer for seconds counter and progress bar
    tickerTimerRef.current = window.setInterval(() => {
      if (!isMountedRef.current) return;
      const elapsed = Math.floor((Date.now() - wakeStartTimeRef.current) / 1000);
      setElapsedSeconds(elapsed);

      if (elapsed >= MAX_POLLING_DURATION_SEC) {
        clearAllTimers();
        isWakingRef.current = false;
        if (isMountedRef.current) {
          setStatus('ERROR');
          setMessage('The server is taking longer than expected. You can retry in a moment.');
          setErrorDetail('Timeout reached while waiting for server startup.');
        }
      }
    }, 1000);

    // Progressive health probe loop with generous queue timeout
    const probeNext = async () => {
      if (!isMountedRef.current || !isWakingRef.current) return;

      const currentElapsed = Math.floor((Date.now() - wakeStartTimeRef.current) / 1000);
      if (currentElapsed >= MAX_POLLING_DURATION_SEC) {
        clearAllTimers();
        isWakingRef.current = false;
        if (isMountedRef.current) {
          setStatus('ERROR');
          setMessage('The server is taking longer than expected. You can retry in a moment.');
          setErrorDetail('Timeout reached while waiting for server startup.');
        }
        return;
      }

      // Check health with ACTIVE_POLL_TIMEOUT_MS (14s) so Render's queued request
      // completes the moment port 8000 opens
      const healthy = await checkHealth(true, ACTIVE_POLL_TIMEOUT_MS);
      if (!isMountedRef.current || !isWakingRef.current) return;

      if (healthy) {
        clearAllTimers();
        isWakingRef.current = false;
        setStatus('ONLINE');
        setMessage("You're all set! BuildWise is ready.");
        setJustWokeUp(true);

        successTimerRef.current = window.setTimeout(() => {
          if (isMountedRef.current) {
            setJustWokeUp(false);
          }
        }, 4500);

        onOnlineRef.current?.();
        return;
      }

      const elapsed = (Date.now() - wakeStartTimeRef.current) / 1000;
      if (elapsed < MAX_POLLING_DURATION_SEC && isWakingRef.current) {
        pollTimerRef.current = window.setTimeout(probeNext, POLL_INTERVAL_MS);
      }
    };

    // First health probe after 2s
    pollTimerRef.current = window.setTimeout(probeNext, 2000);
  }, [checkHealth, clearAllTimers]);

  const wakeUp = useCallback(async () => {
    if (isWakingRef.current) return; // Guard against duplicate concurrent requests
    isWakingRef.current = true;

    setStatus('WAKING_UP');
    setJustWokeUp(false);
    setMessage('Getting BuildWise ready for you...');
    setErrorDetail(null);

    // CRITICAL: Start UI timer & polling immediately at t=0!
    // Do NOT await triggerServerWakeUp before starting the clock!
    startPolling();

    // Concurrently dispatch wake-up probe
    try {
      void triggerServerWakeUp();
    } catch {
      // non-critical: polling will detect when online
    }
  }, [startPolling]);

  // Initial check on mount
  useEffect(() => {
    isMountedRef.current = true;

    if (autoCheck) {
      void checkHealth(false);
    }

    const handleWindowOnline = () => {
      void checkHealth(true);
    };
    const handleWindowOffline = () => {
      setStatus('OFFLINE');
      setMessage('Your device is currently offline.');
    };

    window.addEventListener('online', handleWindowOnline);
    window.addEventListener('offline', handleWindowOffline);

    return () => {
      isMountedRef.current = false;
      isWakingRef.current = false;
      clearAllTimers();
      window.removeEventListener('online', handleWindowOnline);
      window.removeEventListener('offline', handleWindowOffline);
    };
  }, [autoCheck, checkHealth, clearAllTimers]);

  // Derived progress percentage (0 - 100%)
  // Smoothly advances to 92% at ESTIMATED_COLD_START_SEC (60s),
  // then gently advances up to 98% if cold-start takes up to MAX_POLLING_DURATION_SEC (120s),
  // and snaps to 100% the moment status is ONLINE.
  let progressPercent = 0;
  if (status === 'ONLINE') {
    progressPercent = 100;
  } else if (status === 'WAKING_UP') {
    if (elapsedSeconds <= ESTIMATED_COLD_START_SEC) {
      progressPercent = Math.round((elapsedSeconds / ESTIMATED_COLD_START_SEC) * 92);
    } else {
      const extraRatio =
        (elapsedSeconds - ESTIMATED_COLD_START_SEC) /
        (MAX_POLLING_DURATION_SEC - ESTIMATED_COLD_START_SEC);
      progressPercent = Math.min(98, 92 + Math.round(extraRatio * 6));
    }
  }

  return {
    status,
    isOnline: status === 'ONLINE',
    justWokeUp,
    latencyMs,
    message,
    elapsedSeconds,
    estimatedTotalSeconds: ESTIMATED_COLD_START_SEC,
    progressPercent,
    lastChecked,
    errorDetail,
    wakeUp,
    checkHealth: () => checkHealth(true),
  };
}
