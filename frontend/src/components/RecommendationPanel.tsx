import React, { useState } from 'react';
import type { RecommendationItem, SiteFeasibilityAIAnalysis } from '../services/types';
import { Icon } from './Icon';
import { SegmentedControl } from '../design';

interface RecommendationPanelProps {
  summary: string;
  recommendations: string[];
  recommendationItems?: RecommendationItem[];
  aiMetadata: {
    provider_requested?: string;
    provider_used?: string;
    generation_time_ms?: string;
    fallback_reason?: string;
    parameter_reflection?: string;
    feasibility_score?: string;
    narrative_class?: string;
    narrative_redactions?: string;
  };
  parameterReflection?: string;
  structuredNarrative?: SiteFeasibilityAIAnalysis | null;
  summaryOnly?: boolean;
}

export const RecommendationPanel: React.FC<RecommendationPanelProps> = ({
  summary,
  recommendations,
  recommendationItems,
  aiMetadata,
  parameterReflection,
  structuredNarrative,
  summaryOnly = false,
}) => {
  const [copied, setCopied] = useState(false);
  const [filterSeverity, setFilterSeverity] = useState<string>('all');
  const [expandedItems, setExpandedItems] = useState<Record<string | number, boolean>>({});
  const [activeIntelTab, setActiveIntelTab] = useState<'structural' | 'hazards' | 'financial'>('structural');

  const toggleExpand = (id: string | number) => {
    setExpandedItems((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const reflectionText = parameterReflection || aiMetadata?.parameter_reflection || '';

  const providerUsed = String(aiMetadata?.provider_used || '').toLowerCase();
  const narrativeIsDeterministic = providerUsed.includes('mock') || providerUsed.includes('deterministic');
  const narrativeLabel = narrativeIsDeterministic
    ? 'Deterministic engine narrative'
    : 'AI narrative — advisory, non-certified';
  const redactedClaims = String(aiMetadata?.narrative_redactions || '')
    .split(',')
    .map((r) => r.trim())
    .filter(Boolean);

  const normalize = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, '');
  const isNearIdentical = Boolean(
    reflectionText &&
      summary &&
      normalize(reflectionText).slice(0, 60) === normalize(summary).slice(0, 60)
  );

  const handleCopy = () => {
    let fullText = `${reflectionText ? `Parameter Reflection: "${reflectionText}"\n\n` : ''}`;
    if (structuredNarrative) {
      fullText += `Executive Summary:\n${structuredNarrative.executive_summary}\n\n`;
      fullText += `Overall Assessment:\n${structuredNarrative.overall_assessment}\n\n`;
      fullText += `Key Strengths:\n${structuredNarrative.key_strengths.map((s) => `• ${s}`).join('\n')}\n\n`;
      fullText += `Key Concerns:\n${structuredNarrative.key_concerns.map((c) => `• ${c}`).join('\n')}\n\n`;
      fullText += `Engineering Considerations:\n${structuredNarrative.engineering_considerations.map((e) => `• ${e}`).join('\n')}\n\n`;
      fullText += `Required Investigations:\n${structuredNarrative.required_investigations.map((i) => `• ${i}`).join('\n')}\n\n`;
    } else if (!isNearIdentical && summary) {
      fullText += `${summary}\n\n`;
    }
    if (!summaryOnly) {
      if (recommendationItems && recommendationItems.length > 0) {
        fullText +=
          `Traceable Engineering Recommendations:\n` +
          recommendationItems
            .map(
              (r) =>
                `[${r.rule_id || r.id}] (${r.severity}) ${r.category_label || r.title || r.category}: ${r.recommendation_text || r.description}`
            )
            .join('\n\n');
      } else {
        fullText +=
          `Key Engineering Recommendations:\n` +
          recommendations.map((r, i) => `${i + 1}. ${r}`).join('\n');
      }
    }
    navigator.clipboard.writeText(fullText);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const getSeverityStyle = (sev: string) => {
    switch (sev.toLowerCase()) {
      case 'critical':
      case 'high':
        return {
          bg: 'rgba(255, 59, 48, 0.12)',
          text: 'var(--semantic-red-ink)',
        };
      case 'advisory':
      case 'moderate':
        return {
          bg: 'rgba(255, 159, 10, 0.12)',
          text: 'var(--semantic-amber-ink)',
        };
      default:
        return {
          bg: 'rgba(52, 199, 89, 0.12)',
          text: 'var(--semantic-green-ink)',
        };
    }
  };

  const items = recommendationItems || [];
  const filteredItems =
    filterSeverity === 'all'
      ? items
      : items.filter((it) => it.severity.toLowerCase() === filterSeverity.toLowerCase());

  return (
    <div className="bw-card rounded-[16px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)] p-4 sm:p-[20px] space-y-4 w-full min-w-0">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--hairline)] pb-3 min-w-0">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="w-8 h-8 rounded-lg bg-[var(--accent-tint)] border border-[var(--accent)]/30 flex items-center justify-center text-[var(--accent-ink)] shrink-0">
            <Icon name="sparkles" size={16} />
          </div>
          <div>
            <h3 className="text-[15px] font-semibold text-[var(--text-1)] tracking-tight">
              {structuredNarrative ? 'Civil Engineering Dossier & Strategic Synthesis' : 'Engineering Commentary & Advisory'}
            </h3>
            <p className="text-[11.5px] text-[var(--text-3)]">
              {narrativeLabel} • Certified IS 456 & IS 1893:2016 benchmarks
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-medium text-[var(--text-2)] hover:text-[var(--text-1)] bg-[var(--fill)] hover:bg-[var(--fill-hover)] rounded-full transition-colors shrink-0 cursor-pointer"
        >
          <Icon
            name={copied ? 'check' : 'copy'}
            size={13}
            className={copied ? 'text-[var(--semantic-green-ink)]' : 'text-[var(--text-3)]'}
          />
          <span>{copied ? 'Copied' : 'Copy Dossier'}</span>
        </button>
      </div>

      {/* Parameter Reflection Callout */}
      {reflectionText && (
        <div
          data-testid="narrative-block"
          className="p-3.5 bg-[var(--accent-tint)] border border-[var(--accent)]/20 rounded-[12px] space-y-1.5"
        >
          <div className="flex items-center justify-between gap-2 text-[12px] font-medium text-[var(--accent-ink)]">
            <div className="flex items-center gap-1.5">
              <Icon name="sparkles" size={13} className="shrink-0" />
              <span data-testid="narrative-label">{narrativeLabel}</span>
            </div>
            <span className="text-[11px] px-2 py-0.5 rounded-full bg-[var(--accent)]/15 font-mono">
              {aiMetadata?.provider_used || 'engine'}
            </span>
          </div>
          <p className="text-[13px] text-[var(--text-1)] leading-relaxed italic">
            "{reflectionText}"
          </p>
          {redactedClaims.length > 0 && (
            <p data-testid="narrative-redaction-note" className="text-[11px] text-[var(--text-3)] leading-snug pt-0.5">
              Certified values verified: {redactedClaims.join(', ')} reference report tables directly.
            </p>
          )}
        </div>
      )}

      {/* Structured Feasibility Narrative Sections */}
      {structuredNarrative ? (
        <div className="space-y-4">
          {/* Executive Summary & Assessment */}
          <div className="p-4 rounded-[12px] bg-[var(--fill)]/50 border border-[var(--hairline)] space-y-2.5">
            <div className="flex items-center gap-2 text-[12.5px] font-semibold text-[var(--text-1)]">
              <Icon name="file-text" size={14} className="text-[var(--accent-ink)]" />
              <span>Executive Synthesis & Site Viability</span>
            </div>
            <p className="text-[13px] text-[var(--text-2)] leading-relaxed">
              {structuredNarrative.executive_summary}
            </p>
            {structuredNarrative.overall_assessment && (
              <div className="pt-2 border-t border-[var(--hairline)]/60 text-[12.5px] font-medium text-[var(--text-1)] leading-relaxed">
                <span className="text-[var(--accent-ink)] font-semibold">Overall Verdict: </span>
                {structuredNarrative.overall_assessment}
              </div>
            )}
          </div>

          {/* Key Strengths & Concerns Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {/* Strengths */}
            <div className="p-3.5 rounded-[12px] bg-[var(--semantic-green)]/8 border border-[var(--semantic-green)]/25 space-y-2">
              <div className="flex items-center gap-1.5 text-[12px] font-bold text-[var(--semantic-green-ink)] uppercase tracking-wider">
                <Icon name="check-circle" size={14} />
                <span>Primary Site Advantages</span>
              </div>
              <ul className="space-y-1.5 text-[12.5px] text-[var(--text-2)]">
                {structuredNarrative.key_strengths.map((strength, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span className="text-[var(--semantic-green-ink)] font-bold shrink-0">•</span>
                    <span>{strength}</span>
                  </li>
                ))}
              </ul>
            </div>

            {/* Concerns */}
            <div className="p-3.5 rounded-[12px] bg-[var(--semantic-amber)]/8 border border-[var(--semantic-amber)]/25 space-y-2">
              <div className="flex items-center gap-1.5 text-[12px] font-bold text-[var(--semantic-amber-ink)] uppercase tracking-wider">
                <Icon name="alert-triangle" size={14} />
                <span>Key Engineering Challenges</span>
              </div>
              <ul className="space-y-1.5 text-[12.5px] text-[var(--text-2)]">
                {structuredNarrative.key_concerns.map((concern, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span className="text-[var(--semantic-amber-ink)] font-bold shrink-0">•</span>
                    <span>{concern}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* Tabbed Engineering Details */}
          <div className="rounded-[12px] border border-[var(--hairline)] bg-[var(--fill)]/40 p-3.5 space-y-3">
            <div className="flex items-center justify-between border-b border-[var(--hairline)] pb-2 flex-wrap gap-2">
              <span className="text-[12.5px] font-semibold text-[var(--text-1)]">
                Technical Analysis Dimensions
              </span>
              <div className="flex items-center gap-1 bg-[var(--fill)] p-0.5 rounded-lg text-[11.5px]">
                <button
                  type="button"
                  onClick={() => setActiveIntelTab('structural')}
                  className={`px-2.5 py-1 rounded-md font-medium transition-[color,background-color,box-shadow] ${
                    activeIntelTab === 'structural'
                      ? 'bg-[var(--card-bg)] text-[var(--text-1)] shadow-sm'
                      : 'text-[var(--text-3)] hover:text-[var(--text-2)]'
                  }`}
                >
                  Structural & Soil
                </button>
                <button
                  type="button"
                  onClick={() => setActiveIntelTab('hazards')}
                  className={`px-2.5 py-1 rounded-md font-medium transition-[color,background-color,box-shadow] ${
                    activeIntelTab === 'hazards'
                      ? 'bg-[var(--card-bg)] text-[var(--text-1)] shadow-sm'
                      : 'text-[var(--text-3)] hover:text-[var(--text-2)]'
                  }`}
                >
                  Hazards & Bioclimatic
                </button>
                <button
                  type="button"
                  onClick={() => setActiveIntelTab('financial')}
                  className={`px-2.5 py-1 rounded-md font-medium transition-[color,background-color,box-shadow] ${
                    activeIntelTab === 'financial'
                      ? 'bg-[var(--card-bg)] text-[var(--text-1)] shadow-sm'
                      : 'text-[var(--text-3)] hover:text-[var(--text-2)]'
                  }`}
                >
                  CPWD Financials
                </button>
              </div>
            </div>

            {/* Tab Contents */}
            <div className="text-[12.5px] text-[var(--text-2)] space-y-2">
              {activeIntelTab === 'structural' && (
                <ul className="space-y-1.5">
                  {structuredNarrative.engineering_considerations.map((item, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <span className="text-[var(--accent-ink)] font-bold shrink-0">→</span>
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              )}

              {activeIntelTab === 'hazards' && (
                <ul className="space-y-1.5">
                  {structuredNarrative.environmental_and_hazards.map((item, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <span className="text-[var(--accent-ink)] font-bold shrink-0">→</span>
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              )}

              {activeIntelTab === 'financial' && (
                <ul className="space-y-1.5">
                  {structuredNarrative.financial_considerations.map((item, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <span className="text-[var(--accent-ink)] font-bold shrink-0">→</span>
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          {/* Pre-Construction Field Investigations */}
          {structuredNarrative.required_investigations.length > 0 && (
            <div className="p-3.5 rounded-[12px] bg-[var(--card-bg)] border border-[var(--hairline)] space-y-2">
              <div className="flex items-center gap-1.5 text-[12px] font-bold text-[var(--text-1)] uppercase tracking-wider">
                <Icon name="check-circle" size={13} className="text-[var(--accent-ink)]" />
                <span>Mandatory Pre-Construction Investigations</span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1">
                {structuredNarrative.required_investigations.map((inv, idx) => (
                  <div
                    key={idx}
                    className="p-2.5 rounded-lg bg-[var(--fill)]/60 border border-[var(--hairline)]/80 text-[12px] text-[var(--text-2)] flex items-start gap-2"
                  >
                    <span className="w-4 h-4 rounded bg-[var(--accent-tint)] text-[var(--accent-ink)] text-[10px] font-bold flex items-center justify-center shrink-0 mt-0.5">
                      {idx + 1}
                    </span>
                    <span>{inv}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Recommended Next Steps */}
          {structuredNarrative.recommended_next_steps.length > 0 && (
            <div className="p-3.5 rounded-[12px] bg-[var(--accent-tint)]/40 border border-[var(--accent)]/15 space-y-2">
              <div className="flex items-center gap-1.5 text-[12px] font-bold text-[var(--accent-ink)] uppercase tracking-wider">
                <Icon name="arrow-up-right" size={14} />
                <span>Recommended Chronological Next Steps</span>
              </div>
              <div className="space-y-1.5 text-[12.5px] text-[var(--text-1)]">
                {structuredNarrative.recommended_next_steps.map((step, idx) => (
                  <div key={idx} className="flex items-start gap-2">
                    <span className="text-[var(--accent-ink)] font-semibold shrink-0">Step {idx + 1}:</span>
                    <span>{step.replace(/^\d+[\.\)]\s*/, '')}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : (
        /* Fallback Deterministic Summary view when structured narrative is absent */
        !isNearIdentical && summary && (
          <div className="p-3.5 bg-[var(--fill)] rounded-[12px] text-[13px] text-[var(--text-2)] leading-[1.55] space-y-1.5">
            <div className="flex items-center gap-1.5 text-[12px] font-medium text-[var(--text-1)]">
              <Icon name="file-text" size={13} className="text-[var(--text-2)] shrink-0" />
              <span>Deterministic Engineering Summary</span>
            </div>
            <p>{summary}</p>
          </div>
        )
      )}

      {/* Action Items with Natural-Scrolling Filter Control */}
      {!summaryOnly && items.length > 0 && (
        <div className="space-y-3 pt-2 border-t border-[var(--hairline)]">
          {/* Filter row */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 pb-1">
            <div className="flex items-center gap-2">
              <span className="text-[13px] font-semibold text-[var(--text-1)] tracking-tight">
                Traceable Engineering Action Items
              </span>
              <span className="text-[11px] px-2 py-0.5 rounded-full bg-[var(--fill)] text-[var(--text-2)] font-medium tabular-nums">
                {filteredItems.length} of {items.length}
              </span>
            </div>
            <div className="w-full sm:w-auto sm:min-w-[280px]">
              <SegmentedControl
                ariaLabel="Filter recommendations by severity"
                size="sm"
                stretch
                value={filterSeverity}
                onChange={setFilterSeverity}
                options={[
                  { id: 'all', label: 'All' },
                  { id: 'critical', label: 'Critical' },
                  { id: 'advisory', label: 'Advisory' },
                  { id: 'optimal', label: 'Optimal' },
                ]}
              />
            </div>
          </div>

          {/* Grouped Recommendations List */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {filteredItems.map((item, idx) => {
              const style = getSeverityStyle(item.severity);
              const itemId = item.rule_id || item.id || idx;
              const isExpanded = Boolean(expandedItems[itemId]);
              const bodyText = item.recommendation_text || item.description || '';
              const isLongText = bodyText.length > 180;

              return (
                <div
                  key={itemId}
                  className="p-3.5 rounded-[12px] bg-[var(--fill)]/60 border border-[var(--hairline)] space-y-2 min-w-0 flex flex-col justify-between"
                >
                  <div className="space-y-1.5">
                    <div className="flex items-start justify-between gap-2 min-w-0">
                      <span className="text-[13.5px] font-semibold text-[var(--text-1)] leading-snug break-words">
                        {item.category_label || item.title || item.category}
                      </span>
                      <span
                        className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold capitalize shrink-0"
                        style={{ backgroundColor: style.bg, color: style.text }}
                      >
                        <span
                          className="w-1.5 h-1.5 rounded-full"
                          style={{ backgroundColor: style.text }}
                        />
                        <span>{item.severity}</span>
                      </span>
                    </div>

                    <div className="text-[12.5px] text-[var(--text-2)] leading-[1.55]">
                      <p className={isExpanded ? '' : 'line-clamp-3'}>
                        {bodyText}
                      </p>
                      {isLongText && (
                        <button
                          type="button"
                          onClick={() => toggleExpand(itemId)}
                          className="text-[12px] font-medium text-[var(--accent-ink)] hover:underline mt-1 cursor-pointer select-none inline-block"
                        >
                          {isExpanded ? 'Less' : 'More'}
                        </button>
                      )}
                    </div>
                  </div>

                  {(item.trigger_condition || item.source_data_ref) && (
                    <details className="group pt-1 border-t border-[var(--hairline)]">
                      <summary className="cursor-pointer text-[11px] font-medium text-[var(--accent-ink)] hover:underline select-none inline-flex items-center gap-1 list-none">
                        <Icon name="info" size={11} className="shrink-0" />
                        Why this recommendation
                      </summary>
                      <div className="mt-1.5 space-y-1 pl-4 text-[11px] text-[var(--text-3)] leading-snug">
                        {item.trigger_condition && (
                          <p>
                            <span className="font-semibold text-[var(--text-2)]">Trigger:</span>{' '}
                            {item.trigger_condition}
                          </p>
                        )}
                        {item.source_data_ref && (
                          <p>
                            <span className="font-semibold text-[var(--text-2)]">Source data:</span>{' '}
                            {item.source_data_ref}
                          </p>
                        )}
                        {item.rule_id && <p className="font-mono">Rule {item.rule_id}</p>}
                      </div>
                    </details>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Fallback to simple list if no structured items and not summaryOnly */}
      {!summaryOnly && items.length === 0 && recommendations.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-[var(--hairline)]">
          {recommendations.map((rec, idx) => {
            const isExpanded = Boolean(expandedItems[idx]);
            const isLongText = rec.length > 180;
            return (
              <div key={idx} className="p-3.5 rounded-[12px] bg-[var(--fill)]/60 border border-[var(--hairline)] text-[12.5px] text-[var(--text-2)] leading-[1.55]">
                <div className="flex items-start gap-2">
                  <span className="font-semibold text-[var(--text-1)] shrink-0">{idx + 1}.</span>
                  <div className="flex-1 min-w-0">
                    <p className={isExpanded ? '' : 'line-clamp-4'}>{rec}</p>
                    {isLongText && (
                      <button
                        type="button"
                        onClick={() => toggleExpand(idx)}
                        className="text-[12px] font-medium text-[var(--accent-ink)] hover:underline mt-1 cursor-pointer select-none inline-block"
                      >
                        {isExpanded ? 'Less' : 'More'}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Latency and provider metadata */}
      <div className="flex items-center justify-between text-[11px] text-[var(--text-3)] pt-2 border-t border-[var(--hairline)]">
        <span>Execution Engine: {aiMetadata?.provider_used || 'deterministic_core'}</span>
        <span>
          Response Time:{' '}
          {aiMetadata?.generation_time_ms
            ? `${parseFloat(aiMetadata.generation_time_ms).toFixed(0)}ms`
            : 'Instantaneous'}
        </span>
      </div>
    </div>
  );
};
