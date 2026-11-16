/**
 * aiProviderApi.ts — Frontend client service for AI Provider BYOK management.
 * Communicates with backend endpoints (/api/ai/*) with authenticated session credentials.
 */
import { API_BASE_URL } from './api';

export interface ProviderCatalogItem {
  id: string;
  name: string;
  description: string;
  models: string[];
  requires_api_key: boolean;
  supports_custom_url: boolean;
  icon: string;
}

export interface UserAICredentialSummary {
  provider: string;
  key_hint: string;
  base_url?: string | null;
  selected_model?: string | null;
  status: 'connected' | 'invalid_key' | 'rate_limited' | 'error';
  last_validated_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface UserAIPreferenceRecord {
  user_id: string;
  preferred_provider: string;
  preferred_model?: string | null;
  fallback_to_deterministic: boolean;
  updated_at: string;
}

export interface UserAIConfigResponse {
  configured_providers: UserAICredentialSummary[];
  preference: UserAIPreferenceRecord;
  is_production: boolean;
  server_default_provider: string;
}

export interface ValidateCredentialRequest {
  provider: string;
  api_key?: string;
  base_url?: string;
  model?: string;
}

export interface ValidateCredentialResponse {
  valid: boolean;
  message: string;
  available_models: string[];
}

export interface ConnectProviderRequest {
  provider: string;
  api_key?: string;
  base_url?: string;
  selected_model?: string;
  validate_first?: boolean;
}

export interface UpdatePreferenceRequest {
  preferred_provider: string;
  preferred_model?: string | null;
  fallback_to_deterministic?: boolean;
}

async function handleApiError(resp: Response, fallbackMessage: string): Promise<never> {
  const errorData = await resp.json().catch(() => ({}));
  let message = fallbackMessage;
  if (typeof errorData.detail === 'string') {
    message = errorData.detail;
  } else if (Array.isArray(errorData.detail) && errorData.detail.length > 0) {
    message = errorData.detail.map((e: any) => e.msg || String(e)).join('; ');
  } else if (errorData.message) {
    message = errorData.message;
  }
  throw new Error(message);
}

/** Fetches full catalog of supported AI providers. */
export async function fetchSupportedProviders(): Promise<ProviderCatalogItem[]> {
  const resp = await fetch(`${API_BASE_URL}/api/ai/providers`, {
    credentials: 'include',
  });
  if (!resp.ok) {
    await handleApiError(resp, `Failed to fetch provider catalog (${resp.status})`);
  }
  return resp.json();
}

/** Fetches user's configured providers and active preferences. */
export async function fetchUserAIConfig(): Promise<UserAIConfigResponse> {
  const resp = await fetch(`${API_BASE_URL}/api/ai/config`, {
    credentials: 'include',
  });
  if (!resp.ok) {
    await handleApiError(resp, `Failed to load AI provider configurations (${resp.status})`);
  }
  return resp.json();
}

/** Validates credentials or custom base URL with remote provider. */
export async function validateProviderCredential(
  payload: ValidateCredentialRequest
): Promise<ValidateCredentialResponse> {
  const resp = await fetch(`${API_BASE_URL}/api/ai/validate`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    await handleApiError(resp, `Validation request failed (${resp.status})`);
  }
  return resp.json();
}

/** Saves an encrypted API key for the user. */
export async function connectProvider(
  payload: ConnectProviderRequest
): Promise<UserAICredentialSummary> {
  const resp = await fetch(`${API_BASE_URL}/api/ai/providers`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    await handleApiError(resp, `Failed to connect provider (${resp.status})`);
  }
  return resp.json();
}

/** Disconnects and permanently deletes an API key. */
export async function disconnectProvider(
  provider: string
): Promise<{ success: boolean; message: string }> {
  const resp = await fetch(`${API_BASE_URL}/api/ai/providers/${encodeURIComponent(provider)}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!resp.ok) {
    await handleApiError(resp, `Failed to disconnect provider (${resp.status})`);
  }
  return resp.json();
}

/** Updates user's preferred provider and model. */
export async function updateAIPreference(
  payload: UpdatePreferenceRequest
): Promise<UserAIPreferenceRecord> {
  const resp = await fetch(`${API_BASE_URL}/api/ai/preference`, {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) {
    await handleApiError(resp, `Failed to update preference (${resp.status})`);
  }
  return resp.json();
}
