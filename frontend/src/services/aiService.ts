import type { AnalysisRequest, AnalysisResponse } from './types';
import { env } from '../config/env';

export interface BackendStatus {
  status: string;
  groq: boolean;
  gemini: boolean;
  openai?: boolean;
  anthropic?: boolean;
  ollama?: boolean;
  default_provider: string;
  deterministic_engine?: boolean;
  byok_supported?: boolean;
  user_configured_providers?: string[];
  user_preferred_provider?: string;
  user_preferred_model?: string;
  configured_models?: Record<string, string>;
}

/**
 * Checks server health and which LLM providers have API keys configured
 */
export async function fetchBackendStatus(): Promise<BackendStatus> {
  const resp = await fetch(`${env.VITE_API_URL}/api/status`, {
    credentials: 'include',
  });
  if (!resp.ok) {
    throw new Error(`Failed to fetch backend status: ${resp.status}`);
  }
  return resp.json();
}

export interface FeasibilityResult {
  data: AnalysisResponse;
  fallbackTriggered: boolean;
  fallbackReason?: string;
}

/**
 * Dispatches feasibility analysis request to the secure backend proxy
 */
export async function generateFeasibilityReport(
  request: AnalysisRequest,
  signal?: AbortSignal
): Promise<FeasibilityResult> {
  let resp: Response;
  try {
    resp = await fetch(`${env.VITE_API_URL}/api/analyze`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      credentials: 'include',
      body: JSON.stringify(request),
      signal,
    });
  } catch (err: unknown) {
    if (signal?.aborted) throw err;
    throw new Error(
      'BuildWise backend is currently sleeping or unreachable. Please wake up the server or retry shortly.'
    );
  }

  if (!resp.ok) {
    const errorData = await resp.json().catch(() => ({}));
    const is50x = resp.status === 502 || resp.status === 503 || resp.status === 504;
    const fallbackMsg = is50x
      ? 'BuildWise backend is temporarily unavailable (sleeping on free tier or restarting).'
      : `Analysis request failed with status: ${resp.status}`;
    throw new Error(errorData.detail || fallbackMsg);
  }

  const data: AnalysisResponse = await resp.json();
  const providerUsed = data.ai_metadata?.provider_used || '';
  const fallbackTriggered =
    request.ai_provider !== 'mock' && providerUsed.includes('mock_fallback');
  const fallbackReason = data.ai_metadata?.fallback_reason;

  return {
    data,
    fallbackTriggered,
    fallbackReason,
  };
}
