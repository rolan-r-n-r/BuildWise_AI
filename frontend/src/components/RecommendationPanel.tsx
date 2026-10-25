import React, { useState } from 'react';
import type { RecommendationItem } from '../services/types';
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
  summaryOnly?: boolean;
}

export const RecommendationPanel: React.FC<RecommendationPanelProps> = ({
  summary,
  recommendations,
  recommendationItems,
  aiMetadata,
  parameterReflection,
  summaryOnly = false,
}) => {
  const [copied, setCopied] = useState(false);
  const [filterSeverity, setFilterSeverity] = useState<string>('all');
  const [expandedItems, setExpandedItems] = useState<Record<string | number, boolean>>({});

  const toggleExpand = (id: string | number) => {
    setExpandedItems((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const reflectionText = parameterReflection || aiMetadata?.parameter_reflection || '';

  // The narrative is advisory text, never a source of report values.
  // Every figure it asserted was stripped server-side; say so where it shows.
  const providerUsed = String(aiMetadata?.provider_used || '').toLowerCase();
  const narrativeIsDeterministic = providerUsed.includes('mock') || providerUsed.includes('deterministic');
  const narrativeLabel = narrativeIsDeterministic
    ? 'Deterministic engine narrative'
    : 'AI narrative — advisory, non-certified';
  const redactedClaims = String(aiMetadata?.narrative_redactions || '')
    .split(',')
    .map((r) => r.trim())
    .filter(Boolean);

  // Deduplicate commentary: compare first 60 normalized chars
  const normalize = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, '');
  const isNearIdentical = Boolean(
    reflectionText &&
      summary &&
      normalize(reflectionText).slice(0, 60) === normalize(summary).slice(0, 60)
  );

  const handleCopy = () => {
    let fullText = `${reflectionText ? `AI Parameter Reflection: "${reflectionText}"\n\n` : ''}`;
    if (!isNearIdentical && summary) {
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

  // Pill TEXT uses the -ink hues: the bright semantic tokens are fill/graphic
  // colours and measure below AA as small text on their own tints (red 3.01:1,
  // amber 1.88:1, green 2.01:1 on 12% tints).
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
    <div className="bw-card rounded-[14px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)] p-4 sm:p-[18px] space-y-3.5 w-full min-w-0">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--hairline)] pb-2 min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <Icon name="file-text" size={15} className="text-[var(--text-2)] shrink-0" />
          <h3 className="text-[14px] font-semibold text-[var(--text-1)] tracking-tight">
            {summaryOnly ? 'Engineering Summary & Advisory' : 'Engineering Commentary & Action Items'}
          </h3>
        </div>
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1.5 px-2.5 py-1 text-[12px] font-medium text-[var(--text-2)] hover:text-[var(--text-1)] bg-[var(--fill)] hover:bg-[var(--fill-hover)] rounded-full transition-colors shrink-0 cursor-pointer"
        >
          <Icon
            name={copied ? 'check' : 'copy'}
            size={12}
            className={copied ? 'text-[var(--semantic-green-ink)]' : 'text-[var(--text-3)]'}
          />
          <span>{copied ? 'Copied' : 'Copy'}</span>
        </button>
      </div>

      {/* Parameter Reflection: styled italic quote with sparkles icon and accent-tinted surface */}
      {reflectionText && (
        <div
          data-testid="narrative-block"
          className="p-3.5 bg-[var(--accent-tint)] border border-[var(--accent)]/20 rounded-[12px] space-y-1.5"
        >
          <div className="flex items-center gap-1.5 text-[12px] font-medium text-[var(--accent-ink)]">
            <Icon name="sparkles" size={13} className="text-[var(--accent-ink)]" />
            <span data-testid="narrative-label">{narrativeLabel}</span>
          </div>
          <p className="text-[13px] text-[var(--text-1)] leading-relaxed italic">
            "{reflectionText}"
          </p>
          {redactedClaims.length > 0 && (
            <p data-testid="narrative-redaction-note" className="text-[11px] text-[var(--text-2)] leading-snug">
              {redactedClaims.join(', ')} claim{redactedClaims.length === 1 ? '' : 's'} removed — use the
              certified values in this report.
            </p>
          )}
        </div>
      )}

      {/* Engineering Narrative Summary (only rendered if distinct from reflectionText) */}
      {!isNearIdentical && summary && (
        <div className="p-3.5 bg-[var(--fill)] rounded-[12px] text-[13px] text-[var(--text-2)] leading-[1.55]">
          {summary}
        </div>
      )}

      {/* Compact Action Items with Sticky Filter Control */}
      {!summaryOnly && items.length > 0 && (
        <div className="space-y-2 pt-1">
          {/* Sticky filter segmented control at card top */}
          <div className="sticky top-0 bg-[var(--card-bg-subtle)] z-10 pt-1 pb-1.5">
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

          {/* Grouped Recommendations List: hairline separators, no per-entry cards, scrollable */}
          <div className="divide-y divide-[var(--hairline)] border-y border-[var(--hairline)] max-h-[340px] overflow-y-auto scrollbar-apple pr-1">
            {filteredItems.map((item, idx) => {
              const style = getSeverityStyle(item.severity);
              const itemId = item.rule_id || item.id || idx;
              const isExpanded = Boolean(expandedItems[itemId]);
              const bodyText = item.recommendation_text || item.description || '';
              const isLongText = bodyText.length > 180;

              return (
                <div key={itemId} className="py-3 space-y-1.5 min-w-0 first:pt-2 last:pb-1">
                  {/* Title Row: 14px/600 --text-1 + tinted severity pill right */}
                  <div className="flex items-center justify-between gap-2 min-w-0">
                    <span className="text-[14px] font-semibold text-[var(--text-1)] leading-snug break-words">
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

                  {/* Body: 13px --text-2, line-height 1.55, clamped to 4 lines with a 'More' button */}
                  <div className="text-[13px] text-[var(--text-2)] leading-[1.55]">
                    <p className={isExpanded ? '' : 'line-clamp-4'}>
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

                  {/* Traceability: why this recommendation fired + which payload field it reads. */}
                  {(item.trigger_condition || item.source_data_ref) && (
                    <details className="group">
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
        <div className="divide-y divide-[var(--hairline)] border-y border-[var(--hairline)] max-h-[340px] overflow-y-auto scrollbar-apple pr-1">
          {recommendations.map((rec, idx) => {
            const isExpanded = Boolean(expandedItems[idx]);
            const isLongText = rec.length > 180;
            return (
              <div key={idx} className="py-3 text-[13px] text-[var(--text-2)] leading-[1.55]">
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
      <div className="flex items-center justify-between text-[11px] text-[var(--text-3)] pt-1">
        <span>Engine: {aiMetadata?.provider_used || 'deterministic'}</span>
        <span>
          Latency:{' '}
          {aiMetadata?.generation_time_ms
            ? `${parseFloat(aiMetadata.generation_time_ms).toFixed(0)}ms`
            : 'Instant'}
        </span>
      </div>
    </div>
  );
};
