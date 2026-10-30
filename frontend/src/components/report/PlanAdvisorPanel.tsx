import React, { useCallback, useEffect, useId, useMemo, useState } from 'react';
import { Icon } from '../Icon';
import { fetchPlanAdvisory, fetchRemediationOptions } from '../../services/api';
import {
  buildAdvisoryRequest,
  deterministicSummary,
  effectLine,
  hashPlan,
  readAdvisorCache,
  readRemediationCache,
  writeAdvisorCache,
  writeRemediationCache,
} from '../../services/planAdvisor';
import type {
  AdvisoryResponse,
  FloorPlanRequest,
  FloorPlanResponse,
  RemediationOption,
} from '../../services/types';
import type { WarningReport } from '../../services/warningReport';

const ADVISOR_TIMEOUT_MS = 8000;
const REMEDIATION_TIMEOUT_MS = 25000;

type AdvisorState = 'loading' | 'ready' | 'offline';

interface PlanAdvisorPanelProps {
  plan: FloorPlanResponse;
  report: WarningReport;
  request: Partial<FloorPlanRequest> | null;
  planVerdict: string;
  isGenerating?: boolean;
  /** Applies the option's validated inputs through the generator and re-solves. */
  onApply: (option: RemediationOption) => void;
  /** Test seams: skip the network and render the given state. */
  testAdvisory?: AdvisoryResponse | null;
  testOptions?: RemediationOption[] | null;
}

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`timeout after ${ms} ms`)), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}

const AdvisorSkeleton: React.FC = () => (
  <div data-testid="advisor-skeleton" aria-busy="true" aria-live="polite" className="space-y-1.5">
    <span className="sr-only">Wording the advisory explanation</span>
    <div className="h-2.5 w-[92%] rounded-full bg-[var(--fill)] animate-pulse" />
    <div className="h-2.5 w-[84%] rounded-full bg-[var(--fill)] animate-pulse" />
    <div className="h-2.5 w-[63%] rounded-full bg-[var(--fill)] animate-pulse" />
  </div>
);

export const PlanAdvisorPanel: React.FC<PlanAdvisorPanelProps> = ({
  plan,
  report,
  request,
  planVerdict,
  isGenerating = false,
  onApply,
  testAdvisory,
  testOptions,
}) => {
  const summary = useMemo(() => deterministicSummary(report, planVerdict), [report, planVerdict]);
  const planHash = useMemo(() => hashPlan(plan, request), [plan, request]);

  const [options, setOptions] = useState<RemediationOption[] | null>(testOptions ?? null);
  // A card that changes the programme (the S2 dwelling-count trade) may only
  // run after the client ticks the deficit acknowledgement.  Reset on a new
  // plan so a tick never travels to a different certificate.
  const [confirmed, setConfirmed] = useState<Record<string, boolean>>({});
  useEffect(() => {
    setConfirmed({});
  }, [planHash]);
  const [optionsState, setOptionsState] = useState<'loading' | 'ready' | 'failed'>(
    testOptions ? 'ready' : 'loading',
  );
  const [optionsNote, setOptionsNote] = useState<string | null>(null);
  const [advisor, setAdvisor] = useState<AdvisoryResponse | null>(testAdvisory ?? null);
  const [advisorState, setAdvisorState] = useState<AdvisorState>(
    testAdvisory ? (testAdvisory.narrative ? 'ready' : 'offline') : 'loading',
  );
  const [offlineReason, setOfflineReason] = useState<string | null>(
    testAdvisory && !testAdvisory.narrative ? testAdvisory.meta.fallback_reason ?? null : null,
  );

  // ---- engine dry-runs (deterministic) --------------------------------
  useEffect(() => {
    if (testOptions) return;
    if (!request) {
      setOptionsState('failed');
      setOptionsNote('No request snapshot is available for this plan.');
      return;
    }
    const cached = readRemediationCache(planHash);
    if (cached) {
      setOptions(cached.options);
      setOptionsState('ready');
      return;
    }
    const controller = new AbortController();
    let cancelled = false;
    setOptionsState('loading');
    setOptionsNote(null);
    const placedRooms = Array.from(
      new Set(
        (plan.multi_storey?.floors ?? [])
          .flatMap((floor) => floor.rooms ?? [])
          .map((room: any) => String(room.room_id).replace(/_F\d+$/, '')),
      ),
    );
    const payload = {
      request: request as FloorPlanRequest,
      warnings: plan.warnings ?? [],
      plan_verdict: planVerdict,
      placed_rooms: placedRooms,
      rotation_alternatives: (plan.site_plan?.rotation_alternatives ??
        (plan.qa as any)?.rotation_alternatives ??
        []) as Array<Record<string, any>>,
      scheme_alternatives: (plan.scheme_alternatives ?? []).map((alt) => ({
        scheme_id: alt.scheme_id,
        label: alt.label,
        feasible: alt.feasible,
        score: alt.score,
      })),
      selected_scheme_id: plan.selected_scheme_id ?? request.selected_scheme_id ?? null,
      // The ladder's chosen rung, so the matching card reads "current" even
      // when the baseline request never named the variant.
      strategy_selected: plan.multi_storey?.strategy_selected ?? null,
      baseline: {
        warning_count: report.totalMessages,
        failure_count: report.tiers.T1.messages,
        relaxation_count: report.relaxations.total,
        plate_area_m2: null,
      },
      plan_hash: planHash,
    };
    withTimeout(fetchRemediationOptions(payload, controller.signal), REMEDIATION_TIMEOUT_MS)
      .then((response) => {
        if (cancelled) return;
        setOptions(response.options);
        setOptionsState('ready');
        writeRemediationCache(planHash, response);
      })
      .catch((error) => {
        if (cancelled) return;
        setOptionsState('failed');
        setOptionsNote(
          error?.name === 'AbortError'
            ? 'Engine dry-run cancelled.'
            : `Next steps could not be measured${error?.status ? ` (HTTP ${error.status})` : ''}: ${
                error?.message || 'the engine did not answer'
              }. The generated plan and its verdict are unchanged; only this remediation preview failed.`,
        );
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [plan, planHash, planVerdict, report, request, testOptions]);

  // ---- advisory wording (optional, never authoritative) ---------------
  useEffect(() => {
    if (testAdvisory !== undefined && testAdvisory !== null) return;
    if (optionsState !== 'ready' || !options) return;
    const cached = readAdvisorCache(planHash);
    if (cached) {
      setAdvisor(cached);
      setAdvisorState(cached.narrative ? 'ready' : 'offline');
      setOfflineReason(cached.meta.fallback_reason ?? null);
      return;
    }
    const controller = new AbortController();
    let cancelled = false;
    setAdvisorState('loading');
    const advisoryPayload = buildAdvisoryRequest(planHash, planVerdict, report, options);
    withTimeout(fetchPlanAdvisory(advisoryPayload, controller.signal), ADVISOR_TIMEOUT_MS)
      .then((response) => {
        if (cancelled) return;
        setAdvisor(response);
        writeAdvisorCache(planHash, response);
        setAdvisorState(response.narrative ? 'ready' : 'offline');
        setOfflineReason(response.meta.fallback_reason ?? null);
      })
      .catch((error) => {
        if (cancelled) return;
        setAdvisorState('offline');
        setOfflineReason(
          error?.name === 'AbortError'
            ? 'Advisor timed out — showing the deterministic summary only.'
            : 'Advisor offline — showing the deterministic summary only.',
        );
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [options, optionsState, planHash, planVerdict, report, testAdvisory]);

  const handleApply = useCallback(
    (option: RemediationOption) => {
      // A constraint has no validated patch.  Never hand it to the generator as
      // though it were an actionable card: that is the 422 this panel used to
      // trigger.  The server is the authority on whether a patch is valid.
      if (isGenerating || option.available === false || !Object.keys(option.patch ?? {}).length) {
        return;
      }
      if (!option.effect) return;
      onApply(option);
    },
    [isGenerating, onApply],
  );

  const critical = planVerdict === 'NOT-CERTIFIED-FAIL-STAMP';
  const titleId = useId();

  return (
    <section
      data-testid="plan-advisor"
      data-plan-hash={planHash}
      data-advisor-state={advisorState}
      data-options-state={optionsState}
      aria-labelledby={titleId}
      className={`mt-2.5 min-w-0 max-w-full rounded-[12px] border p-3 space-y-2.5 ${
        critical ? 'border-rose-500/30 bg-[var(--card-bg-subtle)]' : 'border-[var(--hairline)] bg-[var(--card-bg-subtle)]'
      }`}
    >
      {/* Deterministic summary: instant, offline, never generated by a model */}
      <div data-testid="advisor-deterministic" className="min-w-0 space-y-1">
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <Icon
            name={critical ? 'alert-triangle' : 'info'}
            size={13}
            className={`shrink-0 ${critical ? 'text-[var(--semantic-red-ink)]' : 'text-[var(--text-3)]'}`}
          />
          <h3
            id={titleId}
            className="text-[11px] font-bold uppercase tracking-[0.06em] text-[var(--text-1)]"
          >
            What failed and what to do
          </h3>
          <span className="inline-flex items-center rounded-full bg-[var(--fill)] px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-[var(--text-3)]">
            deterministic
          </span>
        </div>
        <p className="min-w-0 break-words text-[11.5px] font-medium leading-snug text-[var(--text-1)]">
          {summary.verdictLine}
        </p>
        <p
          data-testid="advisor-counts"
          className="min-w-0 break-words text-[10.5px] font-medium leading-snug text-[var(--text-3)]"
        >
          {summary.countsLine}
        </p>
        {summary.reasons.length > 0 && (
          <ul data-testid="advisor-reasons" className="min-w-0 space-y-0.5 pl-4 list-disc">
            {summary.reasons.map((reason, index) => (
              <li key={`${index}-${reason}`} className="min-w-0 break-words text-[11px] leading-snug text-[var(--text-2)]">
                {reason}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Advisory wording: labelled, optional, cached per plan hash */}
      <div className="min-w-0 border-t border-[var(--hairline)] pt-2 space-y-1">
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <span className="text-[10px] font-bold uppercase tracking-[0.06em] text-[var(--text-3)]">
            Advisory explanation
          </span>
          <span
            data-testid="advisor-badge"
            className="inline-flex items-center rounded-full bg-[var(--semantic-amber)]/15 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-[var(--semantic-amber-ink)]"
          >
            AI · not certified
          </span>
          {advisor?.meta.cached && (
            <span className="text-[9.5px] text-[var(--text-3)]">cached for this plan</span>
          )}
        </div>
        {advisorState === 'loading' && <AdvisorSkeleton />}
        {advisorState === 'ready' && advisor?.narrative && (
          <p
            data-testid="advisor-narrative"
            className="min-w-0 break-words text-[11.5px] leading-relaxed text-[var(--text-2)]"
          >
            {advisor.narrative}
          </p>
        )}
        {advisorState === 'offline' && (
          <p
            data-testid="advisor-offline"
            className="min-w-0 break-words text-[10.5px] leading-snug text-[var(--text-3)]"
          >
            {offlineReason || 'Advisor offline.'} The deterministic summary above is the
            authoritative explanation; no AI text is shown.
          </p>
        )}
      </div>

      {/* The engine's own search, before any wording: every strategy it tried is
          here with its measured outcome.  A skipped strategy says why; a failed
          one keeps its numbers.  The selected strategy is the plan below. */}
      {plan.multi_storey?.strategy_chain && plan.multi_storey.strategy_chain.length > 1 && (
        <div
          data-testid="strategy-chain"
          data-selected={plan.multi_storey.strategy_selected ?? ''}
          className="min-w-0 border-t border-[var(--hairline)] pt-2 space-y-1"
        >
          <div className="flex min-w-0 flex-wrap items-center gap-1.5">
            <span className="text-[10px] font-bold uppercase tracking-[0.06em] text-[var(--text-2)]">
              Engine search
            </span>
            <span
              data-testid="strategy-selected"
              className="rounded-full border border-[var(--accent)]/35 bg-[var(--accent)]/10 px-1.5 py-0.5 font-mono text-[9.5px] font-semibold text-[var(--accent-ink)]"
            >
              selected {plan.multi_storey.strategy_selected ?? 'S0'}
            </span>
            <span className="text-[9.5px] text-[var(--text-3)]">
              every step is an engine re-solve, never a promise
            </span>
          </div>
          <ul className="space-y-0.5">
            {plan.multi_storey.strategy_chain.map((step) => (
              <li
                key={step.id}
                data-testid="strategy-chain-row"
                data-strategy={step.id}
                data-status={step.status}
                className="flex min-w-0 flex-wrap items-baseline gap-x-1.5 gap-y-0.5 text-[10px] leading-snug"
              >
                <span className="shrink-0 font-mono font-semibold text-[var(--text-1)]">{step.id}</span>
                <span className="min-w-0 break-words text-[var(--text-2)]">{step.label}</span>
                <span
                  className={`shrink-0 font-semibold ${
                    step.status === 'certified'
                      ? 'text-[var(--semantic-green-ink)]'
                      : step.status === 'fail'
                        ? 'text-rose-600 dark:text-rose-300'
                        : 'text-[var(--text-3)]'
                  }`}
                >
                  {step.status}
                </span>
                <span className="min-w-0 break-words font-mono text-[9.5px] text-[var(--text-3)]">
                  {step.status === 'fail' || step.status === 'certified'
                    ? `${step.failures ?? 0} failure(s) · ${step.warnings ?? 0} warning(s)${
                        step.plate_area_m2 != null ? ` · ${step.plate_area_m2.toFixed(1)} m²` : ''
                      }`
                    : step.status === 'skipped'
                      ? (step.skip_reason ?? 'not applicable')
                      : (step.error ?? 'strategy could not be solved')}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Remediation cards: engine-measured, deterministic order */}
      <div
        className="min-w-0 border-t border-[var(--hairline)] pt-2 space-y-1.5"
        aria-busy={optionsState === 'loading'}
      >
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <h4 className="text-[10px] font-bold uppercase tracking-[0.06em] text-[var(--text-2)]">
            Next steps
          </h4>
          <span className="text-[9.5px] text-[var(--text-3)]">
            each effect is a live engine re-solve
          </span>
        </div>
        {optionsState === 'loading' && (
          <div
            data-testid="remediation-skeleton"
            className="space-y-1.5"
            aria-busy="true"
            aria-live="polite"
          >
            <span className="sr-only">Measuring remediation options with the engine</span>
            <div className="h-14 rounded-[8px] border border-[var(--hairline)] bg-[var(--fill)]/40 animate-pulse" />
            <div className="h-14 rounded-[8px] border border-[var(--hairline)] bg-[var(--fill)]/40 animate-pulse" />
          </div>
        )}
        {optionsState === 'failed' && (
          <p
            data-testid="remediation-unavailable"
            role="status"
            className="rounded-[8px] border border-[var(--hairline)] px-2.5 py-2 text-[11px] leading-snug text-[var(--text-3)]"
          >
            {optionsNote}
          </p>
        )}
        {optionsState === 'ready' && options && options.length === 0 && (
          <p
            data-testid="remediation-empty"
            className="rounded-[8px] border border-[var(--hairline)] px-2.5 py-2 text-[11px] leading-snug text-[var(--text-3)]"
          >
            No validated input change is available for this plan. The certificate stands as
            drawn.
          </p>
        )}
        {optionsState === 'ready' && options && options.length > 0 && (
          <ul className="space-y-1.5" aria-label="Engine-measured next steps">
          {options.map((option) => {
            const isCurrent = Boolean(option.details?.current);
            const needsConfirmation = Boolean(option.details?.requires_confirmation);
            const isConfirmed = Boolean(confirmed[option.id]);
            const isConstraint = option.available === false;
            const constraintId = `${titleId}-${option.id}-constraint`;
            return (
            <li
              key={option.id}
              data-testid="remediation-card"
              data-option={option.id}
              data-current={isCurrent ? 'true' : 'false'}
              data-available={isConstraint ? 'false' : 'true'}
              data-verdict={option.effect?.verdict ?? 'UNMEASURED'}
              data-failures={option.effect?.failure_count ?? ''}
              data-warnings={option.effect?.warning_count ?? ''}
              data-plate={option.effect?.plate_area_m2 ?? ''}
              className={`min-w-0 rounded-[8px] border px-2.5 py-2 space-y-1 ${
                isConstraint
                  ? 'border-[var(--semantic-amber)]/35 bg-[var(--semantic-amber)]/5'
                  : 'border-[var(--hairline)] bg-[var(--surface)]'
              }`}
            >
              <div className="flex min-w-0 flex-wrap items-start justify-between gap-1.5">
                <div className="min-w-0">
                  <p className="min-w-0 break-words text-[11.5px] font-semibold text-[var(--text-1)]">
                    {option.title}
                  </p>
                  <p className="min-w-0 break-words text-[10.5px] leading-snug text-[var(--text-2)]">
                    {option.description}
                  </p>
                  {isConstraint && (
                    <span
                      data-testid={`constraint-badge-${option.id}`}
                      className="mt-1 inline-flex items-center rounded-full bg-[var(--semantic-amber)]/15 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider text-[var(--semantic-amber-ink)]"
                    >
                      Constraint
                    </span>
                  )}
                  {option.basis && (option.basis.codes?.length || option.basis.rooms?.length) ? (
                    <p
                      data-testid="remediation-basis"
                      className="mt-0.5 min-w-0 break-words font-mono text-[9.5px] leading-snug text-[var(--text-3)]"
                    >
                      Basis: {(option.basis.codes ?? []).join(', ') || 'structured findings'}
                      {(option.basis.room_count ?? option.basis.rooms?.length ?? 0) > 0
                        ? ` · ${option.basis.room_count ?? option.basis.rooms?.length} affected room${(option.basis.room_count ?? option.basis.rooms?.length) === 1 ? '' : 's'}`
                        : ''}
                    </p>
                  ) : null}
                  {advisorState === 'ready' && advisor?.option_notes?.[option.id] && (
                    <p
                      data-testid="advisor-option-note"
                      data-option={option.id}
                      className="mt-0.5 min-w-0 break-words text-[10px] italic leading-snug text-[var(--text-3)]"
                    >
                      {advisor.option_notes[option.id]}
                    </p>
                  )}
                </div>
                {isConstraint ? (
                  <span
                    data-testid={`apply-unavailable-${option.id}`}
                    className="shrink-0 rounded-[6px] border border-[var(--semantic-amber)]/35 bg-[var(--semantic-amber)]/10 px-2 py-1 text-[10.5px] font-semibold text-[var(--semantic-amber-ink)]"
                  >
                    Not available
                  </span>
                ) : (
                  <button
                    type="button"
                    data-testid={`apply-${option.id}`}
                    onClick={() => handleApply(option)}
                    disabled={
                      isGenerating || !option.effect || isCurrent || (needsConfirmation && !isConfirmed)
                    }
                    aria-describedby={
                      option.constraint_reason ? constraintId : undefined
                    }
                    title={
                      isCurrent
                        ? String(option.details?.apply_blocked_reason ?? 'This is already the selected strategy.')
                        : needsConfirmation && !isConfirmed
                          ? 'Confirm the dwelling-count change before re-solving.'
                          : undefined
                    }
                    className="shrink-0 rounded-[6px] border border-[var(--accent)]/40 bg-[var(--accent)]/10 px-2 py-1 text-[10.5px] font-semibold text-[var(--accent-ink)] hover:bg-[var(--accent)]/20 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/40"
                  >
                    {isCurrent
                      ? 'Current strategy'
                      : isGenerating
                        ? 'Re-solving…'
                        : needsConfirmation
                          ? 'Confirm & re-certify'
                          : 'Apply & re-certify'}
                  </button>
                )}
              </div>
              {!isConstraint && needsConfirmation && !isCurrent && (
                <label
                  data-testid={`confirm-${option.id}`}
                  className="flex min-w-0 cursor-pointer items-start gap-1.5 rounded-[6px] border border-[var(--semantic-amber)]/35 bg-[var(--semantic-amber)]/10 px-2 py-1.5 text-[10px] leading-snug text-[var(--semantic-amber-ink)]"
                >
                  <input
                    type="checkbox"
                    data-testid={`confirm-checkbox-${option.id}`}
                    checked={isConfirmed}
                    onChange={(event) =>
                      setConfirmed((prev) => ({ ...prev, [option.id]: event.target.checked }))
                    }
                    className="mt-0.5 shrink-0"
                  />
                  <span className="min-w-0 break-words">
                    I understand this changes the dwelling count; draw the reduced programme.
                  </span>
                </label>
              )}
              {isConstraint && option.constraint_reason && (
                <p
                  id={constraintId}
                  data-testid="remediation-constraint"
                  className="min-w-0 break-words text-[10px] leading-snug text-[var(--semantic-amber-ink)]"
                >
                  {option.constraint_reason}
                </p>
              )}
              <p
                data-testid="remediation-effect"
                className="min-w-0 break-words font-mono text-[10px] leading-snug text-[var(--text-3)]"
              >
                {isConstraint
                  ? 'No dry-run: this input combination is refused by the engine.'
                  : option.error
                    ? `Dry-run failed: ${option.error}`
                    : effectLine(option)}
              </p>
              {option.details?.configuration_note && (
                <p
                  data-testid="remediation-configuration-note"
                  className="min-w-0 break-words text-[10px] leading-snug text-[var(--semantic-amber-ink)]"
                >
                  {String(option.details.configuration_note)}
                </p>
              )}
            </li>
            );
          })}
          </ul>
        )}
        <p className="min-w-0 break-words text-[9.5px] leading-snug text-[var(--text-3)]">
          Applying an option sets only that validated input and re-runs the engine. The new
          certificate decides the verdict — nothing here promises compliance.
        </p>
      </div>
    </section>
  );
};
