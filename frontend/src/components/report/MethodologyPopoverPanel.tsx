/**
 * MethodologyPopoverPanel — the panel BODY of the methodology popover.
 * ===================================================================
 * Split out of `MethodologyPopover` for one measured reason: the popover is used
 * by the AUTHORING FORM, which is on the application shell's first paint, and it
 * statically imported the report's provenance vocabulary (`StatusBadge` + the
 * status taxonomy). That single edge pulled report-surface code into the /app
 * initial graph — exactly the +3 KB gz the bundle pin reports.
 *
 * A popover panel only exists AFTER a reader opens a trigger, so the vocabulary
 * is fetched with it: `MethodologyPopover` lazy-imports this module and keeps
 * everything that must be synchronous — the trigger, the portal, the positioning
 * measurement, the focus return and the outside-click dismissal. No behaviour is
 * deferred except the panel's own contents, which cannot be on screen before the
 * reader asks for them.
 *
 * A type-only import carries the payload shape back, which esbuild erases, so
 * there is no runtime cycle between the two modules.
 */
import React from 'react';
import { Icon } from '../Icon';
import { StatusBadge } from './StatusBadge';
import { assumedFootnote } from './statusTaxonomy';
import type { MethodologyPayload, MethodologySection } from './MethodologyPopover';

export interface MethodologyPopoverPanelProps {
  payload?: MethodologyPayload;
  title?: string;
  sections?: MethodologySection[];
  /** The parent's close handler: closes the panel and returns focus. */
  onClose: () => void;
  /**
   * Called once the body is mounted, so the parent re-measures the panel with
   * its real height and can flip it above the trigger when the viewport bottom
   * would clip it. Without this the first measurement would be the skeleton's.
   */
  onMeasured?: () => void;
}

/** Render the real server fetch timestamp; disclose the absence honestly. */
export function formatFetchedAt(iso: string | null | undefined): string {
  if (!iso) return 'Not fetched this session (derived value)';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export const MethodologyPopoverPanel: React.FC<MethodologyPopoverPanelProps> = ({
  payload,
  title,
  sections,
  onClose,
  onMeasured,
}) => {
  const measured = React.useRef(false);
  React.useLayoutEffect(() => {
    if (measured.current) return;
    measured.current = true;
    onMeasured?.();
  }, [onMeasured]);

  return (
    <>
      <div className="flex items-center justify-between gap-2">
        {payload ? (
          <StatusBadge status={payload.status} />
        ) : (
          <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--text-3)]">
            {title ?? 'What this affects'}
          </span>
        )}
        <button
          type="button"
          onClick={onClose}
          aria-label="Close methodology"
          className="w-5 h-5 rounded-full bg-[var(--fill)] hover:bg-[var(--fill-hover)] text-[var(--text-3)] flex items-center justify-center transition-colors cursor-pointer"
        >
          <Icon name="x" size={10} />
        </button>
      </div>

      {sections && sections.length > 0 ? (
        <>
          {sections.map((s) => (
            <div key={s.label}>
              <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--text-3)] block mb-0.5">
                {s.label}
              </span>
              <p className="text-[12px] text-[var(--text-2)] leading-snug">{s.text}</p>
            </div>
          ))}
        </>
      ) : payload ? (
        <>
          <div>
            <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--text-3)] block mb-0.5">
              Scoring basis
            </span>
            <p className="text-[12px] text-[var(--text-1)] leading-snug">{payload.formula}</p>
          </div>

          <div>
            <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--text-3)] block mb-0.5">
              Data source
            </span>
            <p className="text-[12px] text-[var(--text-2)] leading-snug">{payload.dataSource}</p>
          </div>

          <div>
            <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--text-3)] block mb-0.5">
              Fetched at
            </span>
            <p className="text-[12px] text-[var(--text-2)] leading-snug tabular-nums font-mono">
              {formatFetchedAt(payload.fetchedAt)}
            </p>
          </div>

          <div className="pt-1 border-t border-[var(--hairline)]">
            <p className="text-[11px] text-[var(--text-2)] leading-snug">
              {payload.status === 'ASSUMED'
                ? payload.fallbackNote ?? assumedFootnote('')
                : payload.status === 'UNKNOWN'
                ? 'Telemetry unavailable — the neutral placeholder shown is disclosed, never fabricated.'
                : payload.status === 'CALCULATED'
                ? 'Derived deterministically server-side; not a live telemetry reading.'
                : 'Measured from live telemetry during this analysis.'}
            </p>
          </div>
        </>
      ) : null}
    </>
  );
};
