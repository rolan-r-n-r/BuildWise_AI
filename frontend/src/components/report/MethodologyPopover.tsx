import React, { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import ReactDOM from 'react-dom';
import { Icon } from '../Icon';
import type { ProvenanceStatus } from './statusTaxonomy';

export interface MethodologyPayload {
  /** The deterministic scoring formula in plain language. */
  formula: string;
  /** Upstream data provider(s) actually consulted. */
  dataSource: string;
  /** ISO timestamp of the last successful fetch, when known. */
  fetchedAt?: string | null;
  /** Census status for this factor (renders a matched badge inside the popover). */
  status: ProvenanceStatus;
  /** Disclosure text for synthesized/modelled values. */
  fallbackNote?: string;
}

export interface MethodologySection {
  /** Short uppercase heading for one disclosed fact. */
  label: string;
  /** The fact itself, in plain language. */
  text: string;
}

interface MethodologyPopoverProps {
  /** Contents describing the factor (used as the accessible trigger label). */
  factorName: string;
  /** Provenance payload. Omit when using `sections` for a control disclosure. */
  payload?: MethodologyPayload;
  /** Panel heading override (defaults to the inferred "What this affects"). */
  title?: string;
  /**
   * Control-disclosure mode: replaces the provenance blocks with a list of
   * "what does this affect?" facts. Used by authoring controls whose value
   * changes downstream outputs (rate table, sheet schedules, programme sizing).
   */
  sections?: MethodologySection[];
  /** Accessible name for the trigger button (defaults to the factor name). */
  triggerLabel?: string;
}

const PANEL_WIDTH = 288;

/**
 * The panel BODY is a separate, lazily loaded chunk.
 *
 * Why it is not in this module: this popover is used by the authoring form,
 * which paints with the shell, and its body needs the report's provenance
 * vocabulary (`StatusBadge`, the status taxonomy). Importing those statically
 * put report-surface code in the /app initial graph — the measured +3 KB gz the
 * bundle pin reports. A panel body exists only after a reader opens a trigger,
 * so it loads then. Everything a reader can touch before opening — the trigger,
 * its label, its layout — stays synchronous here.
 *
 * The same import is fired on pointer-over and focus, so the chunk is normally
 * already in flight (or resolved) by the time a click lands: the click path is
 * not made to wait for a module the reader has already signalled intent for.
 */
const loadPanel = () => import('./MethodologyPopoverPanel');
const MethodologyPopoverPanel = React.lazy(() =>
  loadPanel().then((m) => ({ default: m.MethodologyPopoverPanel })),
);

/** Height of the loading placeholder, so the first measurement is not a zero. */
const PANEL_FALLBACK_HEIGHT = 120;

const PanelSkeleton: React.FC = () => (
  <div
    className="space-y-2.5"
    style={{ minHeight: PANEL_FALLBACK_HEIGHT }}
    aria-hidden="true"
    data-testid="methodology-popover-loading"
  >
    <div className="h-3 w-24 rounded bg-[var(--fill)]" />
    <div className="h-2.5 w-full rounded bg-[var(--fill)]" />
    <div className="h-2.5 w-5/6 rounded bg-[var(--fill)]" />
  </div>
);

/**
 * Disclosure popover pinned to a small "i" trigger. Keyboard contract:
 * Enter/Space open, Escape closes and returns focus to the trigger, the
 * content is linked via aria-describedby from the trigger, and an outside
 * click dismisses it.
 *
 * The panel is portalled to <body> and positioned in viewport coordinates so it
 * can never be clipped by an ancestor with overflow hidden (collapsible cards,
 * scrolling sidebars) — the bug class that cut off disclosures in the tile.
 * Both themes use the same token suite, so parity is automatic.
 */
export const MethodologyPopover: React.FC<MethodologyPopoverProps> = ({
  factorName,
  payload,
  title,
  sections,
  triggerLabel,
}) => {
  const [open, setOpen] = useState(false);
  const [coords, setCoords] = useState<{ top: number; left: number; width: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const contentId = useId();

  const close = useCallback(() => {
    setOpen(false);
    triggerRef.current?.focus();
  }, []);

  // Measure the trigger + the rendered panel height so the panel can flip above
  // the trigger when the viewport bottom would clip it. `updateCoords` is also
  // handed to the lazily loaded body, which calls it once it has mounted: the
  // skeleton's height is a placeholder, the body's is the real one.
  const updateCoords = useCallback(() => {
    const rect = triggerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const width = Math.min(PANEL_WIDTH, window.innerWidth - 16);
    const left = Math.max(8, Math.min(rect.right - width, window.innerWidth - width - 8));
    const height = panelRef.current?.offsetHeight ?? 200;
    const below = rect.bottom + 6;
    const flipsAbove = below + height > window.innerHeight - 8 && rect.top - height - 6 > 8;
    setCoords({ top: flipsAbove ? rect.top - height - 6 : below, left, width });
  }, []);

  useLayoutEffect(() => {
    if (open) updateCoords();
  }, [open, updateCoords]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        close();
      }
    };
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (panelRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      setOpen(false);
    };
    const reposition = () => updateCoords();
    window.addEventListener('keydown', onKey, true);
    document.addEventListener('mousedown', onDown);
    window.addEventListener('resize', reposition);
    window.addEventListener('scroll', reposition, true);
    return () => {
      window.removeEventListener('keydown', onKey, true);
      document.removeEventListener('mousedown', onDown);
      window.removeEventListener('resize', reposition);
      window.removeEventListener('scroll', reposition, true);
    };
  }, [open, close, updateCoords]);

  useEffect(() => {
    if (open && panelRef.current) {
      panelRef.current.focus();
    }
  }, [open]);

  const panel =
    open && coords
      ? ReactDOM.createPortal(
          <div
            ref={panelRef}
            id={contentId}
            role="dialog"
            aria-label={`${factorName} methodology`}
            tabIndex={-1}
            data-testid={`methodology-popover-${factorName.replace(/\s+/g, '-').toLowerCase()}`}
            className="animate-popover-open fixed z-[var(--z-popover,1050)] rounded-[12px] border border-[var(--panel-border-color)] bg-[var(--sheet-bg)] shadow-xl p-3.5 space-y-2.5 text-left"
            style={{ top: coords.top, left: coords.left, width: coords.width }}
          >
            <React.Suspense fallback={<PanelSkeleton />}>
              <MethodologyPopoverPanel
                payload={payload}
                title={title}
                sections={sections}
                onClose={close}
                onMeasured={updateCoords}
              />
            </React.Suspense>
          </div>,
          document.body
        )
      : null;

  return (
    <span className="relative inline-flex shrink-0">
      <button
        type="button"
        ref={triggerRef}
        onClick={() => {
          loadPanel();
          setOpen((prev) => !prev);
        }}
        onPointerEnter={() => {
          void loadPanel();
        }}
        onFocus={() => {
          void loadPanel();
        }}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-describedby={open ? contentId : undefined}
        title={triggerLabel ?? `What ${factorName} affects`}
        aria-label={triggerLabel ?? `Methodology for ${factorName}`}
        className="w-5 h-5 rounded-full bg-[var(--fill)] hover:bg-[var(--fill-hover)] text-[var(--text-3)] hover:text-[var(--text-1)] flex items-center justify-center transition-colors duration-150 ease-apple cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/40"
      >
        <Icon name="info" size={11} />
      </button>
      {panel}
    </span>
  );
};
