import React from 'react';
import { Sheet } from '../design';
import { Icon } from './Icon';

interface ConfirmResetDialogProps {
  open: boolean;
  /** What the reset will discard — shown verbatim so the dialog is honest. */
  onCancel: () => void;
  onConfirm: () => void;
}

/**
 * Destructive confirm for "Reset". Reset is irreversible (it drops the plot,
 * the analysis and the generated plan), so it goes through an explicit
 * confirmation instead of firing on the first click / keystroke. Built on the
 * design-system Sheet so focus, scroll lock and Escape behave like every other
 * modal.
 */
export const ConfirmResetDialog: React.FC<ConfirmResetDialogProps> = ({
  open,
  onCancel,
  onConfirm,
}) => (
  <Sheet
    open={open}
    onClose={onCancel}
    title="Reset this session?"
    subtitle="This clears the captured plot, the analysis and any generated plan."
    widthClass="max-w-md"
    /* Above the report sheet (z-2000): Reset is reachable via the R shortcut
       even while the dossier is open, and the confirmation must be visible. */
    zIndex={2100}
    footer={
      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          data-testid="reset-cancel"
          onClick={onCancel}
          className="h-9 px-3.5 rounded-[10px] bg-[var(--fill)] hover:bg-[var(--fill-hover)] text-[12.5px] font-medium text-[var(--text-1)] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
        >
          Keep session
        </button>
        <button
          type="button"
          data-testid="reset-confirm"
          onClick={onConfirm}
          className="h-9 px-3.5 rounded-[10px] bg-[var(--semantic-red)] hover:brightness-95 text-[12.5px] font-semibold text-white transition-[filter] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--semantic-red)]/40"
        >
          Reset session
        </button>
      </div>
    }
  >
    <div data-testid="reset-confirm-dialog" className="space-y-3">
      <div className="flex items-start gap-2.5">
        <span
          aria-hidden="true"
          className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[var(--semantic-red)]/12 text-[var(--semantic-red-ink)]"
        >
          <Icon name="alert-triangle" size={15} />
        </span>
        <p className="text-[12.5px] leading-relaxed text-[var(--text-2)]">
          You will return to a pristine first-run app: the boundary chip,
          the site analysis, the report and its generated plan are removed from
          this browser session. The site pin returns to the default view.
        </p>
      </div>
      <p className="pl-[38px] text-[11.5px] leading-snug text-[var(--text-3)]">
        Your theme, units and coach-mark preferences are kept.
      </p>
    </div>
  </Sheet>
);
