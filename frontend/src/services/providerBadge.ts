/**
 * providerBadge.ts — the ONE vocabulary for "who will author this narrative?"
 * ===========================================================================
 * The Report Narrative Engine panel used to call the built-in
 * deterministic engine "Live" (and the header called that same engine
 * "Offline"), so one screen made two contradictory claims. The label is now a
 * function of two facts that are actually probed at render time:
 *
 *   - is the backend answering?  (no  => Offline, whatever is selected)
 *   - which author is selected and is its key configured?
 *       mock                      => Deterministic
 *       hosted, key configured    => Live
 *       hosted, no key            => Fallback (the deterministic engine authors)
 *       ollama (no health probe)  => Unknown, never fabricated as Live
 *
 * Kept pure and dependency-free so both the panel and its pins read the same
 * table instead of re-spelling labels.
 */

export type ProviderState = 'live' | 'fallback' | 'unknown' | 'deterministic' | 'offline';

export const PROVIDER_STATE_LABEL: Record<ProviderState, string> = {
  live: 'Live',
  fallback: 'Fallback',
  unknown: 'Unknown',
  deterministic: 'Deterministic',
  offline: 'Offline',
};

/** Backend reachability overrides every provider-specific claim. */
export function effectiveProviderState(
  selected: ProviderState,
  engineOnline: boolean,
): ProviderState {
  return engineOnline ? selected : 'offline';
}
