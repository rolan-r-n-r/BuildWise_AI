import React, { useState, useEffect, useMemo } from 'react';
import type {
  FloorPlanResponse,
  BlueprintAIAnalysisResponse,
  AIWarningDetail,
} from '../../services/types';
import { fetchBlueprintAIAnalysis } from '../../services/api';
import { Icon } from '../Icon';

interface BlueprintAIInsightsPanelProps {
  floorPlan: FloorPlanResponse;
  warnings: readonly (string | null | undefined)[];
  planVerdict?: string | null;
  buildingTypology?: string | null;
  builtUpAreaSqft?: number | null;
  floors?: number | null;
  rawWarningsView?: React.ReactNode;
}

export const BlueprintAIInsightsPanel: React.FC<BlueprintAIInsightsPanelProps> = ({
  floorPlan: _floorPlan,
  warnings,
  planVerdict,
  buildingTypology,
  builtUpAreaSqft,
  floors,
  rawWarningsView,
}) => {
  const [analysis, setAnalysis] = useState<BlueprintAIAnalysisResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<string>('overview');
  const [viewMode, setViewMode] = useState<'ai_insights' | 'raw_solver'>('ai_insights');
  const [expandedWarningId, setExpandedWarningId] = useState<string | null>(null);

  const cleanWarnings = useMemo(
    () => warnings.filter((w): w is string => Boolean(w && w.trim())),
    [warnings]
  );

  useEffect(() => {
    let isCancelled = false;

    async function loadAnalysis() {
      if (cleanWarnings.length === 0) {
        setAnalysis(null);
        return;
      }

      setLoading(true);
      setError(null);

      try {
        const res = await fetchBlueprintAIAnalysis({
          warnings: cleanWarnings,
          plan_verdict: planVerdict,
          building_typology: buildingTypology || 'residential_single',
          built_up_area_sqft: builtUpAreaSqft || undefined,
          floors: floors || 1,
        });

        if (!isCancelled) {
          setAnalysis(res);
        }
      } catch (err: any) {
        if (!isCancelled) {
          logger_error: console.error('Blueprint AI analysis fetch failed:', err);
          setError(err?.message || 'Failed to load AI blueprint advisory.');
        }
      } finally {
        if (!isCancelled) {
          setLoading(false);
        }
      }
    }

    loadAnalysis();

    return () => {
      isCancelled = true;
    };
  }, [cleanWarnings, planVerdict, buildingTypology, builtUpAreaSqft, floors]);

  const categories = useMemo(() => {
    if (!analysis?.categorized_warnings) return [];
    return Object.keys(analysis.categorized_warnings).filter(
      (cat) => (analysis.categorized_warnings[cat] || []).length > 0
    );
  }, [analysis]);

  const getPriorityStyle = (priority: string) => {
    switch (priority.toLowerCase()) {
      case 'critical':
        return 'bg-[var(--semantic-red)]/15 text-[var(--semantic-red-ink)] border-[var(--semantic-red)]/30';
      case 'high':
        return 'bg-[var(--semantic-amber)]/15 text-[var(--semantic-amber-ink)] border-[var(--semantic-amber)]/30';
      case 'medium':
        return 'bg-blue-500/15 text-blue-800 dark:text-blue-300 border-blue-500/30';
      case 'low':
        return 'bg-purple-500/15 text-purple-800 dark:text-purple-300 border-purple-500/30';
      default:
        return 'bg-[var(--semantic-green)]/15 text-[var(--semantic-green-ink)] border-[var(--semantic-green)]/30';
    }
  };

  if (cleanWarnings.length === 0) {
    return null;
  }

  return (
    <div className="bw-card rounded-[16px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)] p-4 sm:p-5 space-y-4 w-full min-w-0">
      {/* Top Header & Switcher */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-[var(--hairline)] pb-3">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-[var(--accent-tint)] border border-[var(--accent)]/30 flex items-center justify-center text-[var(--accent-ink)] shrink-0">
            <Icon name="sparkles" size={16} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-[14.5px] font-semibold text-[var(--text-1)] tracking-tight">
                AI Blueprint Advisory & Plan Diagnostics
              </h3>
              <span className="text-[11px] px-2 py-0.5 rounded-full font-mono bg-[var(--fill)] text-[var(--text-2)] border border-[var(--hairline)]">
                {cleanWarnings.length} condition{cleanWarnings.length === 1 ? '' : 's'}
              </span>
            </div>
            <p className="text-[11.5px] text-[var(--text-3)]">
              Architectural code diagnostics, root-cause grouping, and prioritized corrective actions
            </p>
          </div>
        </div>

        {/* View Switcher: AI Insights vs Raw Solver */}
        <div className="flex items-center gap-1 bg-[var(--fill)] p-0.5 rounded-lg text-[12px] self-start sm:self-auto">
          <button
            type="button"
            onClick={() => setViewMode('ai_insights')}
            className={`px-3 py-1 rounded-md font-medium transition-all cursor-pointer ${
              viewMode === 'ai_insights'
                ? 'bg-[var(--card-bg)] text-[var(--text-1)] shadow-sm'
                : 'text-[var(--text-3)] hover:text-[var(--text-2)]'
            }`}
          >
            AI Architectural Insights
          </button>
          <button
            type="button"
            onClick={() => setViewMode('raw_solver')}
            className={`px-3 py-1 rounded-md font-medium transition-all cursor-pointer ${
              viewMode === 'raw_solver'
                ? 'bg-[var(--card-bg)] text-[var(--text-1)] shadow-sm'
                : 'text-[var(--text-3)] hover:text-[var(--text-2)]'
            }`}
          >
            Raw Solver Engine Log
          </button>
        </div>
      </div>

      {/* Raw Solver View */}
      {viewMode === 'raw_solver' && (
        <div className="space-y-3 pt-1">
          <div className="p-3 bg-[var(--fill)]/50 rounded-lg text-[12px] text-[var(--text-2)] flex items-center justify-between">
            <span>Direct mathematical solver verification log & code traces</span>
            <button
              type="button"
              onClick={() => setViewMode('ai_insights')}
              className="text-[var(--accent-ink)] font-semibold hover:underline cursor-pointer"
            >
              ← Back to AI Insights
            </button>
          </div>
          {rawWarningsView}
        </div>
      )}

      {/* AI Insights View */}
      {viewMode === 'ai_insights' && (
        <>
          {loading && (
            <div className="py-8 flex flex-col items-center justify-center space-y-2 text-[var(--text-3)]">
              <Icon name="loader" size={20} className="animate-spin text-[var(--accent-ink)]" />
              <p className="text-[12.5px]">Synthesizing structural and architectural code analysis...</p>
            </div>
          )}

          {error && (
            <div className="p-3.5 rounded-xl bg-[var(--semantic-red)]/10 border border-[var(--semantic-red)]/25 text-[12.5px] text-[var(--semantic-red-ink)] flex items-center justify-between">
              <span>{error}</span>
              <button
                type="button"
                onClick={() => setViewMode('raw_solver')}
                className="underline font-semibold ml-2"
              >
                View raw solver warnings
              </button>
            </div>
          )}

          {analysis && !loading && (
            <div className="space-y-4">
              {/* Overall Blueprint Assessment Card */}
              <div
                className={`p-4 rounded-[14px] border ${
                  analysis.blueprint_assessment.ready_for_review
                    ? 'bg-[var(--semantic-green)]/8 border-[var(--semantic-green)]/25'
                    : 'bg-[var(--semantic-amber)]/8 border-[var(--semantic-amber)]/25'
                } space-y-2.5`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span
                      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11.5px] font-bold uppercase tracking-wider ${
                        analysis.blueprint_assessment.ready_for_review
                          ? 'bg-[var(--semantic-green)]/20 text-[var(--semantic-green-ink)]'
                          : 'bg-[var(--semantic-amber)]/20 text-[var(--semantic-amber-ink)]'
                      }`}
                    >
                      <Icon
                        name={analysis.blueprint_assessment.ready_for_review ? 'check-circle' : 'alert-triangle'}
                        size={13}
                      />
                      <span>
                        {analysis.blueprint_assessment.ready_for_review
                          ? 'Ready for Detailed Design Review'
                          : 'Requires Action Before Review'}
                      </span>
                    </span>

                    {analysis.blueprint_assessment.professional_review_required && (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10.5px] font-medium bg-[var(--fill)] text-[var(--text-2)] border border-[var(--hairline)]">
                        <Icon name="shield" size={11} />
                        Professional Sign-off Required
                      </span>
                    )}
                  </div>

                  <span className="text-[11px] font-mono text-[var(--text-3)]">
                    Engine: {analysis.meta?.provider_used || 'deterministic_core'}
                  </span>
                </div>

                <p className="text-[13px] text-[var(--text-1)] leading-relaxed">
                  {analysis.blueprint_assessment.overall_status_summary}
                </p>

                {/* Recurring Themes */}
                {analysis.blueprint_assessment.recurring_themes?.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1.5 pt-1 text-[11.5px]">
                    <span className="text-[var(--text-3)] font-medium">Recurring Themes:</span>
                    {analysis.blueprint_assessment.recurring_themes.map((theme, i) => (
                      <span
                        key={i}
                        className="px-2 py-0.5 rounded-md bg-[var(--card-bg)] text-[var(--text-2)] border border-[var(--hairline)] font-medium"
                      >
                        {theme}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Sub-Navigation Tabs */}
              <div className="flex items-center gap-1.5 border-b border-[var(--hairline)] pb-2 overflow-x-auto text-[12px] no-scrollbar">
                <button
                  type="button"
                  onClick={() => setActiveTab('overview')}
                  className={`px-3 py-1.5 rounded-lg font-medium whitespace-nowrap transition-colors cursor-pointer ${
                    activeTab === 'overview'
                      ? 'bg-[var(--fill)] text-[var(--text-1)] font-semibold'
                      : 'text-[var(--text-3)] hover:text-[var(--text-2)]'
                  }`}
                >
                  Prioritized Action Plan ({analysis.prioritized_actions.length})
                </button>

                <button
                  type="button"
                  onClick={() => setActiveTab('grouped')}
                  className={`px-3 py-1.5 rounded-lg font-medium whitespace-nowrap transition-colors cursor-pointer ${
                    activeTab === 'grouped'
                      ? 'bg-[var(--fill)] text-[var(--text-1)] font-semibold'
                      : 'text-[var(--text-3)] hover:text-[var(--text-2)]'
                  }`}
                >
                  Root Cause Groups ({analysis.grouped_issues.length})
                </button>

                {categories.map((cat) => {
                  const count = (analysis.categorized_warnings[cat] || []).length;
                  return (
                    <button
                      key={cat}
                      type="button"
                      onClick={() => setActiveTab(cat)}
                      className={`px-3 py-1.5 rounded-lg font-medium whitespace-nowrap transition-colors cursor-pointer flex items-center gap-1.5 ${
                        activeTab === cat
                          ? 'bg-[var(--fill)] text-[var(--text-1)] font-semibold'
                          : 'text-[var(--text-3)] hover:text-[var(--text-2)]'
                      }`}
                    >
                      <span>{cat}</span>
                      <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-[var(--card-bg)] text-[var(--text-2)] font-mono">
                        {count}
                      </span>
                    </button>
                  );
                })}
              </div>

              {/* TAB 1: Prioritized Actions */}
              {activeTab === 'overview' && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between text-[12.5px] font-semibold text-[var(--text-1)]">
                    <span>Ordered Remediation Roadmap</span>
                    <span className="text-[11px] text-[var(--text-3)] font-normal">
                      Ranked by structural urgency and compliance impact
                    </span>
                  </div>

                  <div className="space-y-2.5">
                    {analysis.prioritized_actions.map((act, idx) => (
                      <div
                        key={idx}
                        className="p-3.5 rounded-[12px] bg-[var(--fill)]/50 border border-[var(--hairline)] flex flex-col sm:flex-row sm:items-start justify-between gap-3"
                      >
                        <div className="flex items-start gap-3">
                          <span className="w-6 h-6 rounded-full bg-[var(--card-bg)] border border-[var(--hairline)] text-[11px] font-bold text-[var(--text-1)] flex items-center justify-center shrink-0 mt-0.5">
                            {idx + 1}
                          </span>
                          <div className="space-y-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-[13px] font-semibold text-[var(--text-1)]">
                                {act.action_title}
                              </span>
                              <span
                                className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border ${getPriorityStyle(
                                  act.priority
                                )}`}
                              >
                                {act.priority}
                              </span>
                              {act.target_elements?.map((el, ei) => (
                                <span
                                  key={ei}
                                  className="px-2 py-0.5 rounded-md text-[10.5px] font-medium bg-[var(--card-bg)] text-[var(--text-2)] border border-[var(--hairline)]"
                                >
                                  {el}
                                </span>
                              ))}
                            </div>
                            <p className="text-[12.5px] text-[var(--text-2)] leading-relaxed">
                              {act.description}
                            </p>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* TAB 2: Grouped Root Causes */}
              {activeTab === 'grouped' && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between text-[12.5px] font-semibold text-[var(--text-1)]">
                    <span>Interconnected Architectural Root Causes</span>
                    <span className="text-[11px] text-[var(--text-3)] font-normal">
                      Addressing shared causes resolves multiple warnings simultaneously
                    </span>
                  </div>

                  {analysis.grouped_issues.length === 0 ? (
                    <div className="p-4 rounded-xl bg-[var(--fill)]/40 text-[12.5px] text-[var(--text-3)] text-center">
                      No multi-warning clustering detected. Warnings are isolated conditions.
                    </div>
                  ) : (
                    <div className="space-y-3">
                      {analysis.grouped_issues.map((group, idx) => (
                        <div
                          key={idx}
                          className="p-4 rounded-[12px] bg-[var(--card-bg)] border border-[var(--hairline)] space-y-3 shadow-sm"
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="space-y-1">
                              <span className="text-[13.5px] font-bold text-[var(--text-1)]">
                                {group.group_name}
                              </span>
                              <p className="text-[12.5px] text-[var(--text-2)] leading-relaxed">
                                <span className="font-semibold text-[var(--text-1)]">Root Cause: </span>
                                {group.underlying_cause}
                              </p>
                            </div>
                            <span className="px-2 py-0.5 rounded-full text-[11px] font-mono bg-[var(--fill)] text-[var(--text-2)] shrink-0">
                              {group.related_warnings.length} issues linked
                            </span>
                          </div>

                          {/* Combined Solution */}
                          <div className="p-3 rounded-lg bg-[var(--accent-tint)]/40 border border-[var(--accent)]/20 text-[12px] text-[var(--text-1)] space-y-1">
                            <span className="font-bold text-[var(--accent-ink)] flex items-center gap-1">
                              <Icon name="check" size={13} />
                              Recommended Integrated Solution:
                            </span>
                            <p className="leading-relaxed">{group.combined_solution}</p>
                          </div>

                          {/* Linked warnings */}
                          <div className="space-y-1">
                            <span className="text-[11px] font-semibold text-[var(--text-3)] uppercase tracking-wider">
                              Covered Warning Strings:
                            </span>
                            <ul className="space-y-1 text-[11.5px] text-[var(--text-2)] font-mono pl-3 list-disc">
                              {group.related_warnings.map((rw, rwi) => (
                                <li key={rwi} className="break-words">
                                  {rw}
                                </li>
                              ))}
                            </ul>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* TAB 3+: Individual Categories */}
              {categories.includes(activeTab) && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between text-[12.5px] font-semibold text-[var(--text-1)]">
                    <span>{activeTab} Warnings & Remediation Detail</span>
                    <span className="text-[11px] text-[var(--text-3)] font-mono">
                      {(analysis.categorized_warnings[activeTab] || []).length} items
                    </span>
                  </div>

                  <div className="space-y-3">
                    {(analysis.categorized_warnings[activeTab] || []).map((detail: AIWarningDetail, idx: number) => {
                      const isExpanded = expandedWarningId === `${activeTab}-${idx}`;
                      return (
                        <div
                          key={idx}
                          className="p-4 rounded-[12px] bg-[var(--card-bg)] border border-[var(--hairline)] space-y-3"
                        >
                          {/* Heading Row */}
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="flex flex-wrap items-center gap-2">
                              {detail.warning_id && (
                                <span className="px-2 py-0.5 rounded-md font-mono text-[11px] font-bold bg-[var(--fill)] text-[var(--text-1)] border border-[var(--hairline)]">
                                  {detail.warning_id}
                                </span>
                              )}
                              <span
                                className={`px-2 py-0.5 rounded-full text-[10.5px] font-bold uppercase tracking-wider border ${getPriorityStyle(
                                  detail.ai_priority
                                )}`}
                              >
                                {detail.ai_priority} priority
                              </span>
                              {detail.affected_element && (
                                <span className="px-2 py-0.5 rounded-md text-[11px] font-medium bg-[var(--accent-tint)] text-[var(--accent-ink)]">
                                  {detail.affected_element}
                                </span>
                              )}
                              {detail.requires_professional_review && (
                                <span className="px-2 py-0.5 rounded-md text-[10.5px] font-medium bg-[var(--semantic-red)]/10 text-[var(--semantic-red-ink)]">
                                  Engineer Review Mandated
                                </span>
                              )}
                            </div>

                            <button
                              type="button"
                              onClick={() =>
                                setExpandedWarningId(isExpanded ? null : `${activeTab}-${idx}`)
                              }
                              className="text-[11.5px] font-medium text-[var(--accent-ink)] hover:underline cursor-pointer"
                            >
                              {isExpanded ? 'Less info' : 'Full diagnostic'}
                            </button>
                          </div>

                          {/* Plain-English Explanation */}
                          <div className="space-y-1">
                            <p className="text-[13px] font-medium text-[var(--text-1)] leading-snug">
                              {detail.explanation}
                            </p>
                            <p className="text-[11px] font-mono text-[var(--text-3)] break-words">
                              Original: {detail.original_warning}
                            </p>
                          </div>

                          {/* Actionable Suggestion */}
                          <div className="p-3 rounded-lg bg-[var(--fill)]/70 border border-[var(--hairline)] text-[12px] space-y-1">
                            <span className="font-semibold text-[var(--text-1)] flex items-center gap-1.5">
                              <Icon name="check-circle" size={13} className="text-[var(--semantic-green-ink)]" />
                              Suggested Corrective Action:
                            </span>
                            <p className="text-[var(--text-2)] leading-relaxed">
                              {detail.suggested_correction}
                            </p>
                          </div>

                          {/* Expanded Impact Analysis */}
                          {isExpanded && (
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 pt-2 border-t border-[var(--hairline)]/80 text-[11.5px]">
                              <div className="p-2.5 rounded-lg bg-[var(--fill)]/40 space-y-1">
                                <span className="font-bold text-[var(--text-1)] uppercase tracking-wide text-[10px]">
                                  Why It Matters:
                                </span>
                                <p className="text-[var(--text-2)] leading-relaxed">
                                  {detail.why_it_matters}
                                </p>
                              </div>

                              <div className="p-2.5 rounded-lg bg-[var(--semantic-amber)]/8 space-y-1">
                                <span className="font-bold text-[var(--semantic-amber-ink)] uppercase tracking-wide text-[10px]">
                                  Potential Risk If Unresolved:
                                </span>
                                <p className="text-[var(--text-2)] leading-relaxed">
                                  {detail.potential_risk}
                                </p>
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
};
