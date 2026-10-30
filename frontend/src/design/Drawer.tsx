/**
 * Drawer.tsx — responsive drawer primitive.
 * ===================================================================
 * One component for both mobile panel patterns:
 *   • side="left"|"right" — edge drawer (slide from the screen edge)
 *   • side="bottom"       — bottom sheet (grabber + swipe-down dismiss)
 *
 * Contract (global rules): scrim click + ESC dismiss, focus trapped while
 * open and returned to the trigger on close, 150-200ms ease-out transitions
 * (motion tokens), reduced-motion honored, safe-area insets respected,
 * scroll contained (no chaining to the page).
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { usePresence, useReducedMotion } from './primitives';
import { Z_INDEX } from './tokens';

export type DrawerSide = 'left' | 'right' | 'bottom';

export interface DrawerProps {
  open: boolean;
  onClose: () => void;
  side: DrawerSide;
  /** Accessible name for the dialog (aria-label on the panel). */
  label: string;
  /** Optional DOM id for the panel (test hooks / aria-controls). */
  id?: string;
  /** Element to restore focus to on close (usually the trigger button). */
  returnFocusRef?: React.RefObject<HTMLElement | null>;
  /** Rendered content. */
  children: React.ReactNode;
  /** Extra classes on the panel (width, radius, etc). */
  className?: string;
  /** Hide the bottom-sheet grabber (default: shown for side="bottom"). */
  showGrabber?: boolean;
}

/** Focusable elements for the focus trap. */
const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export const Drawer: React.FC<DrawerProps> = ({
  open,
  onClose,
  side,
  label,
  id,
  returnFocusRef,
  children,
  className = '',
  showGrabber = true,
}) => {
  const panelRef = useRef<HTMLDivElement>(null);
  const [dragY, setDragY] = useState<number>(0);
  const dragState = useRef<{ startY: number; active: boolean; dismissing: boolean }>({
    startY: 0,
    active: false,
    dismissing: false,
  });
  const reduced = useReducedMotion();
  const presence = usePresence(open);

  /* Focus management: trap + restore + initial focus */
  useEffect(() => {
    if (!open) return;
    const panel = panelRef.current;
    if (!panel) return;

    const previous = document.activeElement as HTMLElement | null;
    const focusTimer = window.setTimeout(() => {
      const first = panel.querySelector<HTMLElement>(FOCUSABLE);
      (first ?? panel).focus();
    }, 60);

    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== 'Tab') return;
      const items = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener('keydown', onKey, true);

    return () => {
      window.clearTimeout(focusTimer);
      window.removeEventListener('keydown', onKey, true);
      const target = returnFocusRef?.current ?? previous;
      if (target && typeof target.focus === 'function') target.focus();
    };
  }, [open, onClose, returnFocusRef]);

  /* Bottom-sheet swipe-to-dismiss (touch only; drag follows the finger) */
  const onTouchStart = useCallback(
    (e: React.TouchEvent) => {
      if (side !== 'bottom' || reduced) return;
      // Only initiate swipe-to-dismiss when scrolled to the very top
      const currentScrollTop = panelRef.current ? panelRef.current.scrollTop : 0;
      if (currentScrollTop > 0) {
        dragState.current = { startY: e.touches[0].clientY, active: false, dismissing: false };
        return;
      }
      dragState.current = { startY: e.touches[0].clientY, active: true, dismissing: false };
    },
    [side, reduced]
  );

  const onTouchMove = useCallback(
    (e: React.TouchEvent) => {
      if (!dragState.current.active || side !== 'bottom') return;
      const currentScrollTop = panelRef.current ? panelRef.current.scrollTop : 0;
      if (currentScrollTop > 0) {
        dragState.current.dismissing = false;
        setDragY(0);
        return;
      }
      const dy = e.touches[0].clientY - dragState.current.startY;
      if (dy > 0) {
        dragState.current.dismissing = true;
        setDragY(dy);
      } else {
        dragState.current.dismissing = false;
        setDragY(0);
      }
    },
    [side]
  );

  const onTouchEnd = useCallback(() => {
    if (!dragState.current.active) return;
    dragState.current.active = false;
    if (dragState.current.dismissing && dragY > 80) {
      setDragY(0);
      onClose();
    } else {
      setDragY(0);
    }
  }, [dragY, onClose]);

  if (!presence.mounted) return null;

  const isBottom = side === 'bottom';
  const isLeft = side === 'left';

  const panelPosition: React.CSSProperties = isBottom
    ? {
        left: 0,
        right: 0,
        bottom: 0,
        maxHeight: '86vh',
        borderRadius: '20px 20px 0 0',
        transform: dragY > 0 ? `translateY(${dragY}px)` : undefined,
        transition: dragY > 0 ? 'none' : undefined,
      }
    : {
        top: 0,
        bottom: 0,
        [isLeft ? 'left' : 'right']: 0,
        maxWidth: 'calc(100vw - 24px)',
      };

  return (
    <>
      {/* Scrim */}
      <div
        aria-hidden="true"
        onClick={onClose}
        className={`fixed inset-0 bg-black/25 z-[1040] ${presence.exiting ? 'animate-scrim-out' : 'animate-scrim'}`}
        style={{ zIndex: Z_INDEX.popover - 10 }}
      />
      {/* Panel */}
      <div
        ref={panelRef}
        id={id}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        tabIndex={-1}
        data-side={side}
        data-exiting={presence.exiting ? 'true' : 'false'}
        className={`fixed bw-drawer bw-scroll-pane ${isBottom ? 'bw-drawer-bottom' : ''} ${className}`}
        style={{
          zIndex: Z_INDEX.popover,
          ...panelPosition,
        }}
        onClick={(e) => e.stopPropagation()}
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
      >
        {isBottom && showGrabber && <div className="bw-drawer-grabber" aria-hidden="true" />}
        {children}
      </div>
    </>
  );
};
