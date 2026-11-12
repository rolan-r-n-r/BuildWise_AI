import React from 'react';
import type { RiskItem } from '../services/types';
import { Icon } from './Icon';

export interface RiskMatrixProps {
  risks: RiskItem[];
  showHeader?: boolean;
}

export const RiskMatrix: React.FC<RiskMatrixProps> = ({ risks, showHeader = true }) => {
  // Pill TEXT uses the -ink hues: the bright semantic tokens are fill/graphic
  // colours and measure 1.9-3.0:1 as small text on their own 12% tints.
  const getSeverityStyle = (severity: string) => {
    switch (severity.toLowerCase()) {
      case 'high':
      case 'critical':
        return {
          bg: 'rgba(255, 59, 48, 0.12)',
          text: 'var(--semantic-red-ink)',
          dashed: false,
        };
      case 'medium':
      case 'moderate':
        return {
          bg: 'rgba(255, 159, 10, 0.12)',
          text: 'var(--semantic-amber-ink)',
          dashed: false,
        };
      case 'unknown':
      case 'not assessed':
      case 'not-assessed':
        // Neutral gray, dashed: an unmeasured risk must never read as green "clear"
        return {
          bg: 'var(--fill)',
          text: 'var(--text-2)',
          dashed: true,
        };
      default:
        return {
          bg: 'rgba(52, 199, 89, 0.12)',
          text: 'var(--semantic-green-ink)',
          dashed: false,
        };
    }
  };

  return (
    <div className="rounded-[14px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)] p-4 space-y-3.5 w-full min-w-0">
      {/* Header */}
      {showHeader && (
        <div className="flex items-center justify-between border-b border-[var(--hairline)] pb-2 min-w-0">
          <div className="flex items-center gap-2 min-w-0">
            <Icon name="shield-alert" size={15} className="text-[var(--text-2)] shrink-0" />
            <h3 className="text-[14px] font-semibold text-[var(--text-1)] tracking-tight">
              Site Constraints & Mitigation Register
            </h3>
          </div>
          <span className="text-[12px] font-normal text-[var(--text-3)] shrink-0">
            {risks.length} identified
          </span>
        </div>
      )}

      {/* Grouped list with hairline dividers */}
      <div className="divide-y divide-[var(--hairline)]">
        {risks.map((risk, idx) => {
          const style = getSeverityStyle(risk.severity);

          return (
            <div key={idx} className="py-3 space-y-1.5 min-w-0 first:pt-0 last:pb-0">
              <div className="flex items-center justify-between gap-2 min-w-0">
                <span className="text-[13px] font-semibold text-[var(--text-1)] leading-snug break-words">
                  {risk.title}
                </span>
                <span
                  className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold capitalize shrink-0"
                  style={{
                    backgroundColor: style.bg,
                    color: style.text,
                    ...(style.dashed ? { border: '1px dashed var(--hairline)' } : {}),
                  }}
                >
                  <span
                    className="w-1.5 h-1.5 rounded-full"
                    style={{ backgroundColor: style.text }}
                  />
                  <span>{risk.severity} risk</span>
                </span>
              </div>

              <p className="text-[12px] text-[var(--text-2)] leading-normal">
                {risk.description}
              </p>

              <div className="text-[12px] text-[var(--text-2)] leading-normal pt-0.5">
                <span className="font-semibold text-[var(--text-1)]">Mitigation: </span>
                <span>{risk.mitigation_strategy}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
