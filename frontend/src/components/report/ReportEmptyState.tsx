import React from 'react';
import { Icon, type IconName } from '../Icon';

interface ReportEmptyStateProps {
  icon?: IconName;
  title: string;
  /** One-line explanation of why the area is empty and what to do next. */
  message: string;
  /** Optional recovery affordance (e.g. re-run the degraded service). */
  action?: { label: string; onClick: () => void };
  className?: string;
}

/**
 * Designed empty/degraded state for a report card — icon + one-line
 * explanation + optional action. Replaces a blank area whenever a service
 * degraded or a payload section is absent, so no tab ever shows dead space.
 */
export const ReportEmptyState: React.FC<ReportEmptyStateProps> = ({
  icon = 'info',
  title,
  message,
  action,
  className = '',
}) => (
  <div
    role="status"
    className={`rounded-[16px] border border-dashed border-[var(--hairline)] bg-[var(--card-bg-subtle)] p-5 text-center space-y-2.5 w-full min-w-0 ${className}`}
  >
    <div className="w-9 h-9 mx-auto rounded-full bg-[var(--fill)] text-[var(--text-2)] flex items-center justify-center">
      <Icon name={icon} size={18} />
    </div>
    <div className="space-y-1 max-w-sm mx-auto">
      <h4 className="text-[13px] font-semibold text-[var(--text-1)]">{title}</h4>
      <p className="text-[12px] text-[var(--text-2)] leading-relaxed">{message}</p>
    </div>
    {action && (
      <button
        type="button"
        onClick={action.onClick}
        className="inline-flex items-center gap-1.5 px-3.5 h-8 bg-[var(--fill)] hover:bg-[var(--fill-hover)] text-[var(--text-1)] rounded-full text-[12px] font-medium transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/40"
      >
        <Icon name="refresh" size={12} />
        <span>{action.label}</span>
      </button>
    )}
  </div>
);
