/**
 * ArrivalSlice.tsx — mount an ARRIVING section on an idle slice.
 * ==============================================================
 * When a generated plan lands in an open report sheet, everything that appears
 * with it used to commit in one task: the certificate panel and its QA rows, the
 * plan's schedules, on top of a full re-render of the sheet. At 4× that arrival
 * is the only surface still over the 25 ms script budget (80.2 ms `MessagePort`
 * — React rendering the whole arrival in one go).
 *
 * A slice defers ONE section's first render to the next idle moment. Two rules
 * make that safe inside a report the reader is looking at:
 *
 *   • SAME-HEIGHT PLACEHOLDER. A slice that changes the height of what is above
 *     it is a layout shift with extra steps, and CLS is measured across this
 *     mount. So the placeholder reserves the height this slice measured the last
 *     time it mounted (a module-level cache keyed by slice id); the first-ever
 *     mount falls back to the caller's estimate and the real height is recorded
 *     for every arrival after it.
 *
 *   • NO PLACEHOLDER FOR CONTENT THAT IS ALREADY THERE. `isArrival` is the
 *     caller's own "this data turned up while the reader was looking at the
 *     section" signal (ReportSheet tracks the plan key it has already shown). A
 *     tab visit, a reopened sheet or a regenerate renders the finished section
 *     immediately: the slice is for arrivals, not for tab visits, which
 *     `useDeferredValue(panelTab)` already transitions.
 *
 * The reveal itself is a transition, so an interaction that lands in the same
 * idle window (a tab click, a floor switch) still wins over mounting a card.
 */
import React from 'react';
import { Skeleton } from './Skeleton';

/** Last measured content height per slice id — what the next placeholder reserves. */
const sliceHeights = new Map<string, number>();

/** Keep the height cache bounded across long sessions. */
const MAX_REMEMBERED_SLICES = 24;

export interface ArrivalSliceProps {
  /** Stable id — it is also the height-cache key. */
  sliceId: string;
  /** True when this section's data arrived while the reader was on the tab. */
  isArrival: boolean;
  /** Height to reserve before this slice has ever been measured. */
  fallbackHeight: number;
  /** Accessible description of what is loading. */
  label: string;
  className?: string;
  children: React.ReactNode;
}

export const ArrivalSlice: React.FC<ArrivalSliceProps> = ({
  sliceId,
  isArrival,
  fallbackHeight,
  label,
  className = '',
  children,
}) => {
  // Read once, at mount: a later render of the same arrival is not a second one.
  const deferRef = React.useRef<boolean>(isArrival);
  const [mounted, setMounted] = React.useState<boolean>(() => !isArrival);
  const boxRef = React.useRef<HTMLDivElement | null>(null);
  const reservedHeight = React.useMemo<number>(
    () => sliceHeights.get(sliceId) ?? fallbackHeight,
    [sliceId, fallbackHeight],
  );

  React.useEffect(() => {
    if (!deferRef.current || mounted) return;
    let cancelled = false;
    const reveal = (): void => {
      if (cancelled) return;
      React.startTransition(() => setMounted(true));
    };
    const hasIdle = typeof window !== 'undefined' && typeof window.requestIdleCallback === 'function';
    const handle = hasIdle
      ? window.requestIdleCallback(reveal, { timeout: 400 })
      : window.setTimeout(reveal, 40);
    return () => {
      cancelled = true;
      if (hasIdle) window.cancelIdleCallback(handle);
      else clearTimeout(handle);
    };
  }, [mounted]);

  /**
   * Record what the section actually measures, so the NEXT arrival reserves
   * exactly that. Deliberately after layout and once per mount: this is a report
   * that is already being laid out, and the read is free at that point.
   */
  React.useLayoutEffect(() => {
    if (!mounted) return;
    const el = boxRef.current;
    if (!el) return;
    const h = Math.round(el.getBoundingClientRect().height);
    if (h <= 0) return;
    if (sliceHeights.size >= MAX_REMEMBERED_SLICES && !sliceHeights.has(sliceId)) {
      sliceHeights.delete(sliceHeights.keys().next().value as string);
    }
    sliceHeights.set(sliceId, h);
  }, [mounted, sliceId]);

  if (!mounted) {
    return (
      <div
        ref={boxRef}
        data-slice-placeholder={sliceId}
        aria-busy="true"
        className={`relative w-full min-w-0 ${className}`}
        style={{ minHeight: reservedHeight }}
      >
        <Skeleton className="absolute inset-0 rounded-[16px]" label={label} />
      </div>
    );
  }

  return (
    <div ref={boxRef} data-slice-mounted={sliceId} className={`w-full min-w-0 ${className}`}>
      {children}
    </div>
  );
};
