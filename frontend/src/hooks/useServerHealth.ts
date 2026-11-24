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

const ESTIMATED_COLD_START_SEC = 45;
const MAX_POLLING_DURATION_SEC = 75;
const INITIAL_POLL_INTERVAL_MS = 3000;
const MAX_POLL_INTERVAL_MS = 6000;

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
    async (skipCache = false): Promise<boolean> => {
      if (!isMountedRef.current) return false;

      const result = await checkBackendHealth({ timeoutMs: 5000, skipCache });
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

    // Progressive health probe loop with slight backoff
    let attempt = 0;
    const probeNext = async () => {
      if (!isMountedRef.current || !isWakingRef.current) return;

      attempt += 1;
      const healthy = await checkHealth(true);
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
        // Compute backoff: starts at 3000ms, gently steps up to 5000ms
        const delay = Math.min(
          INITIAL_POLL_INTERVAL_MS + attempt * 400,
          MAX_POLL_INTERVAL_MS
        );
        pollTimerRef.current = window.setTimeout(probeNext, delay);
      }
    };

    // First health probe after 3.5s
    pollTimerRef.current = window.setTimeout(probeNext, 3500);
  }, [checkHealth, clearAllTimers]);

  const wakeUp = useCallback(async () => {
    if (isWakingRef.current) return; // Guard against duplicate concurrent requests
    isWakingRef.current = true;

    setStatus('WAKING_UP');
    setJustWokeUp(false);
    setMessage('Getting BuildWise ready for you...');
    setErrorDetail(null);

    try {
      // Step 1: Transmit wake-up packet
      await triggerServerWakeUp();
      if (!isMountedRef.current || !isWakingRef.current) return;

      // Step 2: Begin intelligent availability polling
      startPolling();
    } catch (err: unknown) {
      if (!isMountedRef.current) return;
      isWakingRef.current = false;
      setStatus('ERROR');
      setMessage("We couldn't connect to the server. Please try again.");
      setErrorDetail(err instanceof Error ? err.message : 'Unknown wake-up error');
      clearAllTimers();
    }
  }, [startPolling, clearAllTimers]);

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
  const progressPercent = Math.min(
    Math.round((elapsedSeconds / ESTIMATED_COLD_START_SEC) * 100),
    status === 'ONLINE' ? 100 : 96
  );

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
