/**
 * serverHealthService.ts — Backend health monitoring & wake-up communication.
 * Handles lightweight health checks (/api/health) and wake-up triggers (/api/wake-up or AWS API Gateway).
 */
import { env } from '../config/env';

export type ServerHealthStatus = 'CHECKING' | 'ONLINE' | 'OFFLINE' | 'WAKING_UP' | 'ERROR';

export interface HealthCheckResult {
  isOnline: boolean;
  status: string;
  latencyMs: number;
  message: string;
  version?: string;
  timestamp: number;
}

export interface WakeUpResult {
  triggered: boolean;
  message: string;
  state?: string;
}

/** Cache the last known online verification briefly (30s) to avoid spamming the backend */
let _lastOnlineCache: { isOnline: boolean; timestamp: number; latencyMs: number } | null = null;
const CACHE_TTL_MS = 30000;

/**
 * Checks server availability via GET /api/health with a fast, bounded timeout.
 * Does not block page rendering or navigation.
 */
export async function checkBackendHealth(options?: {
  timeoutMs?: number;
  skipCache?: boolean;
}): Promise<HealthCheckResult> {
  const timeoutMs = options?.timeoutMs ?? 5000;
  const skipCache = options?.skipCache ?? false;

  const now = Date.now();

  // Fast offline return if client device has no network connectivity
  if (typeof navigator !== 'undefined' && !navigator.onLine) {
    return {
      isOnline: false,
      status: 'offline',
      latencyMs: 0,
      message: 'Your device is currently offline.',
      timestamp: now,
    };
  }

  if (!skipCache && _lastOnlineCache && _lastOnlineCache.isOnline && now - _lastOnlineCache.timestamp < CACHE_TTL_MS) {
    return {
      isOnline: true,
      status: 'healthy',
      latencyMs: _lastOnlineCache.latencyMs,
      message: 'BuildWise backend is operational',
      timestamp: _lastOnlineCache.timestamp,
    };
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const start = performance.now();

  try {
    const url = `${env.VITE_API_URL}/api/health?_t=${now}`;
    const resp = await fetch(url, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: controller.signal,
      cache: 'no-store',
    });
    clearTimeout(timer);
    const latencyMs = Math.round(performance.now() - start);

    if (resp.ok) {
      const data = await resp.json().catch(() => ({}));
      const isHealthy = data.status === 'healthy' || data.status === 'ok';
      if (isHealthy) {
        _lastOnlineCache = { isOnline: true, timestamp: Date.now(), latencyMs };
      }
      return {
        isOnline: isHealthy,
        status: data.status || 'healthy',
        latencyMs,
        message: data.message || 'BuildWise backend is operational',
        version: data.version,
        timestamp: Date.now(),
      };
    }

    _lastOnlineCache = null;
    return {
      isOnline: false,
      status: 'offline',
      latencyMs,
      message: `Backend returned status ${resp.status}`,
      timestamp: Date.now(),
    };
  } catch (err: unknown) {
    clearTimeout(timer);
    _lastOnlineCache = null;
    const latencyMs = Math.round(performance.now() - start);
    const isAbort = err instanceof DOMException && err.name === 'AbortError';

    return {
      isOnline: false,
      status: 'offline',
      latencyMs,
      message: isAbort ? 'Connection timed out' : 'Backend is currently unreachable',
      timestamp: Date.now(),
    };
  }
}

/**
 * Triggers server wake-up.
 * Target URL priority:
 *   1. VITE_WAKEUP_URL (e.g. custom proxy or cloud gateway)
 *   2. ${VITE_API_URL}/api/wake-up (Render Free Tier or continuous backend)
 *
 * Uses a lightweight GET request first to avoid browser CORS preflight OPTIONS
 * round-trips while Render is cold-starting.
 */
export async function triggerServerWakeUp(options?: {
  authToken?: string;
}): Promise<WakeUpResult> {
  const targetUrl = env.VITE_WAKEUP_URL || `${env.VITE_API_URL}/api/wake-up`;
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | null = setTimeout(() => controller.abort(), 8000);

  const headers: Record<string, string> = {
    Accept: 'application/json',
  };
  if (options?.authToken) {
    headers['X-Wakeup-Token'] = options.authToken;
  }

  try {
    // 1. Prefer GET probe: simple CORS request that does NOT trigger an OPTIONS preflight!
    const resp = await fetch(targetUrl, {
      method: 'GET',
      headers,
      signal: controller.signal,
      cache: 'no-store',
    });

    if (resp.ok) {
      if (timer) clearTimeout(timer);
      const data = await resp.json().catch(() => ({}));
      return {
        triggered: true,
        message: data.message || 'Server wake-up initiated successfully.',
        state: data.state,
      };
    }

    // 2. Fall back to POST if the endpoint specifically requires it (e.g. custom webhooks)
    if (resp.status === 405) {
      if (timer) clearTimeout(timer);
      const postController = new AbortController();
      const postTimer = setTimeout(() => postController.abort(), 8000);
      try {
        const postResp = await fetch(targetUrl, {
          method: 'POST',
          headers: { ...headers, 'Content-Type': 'application/json' },
          signal: postController.signal,
          cache: 'no-store',
        });
        clearTimeout(postTimer);
        if (postResp.ok) {
          const postData = await postResp.json().catch(() => ({}));
          return {
            triggered: true,
            message: postData.message || 'Server wake-up initiated successfully.',
            state: postData.state,
          };
        }
      } catch {
        clearTimeout(postTimer);
      }
    }

    if (timer) clearTimeout(timer);
    return {
      triggered: true,
      message: 'Wake-up request transmitted.',
    };
  } catch {
    if (timer) clearTimeout(timer);
    // On free platforms like Render, even an in-flight or queued HTTP connection
    // immediately activates container spin-up.
    return {
      triggered: true,
      message: 'Wake-up packet dispatched to backend host.',
    };
  }
}
