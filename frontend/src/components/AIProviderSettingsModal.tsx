/**
 * AIProviderSettingsModal.tsx — Apple HIG-grade AI Provider BYOK Management Modal.
 * Allows users to view, validate, connect, configure, and disconnect AI providers.
 * Enforces zero-key deterministic availability while providing secure user credential management.
 */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Icon, type IconName } from './Icon';
import {
  fetchSupportedProviders,
  fetchUserAIConfig,
  validateProviderCredential,
  connectProvider,
  disconnectProvider,
  updateAIPreference,
  type ProviderCatalogItem,
  type UserAICredentialSummary,
  type UserAIConfigResponse,
} from '../services/aiProviderApi';

interface AIProviderSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfigChanged?: (preferredProvider: string, preferredModel?: string) => void;
}

function sanitizeApiKeyInput(val: string): string {
  if (!val) return '';
  // Strip whitespace, including zero-width spaces, BOM, and non-breaking spaces
  let cleaned = val.replace(/^[\s\u200B\uFEFF\u200E\u200F\u00A0]+|[\s\u200B\uFEFF\u200E\u200F\u00A0]+$/g, '');
  // Strip surrounding single or double quotes
  if ((cleaned.startsWith('"') && cleaned.endsWith('"')) || (cleaned.startsWith("'") && cleaned.endsWith("'"))) {
    cleaned = cleaned.slice(1, -1).trim();
  }
  // Strip redundant 'Bearer ' prefix
  if (cleaned.toLowerCase().startsWith('bearer ')) {
    cleaned = cleaned.slice(7).trim();
    if ((cleaned.startsWith('"') && cleaned.endsWith('"')) || (cleaned.startsWith("'") && cleaned.endsWith("'"))) {
      cleaned = cleaned.slice(1, -1).trim();
    }
  }
  return cleaned;
}

function isMaskedKey(val: string): boolean {
  if (!val) return true;
  const trimmed = val.trim();
  if (!trimmed) return true;
  if (/^[\u2022\u25cf\*\.\s]+$/.test(trimmed)) return true;
  if (trimmed.includes('...') || trimmed.includes('•••') || trimmed.includes('●●●') || trimmed.includes('***')) return true;
  return false;
}

export const AIProviderSettingsModal: React.FC<AIProviderSettingsModalProps> = ({
  isOpen,
  onClose,
  onConfigChanged,
}) => {
  const modalRef = useRef<HTMLDivElement>(null);
  const [catalog, setCatalog] = useState<ProviderCatalogItem[]>([]);
  const [config, setConfig] = useState<UserAIConfigResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Active provider being edited/configured
  const [editingProvider, setEditingProvider] = useState<ProviderCatalogItem | null>(null);
  const [apiKeyInput, setApiKeyInput] = useState<string>('');
  const [showApiKey, setShowApiKey] = useState<boolean>(false);
  const [selectedModel, setSelectedModel] = useState<string>('');
  const [baseUrlInput, setBaseUrlInput] = useState<string>('');

  // Validation & Saving states
  const [isValidating, setIsValidating] = useState<boolean>(false);
  const [validationResult, setValidationResult] = useState<{ valid: boolean; message: string; available_models?: string[] } | null>(null);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [isDisconnecting, setIsDisconnecting] = useState<string | null>(null);
  const [confirmDisconnect, setConfirmDisconnect] = useState<string | null>(null);

  // Load catalog and current config
  const loadData = useCallback(async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const cat = await fetchSupportedProviders().catch(() => []);
      setCatalog(cat);
      try {
        const userConf = await fetchUserAIConfig();
        setConfig(userConf);
      } catch (authErr: any) {
        // User is a guest or not yet authenticated; catalog still operates deterministically
        setConfig(null);
      }
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to load AI provider settings.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      loadData();
      setEditingProvider(null);
      setValidationResult(null);
    }
  }, [isOpen, loadData]);

  // Focus trap & Escape key
  useEffect(() => {
    if (!isOpen) return;
    modalRef.current?.focus();
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (editingProvider) {
          setEditingProvider(null);
        } else if (confirmDisconnect) {
          setConfirmDisconnect(null);
        } else {
          onClose();
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, editingProvider, confirmDisconnect, onClose]);

  // Body scroll lock
  useEffect(() => {
    if (!isOpen) return;
    const original = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = original;
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const handleStartConfigure = (provider: ProviderCatalogItem) => {
    setEditingProvider(provider);
    setValidationResult(null);
    setApiKeyInput('');
    setShowApiKey(false);

    const cred = config?.configured_providers.find((c) => c.provider === provider.id);
    setSelectedModel(cred?.selected_model || provider.models[0] || '');
    setBaseUrlInput(cred?.base_url || (provider.id === 'ollama' ? 'http://localhost:11434' : ''));
  };

  const handleValidate = async (overrideKey?: string) => {
    if (!editingProvider) return;
    const rawKey = typeof overrideKey === 'string' ? overrideKey : apiKeyInput;
    const cleaned = sanitizeApiKeyInput(rawKey);
    const isMaskedOrEmpty = isMaskedKey(cleaned);
    const keyToTest = isMaskedOrEmpty ? undefined : cleaned;
    if (!keyToTest && editingProvider.requires_api_key && !getProviderCred(editingProvider.id)) {
      setValidationResult({ valid: false, message: 'Please enter an API key to test connection.' });
      return;
    }

    setIsValidating(true);
    setValidationResult(null);
    try {
      const res = await validateProviderCredential({
        provider: editingProvider.id,
        api_key: keyToTest,
        base_url: baseUrlInput.trim() || undefined,
        model: selectedModel,
      });
      setValidationResult({ valid: res.valid, message: res.message, available_models: res.available_models });
      if (res.available_models && res.available_models.length > 0) {
        if (!selectedModel || !res.available_models.includes(selectedModel)) {
          setSelectedModel(res.available_models[0]);
        }
      }
      return res;
    } catch (err: any) {
      setValidationResult({ valid: false, message: err.message || 'Validation request failed.' });
      return null;
    } finally {
      setIsValidating(false);
    }
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingProvider) return;

    const cleaned = sanitizeApiKeyInput(apiKeyInput);
    const isMaskedOrEmpty = isMaskedKey(cleaned);
    const keyToSave = isMaskedOrEmpty ? undefined : cleaned;

    const cred = config?.configured_providers.find((c) => c.provider === editingProvider.id);
    if (!cred && editingProvider.requires_api_key && !keyToSave) {
      setValidationResult({ valid: false, message: 'Please enter an API key to connect this provider.' });
      return;
    }

    setIsSaving(true);
    setValidationResult(null);
    try {
      let modelToSave = selectedModel;
      if (validationResult?.available_models && validationResult.available_models.length > 0) {
        if (!modelToSave || !validationResult.available_models.includes(modelToSave)) {
          modelToSave = validationResult.available_models[0];
          setSelectedModel(modelToSave);
        }
      }

      const saved = await connectProvider({
        provider: editingProvider.id,
        api_key: keyToSave,
        base_url: baseUrlInput.trim() || undefined,
        selected_model: modelToSave || undefined,
        validate_first: Boolean(keyToSave || (editingProvider.id === 'ollama' && baseUrlInput.trim())),
      });
      try {
        await updateAIPreference({
          preferred_provider: editingProvider.id,
          preferred_model: saved.selected_model || modelToSave || null,
          fallback_to_deterministic: true,
        });
      } catch (prefErr) {
        console.warn('Could not set preferred provider after save', prefErr);
      }
      await loadData();
      setEditingProvider(null);
      if (onConfigChanged) {
        onConfigChanged(editingProvider.id, saved.selected_model || modelToSave);
      }
    } catch (err: any) {
      setValidationResult({ valid: false, message: err.message || 'Failed to save configuration.' });
    } finally {
      setIsSaving(false);
    }
  };

  const handleDisconnect = async (providerId: string) => {
    setIsDisconnecting(providerId);
    try {
      await disconnectProvider(providerId);
      await loadData();
      setConfirmDisconnect(null);
      if (onConfigChanged) {
        onConfigChanged('deterministic');
      }
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to disconnect provider.');
    } finally {
      setIsDisconnecting(null);
    }
  };

  const handleSetPreferred = async (providerId: string, model?: string) => {
    try {
      await updateAIPreference({
        preferred_provider: providerId,
        preferred_model: model || null,
        fallback_to_deterministic: true,
      });
      await loadData();
      if (onConfigChanged) {
        onConfigChanged(providerId, model);
      }
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to update preferred provider.');
    }
  };

  const getProviderCred = (providerId: string): UserAICredentialSummary | undefined => {
    return config?.configured_providers.find((c) => c.provider === providerId);
  };

  const preferredProvider = config?.preference?.preferred_provider || 'deterministic';

  const mapIconName = (raw: string): IconName => {
    switch (raw) {
      case 'shield':
        return 'shield-check';
      case 'zap':
        return 'zap';
      case 'sparkles':
        return 'sparkles';
      case 'cpu':
        return 'cpu';
      case 'server':
        return 'server';
      default:
        return 'settings';
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="byok-settings-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      className="fixed inset-0 z-[1250] flex items-center justify-center p-4 bg-slate-900/60 dark:bg-black/75 select-none"
    >
      <div
        ref={modalRef}
        tabIndex={-1}
        className="w-full max-w-[620px] bg-white dark:bg-slate-900 rounded-[20px] border border-slate-200/90 dark:border-slate-800 bw-glass-dialog shadow-2xl p-6 relative overflow-hidden animate-in fade-in zoom-in-95 duration-150 outline-none max-h-[90vh] flex flex-col"
      >
        {/* Header */}
        <div className="flex items-center justify-between pb-4 border-b border-slate-200/80 dark:border-slate-800 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-blue-50 dark:bg-blue-950/70 text-[var(--accent)] border border-blue-200 dark:border-blue-900/80 flex items-center justify-center shadow-xs">
              <Icon name="key" size={18} />
            </div>
            <div>
              <h2 id="byok-settings-title" className="text-[17px] font-bold text-[var(--text-1)]">
                AI Provider Management (BYOK)
              </h2>
              <p className="text-[12px] text-[var(--text-2)]">
                Connect your personal API keys or use the built-in deterministic engine.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close AI Settings"
            className="w-8 h-8 rounded-full text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 flex items-center justify-center transition-colors cursor-pointer"
          >
            <Icon name="x" size={16} />
          </button>
        </div>

        {/* Error notification banner */}
        {errorMsg && (
          <div className="mt-3 p-3 rounded-xl bg-red-50 dark:bg-red-950/50 border border-red-200 dark:border-red-900/60 text-red-700 dark:text-red-300 text-[12px] flex items-center justify-between shrink-0">
            <span>{errorMsg}</span>
            <button
              type="button"
              onClick={() => setErrorMsg(null)}
              className="text-red-500 hover:text-red-700 font-bold ml-2"
            >
              ×
            </button>
          </div>
        )}

        {/* Content Area */}
        <div className="overflow-y-auto pr-1 py-4 flex-1 scrollbar-apple space-y-4">
          {loading ? (
            <div className="py-12 flex flex-col items-center justify-center gap-3 text-slate-400">
              <span className="w-6 h-6 border-2 border-slate-300 dark:border-slate-700 border-t-[var(--accent)] rounded-full animate-spin" />
              <span className="text-[12px]">Loading providers and security credentials...</span>
            </div>
          ) : editingProvider ? (
            /* Configure / Connect Provider Form */
            <form onSubmit={handleSave} className="space-y-4 animate-in fade-in duration-150">
              <div className="flex items-center gap-3 p-3.5 bg-slate-50 dark:bg-slate-800/60 rounded-xl border border-slate-200/80 dark:border-slate-700/60">
                <div className="w-8 h-8 rounded-lg bg-[var(--fill)] flex items-center justify-center text-[var(--accent)] shrink-0">
                  <Icon name={mapIconName(editingProvider.icon)} size={16} />
                </div>
                <div className="min-w-0 flex-1">
                  <h3 className="text-[14px] font-bold text-[var(--text-1)]">{editingProvider.name}</h3>
                  <p className="text-[11px] text-[var(--text-2)]">{editingProvider.description}</p>
                </div>
              </div>

              {/* API Key Input */}
              {editingProvider.requires_api_key && (
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <label
                      htmlFor="byok-api-key"
                      className="text-[12px] font-semibold text-[var(--text-1)]"
                    >
                      API Key {getProviderCred(editingProvider.id) && '(Leave blank to keep existing key)'}
                    </label>
                    {getProviderCred(editingProvider.id) && (
                      <span className="text-[11px] font-mono text-[var(--text-2)]">
                        Current: {getProviderCred(editingProvider.id)?.key_hint}
                      </span>
                    )}
                  </div>
                  <div className="relative">
                    <input
                      id="byok-api-key"
                      name="byok_vault_key_input"
                      type={showApiKey ? 'text' : 'password'}
                      value={apiKeyInput}
                      onChange={(e) => setApiKeyInput(e.target.value)}
                      onPaste={(e) => {
                        e.preventDefault();
                        const rawPasted = e.clipboardData.getData('text');
                        const cleaned = sanitizeApiKeyInput(rawPasted);
                        if (cleaned) {
                          setApiKeyInput(cleaned);
                        }
                      }}
                      placeholder={
                        getProviderCred(editingProvider.id)
                          ? 'Leave empty to keep saved key, or paste new key...'
                          : `Paste your ${editingProvider.name} API key...`
                      }
                      autoComplete="new-password"
                      data-lpignore="true"
                      data-1p-ignore="true"
                      data-form-type="other"
                      className="w-full h-10 px-3 pr-10 text-[13px] font-mono bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-xl text-[var(--text-1)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40 transition-colors"
                    />
                    <button
                      type="button"
                      onClick={() => setShowApiKey(!showApiKey)}
                      aria-label={showApiKey ? 'Hide API key' : 'Show API key'}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors cursor-pointer"
                    >
                      <Icon name={showApiKey ? 'eye-off' : 'eye'} size={15} />
                    </button>
                  </div>
                  <p className="text-[11px] text-[var(--text-3)]">
                    Encrypted at rest using AES-256-GCM. Keys are decrypted only server-side during authorized execution.
                  </p>
                </div>
              )}

              {/* Base URL Input for Ollama / Self-hosted */}
              {editingProvider.supports_custom_url && (
                <div className="space-y-1.5">
                  <label htmlFor="byok-base-url" className="text-[12px] font-semibold text-[var(--text-1)]">
                    Ollama Endpoint URL
                  </label>
                  <input
                    id="byok-base-url"
                    type="url"
                    value={baseUrlInput}
                    onChange={(e) => setBaseUrlInput(e.target.value)}
                    placeholder="http://localhost:11434"
                    className="w-full h-10 px-3 text-[13px] font-mono bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-xl text-[var(--text-1)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40 transition-colors"
                  />
                  <p className="text-[11px] text-[var(--text-3)]">
                    Local instances use http://localhost:11434. In production, use a public HTTPS tunnel (e.g. ngrok).
                  </p>
                </div>
              )}

              {/* Model Selection Dropdown */}
              <div className="space-y-1.5">
                <label htmlFor="byok-model-select" className="text-[12px] font-semibold text-[var(--text-1)]">
                  Preferred Model
                </label>
                <select
                  id="byok-model-select"
                  value={selectedModel}
                  onChange={(e) => setSelectedModel(e.target.value)}
                  className="w-full h-10 px-3 text-[13px] bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-xl text-[var(--text-1)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40 transition-colors cursor-pointer"
                >
                  {Array.from(new Set([
                    ...(validationResult?.available_models || []),
                    ...(editingProvider.models || []),
                    ...(selectedModel ? [selectedModel] : [])
                  ])).filter(Boolean).map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </div>

              {/* Validation Feedback */}
              {validationResult && (
                <div
                  className={`p-3 rounded-xl text-[12px] flex items-start gap-2 ${validationResult.valid
                    ? 'bg-emerald-50 dark:bg-emerald-950/50 border border-emerald-200 dark:border-emerald-900/60 text-emerald-700 dark:text-emerald-300'
                    : 'bg-red-50 dark:bg-red-950/50 border border-red-200 dark:border-red-900/60 text-red-700 dark:text-red-300'
                    }`}
                >
                  <Icon
                    name={validationResult.valid ? 'check-circle' : 'alert-triangle'}
                    size={15}
                    className="shrink-0 mt-0.5"
                  />
                  <span>{validationResult.message}</span>
                </div>
              )}

              {/* Form Action Buttons */}
              <div className="flex items-center gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => handleValidate()}
                  disabled={
                    isValidating ||
                    (editingProvider.requires_api_key && !apiKeyInput.trim() && !getProviderCred(editingProvider.id))
                  }
                  className="px-3.5 h-10 rounded-xl bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-[12px] font-semibold text-[var(--text-1)] flex items-center gap-1.5 transition-colors cursor-pointer disabled:opacity-40"
                >
                  {isValidating ? (
                    <>
                      <span className="w-3.5 h-3.5 border-2 border-slate-400 border-t-transparent rounded-full animate-spin" />
                      <span>Verifying...</span>
                    </>
                  ) : (
                    <>
                      <Icon name="refresh" size={13} />
                      <span>Test Connection</span>
                    </>
                  )}
                </button>

                <div className="flex-1" />

                <button
                  type="button"
                  onClick={() => setEditingProvider(null)}
                  className="px-3.5 h-10 rounded-xl text-[12px] font-medium text-[var(--text-2)] hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer"
                >
                  Cancel
                </button>

                <button
                  type="submit"
                  disabled={isSaving}
                  className="px-4 h-10 rounded-xl bg-[var(--accent)] hover:brightness-110 active:brightness-95 text-white text-[12px] font-semibold flex items-center gap-1.5 transition-[background-color,filter,opacity] shadow-xs cursor-pointer disabled:opacity-50"
                >
                  {isSaving ? (
                    <>
                      <span className="w-3.5 h-3.5 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                      <span>Encrypting & Saving...</span>
                    </>
                  ) : (
                    <span>Save Configuration</span>
                  )}
                </button>
              </div>
            </form>
          ) : (
            /* Provider List Overview */
            <div className="space-y-3">
              {/* Active Strategy Card */}
              <div className="p-3.5 rounded-xl bg-blue-50/70 dark:bg-blue-950/40 border border-blue-200/80 dark:border-blue-900/60 flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-lg bg-blue-100 dark:bg-blue-900/60 text-[var(--accent)] flex items-center justify-center shrink-0">
                    <Icon name="sparkles" size={15} />
                  </div>
                  <div>
                    <div className="text-[11px] font-semibold tracking-wide text-blue-600 dark:text-blue-400 uppercase">
                      Active Execution Strategy
                    </div>
                    <div className="text-[13px] font-bold text-[var(--text-1)]">
                      {preferredProvider === 'deterministic'
                        ? 'Built-in Deterministic Engine'
                        : `${catalog.find((c) => c.id === preferredProvider)?.name || preferredProvider} (BYOK)`}
                    </div>
                  </div>
                </div>
                <span className="px-2.5 py-1 rounded-full text-[10px] font-bold bg-white dark:bg-slate-900 text-blue-600 dark:text-blue-300 border border-blue-200 dark:border-blue-800 shadow-2xs">
                  {preferredProvider === 'deterministic' ? '100% Free · No Key Required' : 'BYOK Active'}
                </span>
              </div>

              {/* Provider List */}
              <div className="space-y-2">
                {catalog.map((provider) => {
                  const cred = getProviderCred(provider.id);
                  const isConfigured = Boolean(cred);
                  const isPreferred = preferredProvider === provider.id;

                  return (
                    <div
                      key={provider.id}
                      className={`p-3.5 rounded-xl border transition-[background-color,border-color] ${isPreferred
                        ? 'border-[var(--accent)]/60 bg-blue-50/20 dark:bg-blue-950/20'
                        : 'border-slate-200/80 dark:border-slate-800 bg-slate-50/60 dark:bg-slate-800/40 hover:border-slate-300 dark:hover:border-slate-700'
                        }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-start gap-3 min-w-0">
                          <div className="w-8 h-8 rounded-lg bg-[var(--fill)] flex items-center justify-center text-[var(--text-1)] shrink-0 mt-0.5">
                            <Icon name={mapIconName(provider.icon)} size={16} />
                          </div>
                          <div className="min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="text-[13px] font-bold text-[var(--text-1)]">
                                {provider.name}
                              </span>

                              {/* Status Badge */}
                              {provider.id === 'deterministic' ? (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-900/60">
                                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                                  Built-in Core
                                </span>
                              ) : isConfigured ? (
                                cred?.status === 'invalid_key' ? (
                                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-red-50 dark:bg-red-950/60 text-red-700 dark:text-red-300 border border-red-200 dark:border-red-900/60">
                                    <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
                                    Invalid Key
                                  </span>
                                ) : (
                                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-900/60">
                                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                                    Connected ({cred?.key_hint})
                                  </span>
                                )
                              ) : (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 border border-slate-200 dark:border-slate-700">
                                  Not Configured
                                </span>
                              )}

                              {isPreferred && (
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-[var(--accent)] text-white shadow-2xs">
                                  Preferred
                                </span>
                              )}
                            </div>

                            <p className="text-[11px] text-[var(--text-2)] mt-1 line-clamp-2">
                              {provider.description}
                            </p>

                            {isConfigured && cred?.selected_model && (
                              <div className="mt-1.5 flex items-center gap-2 text-[11px] font-mono text-[var(--text-2)]">
                                <span>Model: {cred.selected_model}</span>
                              </div>
                            )}
                          </div>
                        </div>

                        {/* Actions */}
                        <div className="flex items-center gap-1.5 shrink-0">
                          {provider.id !== 'deterministic' && (
                            <>
                              <button
                                type="button"
                                onClick={() => handleStartConfigure(provider)}
                                className="px-2.5 py-1 rounded-lg text-[11px] font-semibold text-[var(--text-1)] bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 transition-colors cursor-pointer"
                              >
                                {isConfigured ? 'Edit' : 'Configure'}
                              </button>

                              {isConfigured && (
                                <>
                                  {confirmDisconnect === provider.id ? (
                                    <div className="flex items-center gap-1">
                                      <button
                                        type="button"
                                        onClick={() => handleDisconnect(provider.id)}
                                        disabled={isDisconnecting === provider.id}
                                        className="px-2 py-1 rounded-lg text-[10px] font-bold text-white bg-red-600 hover:bg-red-700 transition-colors cursor-pointer"
                                      >
                                        Confirm
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => setConfirmDisconnect(null)}
                                        className="px-1.5 py-1 rounded-lg text-[10px] text-slate-400 hover:text-slate-200"
                                      >
                                        Cancel
                                      </button>
                                    </div>
                                  ) : (
                                    <button
                                      type="button"
                                      onClick={() => setConfirmDisconnect(provider.id)}
                                      title="Remove API key"
                                      aria-label={`Disconnect ${provider.name}`}
                                      className="p-1.5 rounded-lg text-slate-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950/40 transition-colors cursor-pointer"
                                    >
                                      <Icon name="trash-2" size={13} />
                                    </button>
                                  )}
                                </>
                              )}
                            </>
                          )}

                          {/* Set as preferred button */}
                          {(isConfigured || provider.id === 'deterministic') && !isPreferred && (
                            <button
                              type="button"
                              onClick={() => handleSetPreferred(provider.id, cred?.selected_model || undefined)}
                              className="px-2.5 py-1 rounded-lg text-[11px] font-semibold text-[var(--accent)] hover:bg-blue-50 dark:hover:bg-blue-950/50 transition-colors cursor-pointer"
                            >
                              Use
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Security Assurance Card */}
              <div className="p-3 bg-slate-50 dark:bg-slate-800/40 rounded-xl border border-slate-200/80 dark:border-slate-800 text-[11px] text-[var(--text-3)] flex items-start gap-2">
                <Icon name="shield-check" size={14} className="text-emerald-500 shrink-0 mt-0.5" />
                <span>
                  <strong>Zero Mandate Guarantee:</strong> Providing an API key is completely optional. BuildWise
                  operates immediately with its built-in deterministic civil engineering engine without any key.
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="pt-3 border-t border-slate-200/80 dark:border-slate-800 flex justify-end shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="px-4 h-9 rounded-xl bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-[var(--text-1)] text-[12px] font-medium transition-colors cursor-pointer"
          >
            Close Settings
          </button>
        </div>
      </div>
    </div>
  );
};

export default AIProviderSettingsModal;

