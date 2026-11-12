import React, { useEffect, useId, useState } from 'react';
import { Icon, type IconName } from '../Icon';

const PERSISTENCE_KEY = 'bw.report.sections.v1';

function loadCollapsedMap(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(PERSISTENCE_KEY);
    return raw ? (JSON.parse(raw) as Record<string, boolean>) : {};
  } catch {
    return {};
  }
}

function persistCollapsedMap(map: Record<string, boolean>) {
  try {
    localStorage.setItem(PERSISTENCE_KEY, JSON.stringify(map));
  } catch {
    /* storage unavailable (private mode) — collapse state stays in-memory only */
  }
}

interface CollapsibleSectionProps {
  /** Stable persistence key — toggle state survives sheet close/reopen. */
  sectionId: string;
  title: string;
  icon?: IconName;
  /** Static right-side slot (pills, counters). Must not depend on open state. */
  meta?: React.ReactNode;
  defaultOpen?: boolean;
  /**
   * 'plain': divider-style group header, children keep their own card chrome.
   * 'card':  the section itself is the card (children render bare content).
   */
  variant?: 'plain' | 'card';
  children: React.ReactNode;
}

/**
 * Card-grammar section: header row (click to collapse) + collapsible body.
 * Height animates via grid-rows over the token motion band; the global
 * prefers-reduced-motion rule collapses that to an instant toggle. Reserving
 * the header row keeps layout shift at zero when toggling.
 */
export const CollapsibleSection: React.FC<CollapsibleSectionProps> = ({
  sectionId,
  title,
  icon,
  meta,
  defaultOpen = true,
  variant = 'plain',
  children,
}) => {
  const isCard = variant === 'card';
  const contentId = useId();
  const [open, setOpen] = useState<boolean>(
    () => loadCollapsedMap()[sectionId] ?? defaultOpen
  );

  useEffect(() => {
    persistCollapsedMap({ ...loadCollapsedMap(), [sectionId]: open });
  }, [sectionId, open]);

  return (
    <section
      aria-label={title}
      className={`w-full min-w-0 ${
        isCard ? 'bw-card rounded-[16px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)]' : ''
      }`}
    >
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className={`w-full flex flex-wrap items-center justify-between gap-x-2 gap-y-0.5 text-left cursor-pointer select-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/40 ${
          isCard
            ? 'p-4 sm:p-[18px] pb-3 sm:pb-3.5'
            : 'py-1.5 rounded-[8px]'
        }`}
        aria-expanded={open}
        aria-controls={contentId}
      >
        {/* The title owns the first line; the meta slot wraps to its own line
            when the panel is narrow (in the 340px sidebar the meta pill used to
            squeeze "Building Configuration" down to "Building C…"). */}
        <span className="flex items-center gap-2 min-w-0 flex-1 basis-[max-content]">
          {icon && <Icon name={icon} size={15} className="text-[var(--text-2)] shrink-0" />}
          <span className="text-[14px] font-semibold text-[var(--text-1)] tracking-tight truncate">
            {title}
          </span>
        </span>
        <span className="flex items-center gap-2 shrink-0 ml-auto">
          {meta}
          <Icon
            name="chevron-down"
            size={14}
            className={`text-[var(--text-3)] transition-transform duration-200 ease-apple ${
              open ? 'rotate-180 text-[var(--text-1)]' : ''
            }`}
          />
        </span>
      </button>

      <div
        id={contentId}
        className={`grid transition-[grid-template-rows] duration-200 ease-apple ${
          open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
        }`}
      >
        <div className="overflow-hidden">
          <div className={isCard ? 'px-4 sm:px-[18px] pb-4 sm:pb-[18px] pt-2 border-t border-[var(--hairline)]' : 'pt-1.5'}>
            {children}
          </div>
        </div>
      </div>
    </section>
  );
};
