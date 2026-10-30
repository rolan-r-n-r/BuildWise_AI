/**
 * primitives.tsx — BuildWise AI Design System primitives.
 * =======================================================
 * The ONLY sanctioned building blocks for new/changed UI. Every primitive is
 * a macOS-grade dialect component: tokenized motion (`ui()`), focus-visible
 * rings, tabular numerals for measurements, reduced-motion safe, no layout
 * jump on state change.
 *
 * New primitive ⇒ document the justification in the PR + UX QA checklist.
 */
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import ReactDOM from 'react-dom';
import {
  ui,
  MOTION,
  prefersReducedMotion,
  TABULAR_NUMS_CLASS as tabularCls,
  Z_INDEX,
  RADII,
  HIT_TARGETS,
} from './tokens';

/* ================================================================== */
/* 0. DESIGN CONTEXT — reduced motion, toasts, shared state            */
/* ================================================================== */

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState<boolean>(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return false;
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  });
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const onChange = (e: MediaQueryListEvent) => setReduced(e.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);
  return reduced;
}

export interface ToastItem {
  id: number;
  message: string;
  tone?: 'neutral' | 'success' | 'warning' | 'critical';
  /** Auto-dismiss after this many ms (default 3500; 0 = sticky) */
  ttlMs?: number;
}

export interface DesignContextValue {
  toasts: ToastItem[];
  /** Toasts in their exit animation; kept in `toasts` until it completes. */
  exitingToasts: number[];
  dismissToast: (id: number) => void;
  pushToast: (t: Omit<ToastItem, 'id'>) => void;
  reducedMotion: boolean;
}

const DesignContext = createContext<DesignContextValue | null>(null);

export function DesignProvider({ children }: { children: React.ReactNode }): React.JSX.Element {
  const reducedMotion = useReducedMotion();
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [exitingToasts, setExitingToasts] = useState<number[]>([]);
  const nextId = useRef(1);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());
  const exitTimers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const dismissToast = useCallback((id: number) => {
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
    // A notification is a small surface: fade it out, then remove it. Under
    // reduced motion the removal is immediate (the CSS rule already collapses
    // the keyframe, but keeping the node around for 160 ms would still look
    // like a delayed state change).
    if (prefersReducedMotion()) {
      setToasts((prev) => prev.filter((t) => t.id !== id));
      setExitingToasts((prev) => prev.filter((x) => x !== id));
      return;
    }
    const existingExit = exitTimers.current.get(id);
    if (existingExit) clearTimeout(existingExit);
    setExitingToasts((prev) => (prev.includes(id) ? prev : [...prev, id]));
    const exit = setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
      setExitingToasts((prev) => prev.filter((x) => x !== id));
      exitTimers.current.delete(id);
    }, 160);
    exitTimers.current.set(id, exit);
  }, []);

  const pushToast = useCallback(
    (t: Omit<ToastItem, 'id'>) => {
      const id = nextId.current++;
      setToasts((prev) => [...prev.slice(-2), { ...t, id }]); // max 3 visible
      const ttl = t.ttlMs === undefined ? 3500 : t.ttlMs;
      if (ttl > 0) {
        timers.current.set(
          id,
          setTimeout(() => dismissToast(id), ttl)
        );
      }
    },
    [dismissToast]
  );

  useEffect(() => {
    const pending = timers.current;
    const exits = exitTimers.current;
    return () => {
      pending.forEach(clearTimeout);
      pending.clear();
      exits.forEach(clearTimeout);
      exits.clear();
    };
  }, []);

  const ctx = useMemo<DesignContextValue>(
    () => ({ toasts, exitingToasts, dismissToast, pushToast, reducedMotion }),
    [toasts, exitingToasts, dismissToast, pushToast, reducedMotion]
  );

  return <DesignContext.Provider value={ctx}>{children}</DesignContext.Provider>;
}

/**
 * usePresence — keeps a surface mounted long enough to animate OUT.
 *
 * A conditional `{open && <Sheet/>}` can enter beautifully and still disappear
 * in one frame, because unmounting has no transition. This returns `mounted`
 * for the render condition and `exiting` for the closing class. Reduced motion
 * unmounts immediately: there is no point holding a surface for an animation
 * the reader asked not to see.
 */
export function usePresence(
  open: boolean,
  exitMs: number = MOTION.duration.panel,
): { mounted: boolean; exiting: boolean } {
  const [mounted, setMounted] = useState<boolean>(open);

  useEffect(() => {
    if (open) {
      setMounted(true);
      return;
    }
    if (!mounted) return;
    const duration = prefersReducedMotion() ? 0 : exitMs;
    if (duration === 0) {
      setMounted(false);
      return;
    }
    const timer = setTimeout(() => setMounted(false), duration);
    return () => clearTimeout(timer);
  }, [open, mounted, exitMs]);

  return { mounted, exiting: mounted && !open };
}

export function useDesign(): DesignContextValue {
  const ctx = useContext(DesignContext);
  if (!ctx) {
    // Headless fallback so primitives work outside the provider (tests, fragments).
    return { toasts: [], exitingToasts: [], dismissToast: () => {}, pushToast: () => {}, reducedMotion: false };
  }
  return ctx;
}

export function useToast() {
  return useDesign().pushToast;
}

/* ================================================================== */
/* 1. COACH MARKS — dismissible, persisted, reduced-motion safe        */
/* ================================================================== */

export function useCoachMark(id: string, defaultOpen: boolean = true) {
  const storageKey = `bw.coach.${id}`;
  const [open, setOpen] = useState<boolean>(() => {
    if (typeof window === 'undefined' || !window.localStorage) return defaultOpen;
    try {
      return window.localStorage.getItem(storageKey) !== 'dismissed' && defaultOpen;
    } catch {
      return defaultOpen;
    }
  });
  const dismiss = useCallback(() => {
    setOpen(false);
    try {
      window.localStorage.setItem(storageKey, 'dismissed');
    } catch {
      /* storage unavailable — session-only dismissal */
    }
  }, [storageKey]);
  const reset = useCallback(() => {
    try {
      window.localStorage.removeItem(storageKey);
    } catch {
      /* noop */
    }
    setOpen(true);
  }, [storageKey]);
  return { open, dismiss, reset };
}

export interface CoachMarkProps {
  /** Anchors the bubble to this element; renders as plain block when omitted */
  anchorRef?: React.RefObject<HTMLElement>;
  title: 'string' | (string & {});
  body: string;
  open: boolean;
  onDismiss: () => void;
  placement?: 'bottom-start' | 'bottom-end' | 'top-start' | 'top-end';
}

const COACH_PLACEMENT: Record<NonNullable<CoachMarkProps['placement']>, string> = {
  'bottom-start': 'top-full mt-2 left-0',
  'bottom-end': 'top-full mt-2 right-0',
  'top-start': 'bottom-full mb-2 left-0',
  'top-end': 'bottom-full mb-2 right-0',
};

export const CoachMark: React.FC<CoachMarkProps> = ({
  anchorRef,
  title,
  body,
  open,
  onDismiss,
  placement = 'bottom-start',
}) => {
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  useLayoutEffect(() => {
    if (!anchorRef?.current || !open) return;
    const rect = anchorRef.current.getBoundingClientRect();
    setPos({ top: rect.bottom + 8, left: rect.left });
  }, [anchorRef, open]);
  if (!open) return null;

  const bubble = (
    <div
      role="note"
      aria-label={title}
      className={`w-[280px] vibrancy-panel rounded-[12px] p-3.5 shadow-xl ${ui('slow')} ${
        pos ? 'fixed' : `absolute ${COACH_PLACEMENT[placement]}`
      }`}
      style={pos ? { top: pos.top, left: Math.max(12, pos.left), zIndex: Z_INDEX.popover } : { zIndex: Z_INDEX.popover }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[13px] font-semibold text-[var(--text-1)]">{title}</div>
          <p className="mt-1 text-[12px] leading-[1.45] text-[var(--text-2)]">{body}</p>
        </div>
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss tip"
          className={`shrink-0 rounded-[7px] p-1 text-[var(--text-3)] hover:text-[var(--text-1)] hover:bg-[var(--fill)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] ${ui('base')}`}
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </button>
      </div>
    </div>
  );

  if (pos && typeof document !== 'undefined') return ReactDOM.createPortal(bubble, document.body);
  return bubble;
};

/* ================================================================== */
/* 2. TEXT PRIMITIVES — Kbd hint + ShortcutHint                        */
/* ================================================================== */

export const Kbd: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <kbd
    className={`inline-flex min-w-[18px] items-center justify-center rounded-[5px] border border-[var(--hairline)] bg-[var(--fill)] px-1 py-px font-semibold text-[10px] leading-[14px] text-[var(--text-2)] ${tabularCls}`}
  >
    {children}
  </kbd>
);

/** Render one key from tokens.SHORTCUTS as a Kbd badge (help sheet rows). */
export const ShortcutHint: React.FC<{ shortcutKey: string; className?: string }> = ({ shortcutKey, className }) => (
  <span className={`ml-1.5 inline-flex items-center ${className ?? ''}`} aria-hidden="true">
    <Kbd>{shortcutKey === '?' ? '?' : shortcutKey.toUpperCase()}</Kbd>
  </span>
);

/* ================================================================== */
/* 3. PillChip — status / summary chips (tabular numerals built in)    */
/* ================================================================== */

export type ChipTone = 'neutral' | 'accent' | 'success' | 'warning' | 'critical';

const CHIP_TONE_CLASS: Record<ChipTone, string> = {
  neutral: 'bg-[var(--fill)] text-[var(--text-1)]',
  accent: 'bg-[var(--accent-tint)] text-[var(--accent-ink)]',
  success: 'bg-[var(--accent-tint)] text-[var(--semantic-green-ink)]',
  warning: 'bg-[var(--accent-tint)] text-[var(--semantic-amber-ink)]',
  critical: 'bg-[var(--accent-tint)] text-[var(--semantic-red-ink)]',
};

export interface PillChipProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: ChipTone;
  icon?: React.ReactNode;
  onRemove?: () => void;
  removeLabel?: string;
  /** Numbers rendered inside get tabular numerals automatically */
  tabular?: boolean;
}

export const PillChip: React.FC<PillChipProps> = ({
  tone = 'neutral',
  icon,
  onRemove,
  removeLabel = 'Remove',
  tabular = true,
  className = '',
  children,
  ...rest
}) => (
  <span
    className={`inline-flex h-[22px] max-w-full items-center gap-1 rounded-full px-2 text-[11px] font-medium leading-none ${CHIP_TONE_CLASS[tone]} ${
      tabular ? tabularCls : ''
    } ${ui('base')} ${className}`}
    {...rest}
  >
    {icon && <span className="shrink-0 [&>svg]:block">{icon}</span>}
    <span className="truncate">{children}</span>
    {onRemove && (
      <button
        type="button"
        onClick={() => onRemove?.()}
        aria-label={removeLabel}
        className="-mr-0.5 ml-0.5 shrink-0 rounded-full p-0.5 opacity-60 hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]"
      >
        <svg width="9" height="9" viewBox="0 0 12 12" fill="none" aria-hidden="true">
          <path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      </button>
    )}
  </span>
);

/* ================================================================== */
/* 4. SegmentedControl — iOS style, roving focus, arrow keys           */
/* ================================================================== */

export interface SegmentedOption<T extends string = string> {
  id: T;
  label: string;
  sublabel?: string;
  icon?: React.ReactNode;
  disabled?: boolean;
  title?: string;
  /** Count pill rendered after the label (e.g. a warning count). */
  badge?: string | number;
}

export interface SegmentedControlProps<T extends string = string> {
  options: ReadonlyArray<SegmentedOption<T>>;
  value: T;
  onChange: (id: T) => void;
  size?: 'sm' | 'md';
  ariaLabel: string;
  className?: string;
  /**
   * 'radiogroup' (default) for value pickers; 'tablist' for tab bars, which
   * swaps aria-checked for aria-selected and wires aria-controls to the panel.
   */
  role?: 'radiogroup' | 'tablist';
  /** Panel id each tab controls (role="tablist" only). */
  panelId?: string;
  /** DOM-id prefix applied per tab button, e.g. `report-tab` (tablist only). */
  optionIdPrefix?: string;
  /** Equal-width grid cells instead of content-sized flex cells. */
  stretch?: boolean;
  /** Render a sliding accent pill behind the selected option (macOS toolbar). */
  indicator?: boolean;
}

/** Measured box of one segmented option, relative to the control's padding box. */
type PillBox = { left: number; top: number; width: number; height: number };

/**
 * iOS-style segmented control. One primitive serves every segmented surface:
 * value pickers (role=radiogroup) and tab bars (role=tablist), with roving
 * tabindex and arrow-key navigation. Tokenized motion + focus ring.
 */
export function SegmentedControl<T extends string = string>({
  options,
  value,
  onChange,
  size = 'md',
  ariaLabel,
  className = '',
  role = 'radiogroup',
  panelId,
  optionIdPrefix,
  stretch = false,
  indicator = false,
}: SegmentedControlProps<T>): React.JSX.Element {
  const rootRef = useRef<HTMLDivElement>(null);
  const sizeCls = size === 'sm' ? 'p-[2px] text-[11px]' : 'p-[3px] text-[12px]';
  const isTablist = role === 'tablist';

  // Reduced motion is an explicit branch, not a stylesheet hope: the global rule
  // only collapses the DURATION, and `transition-property` defaults to `all`,
  // so merely dropping the utility still leaves a 0.01ms transition on `all`.
  // The pill is then composited, which holds its RENDERED box at the old
  // position for two frames after the selection changes (the inline transform
  // is already correct in that first frame — measured: transform updated at
  // raf1, rect only at raf3). `transition-none` sets `transition-property: none`,
  // so under reduced motion the pill snaps in the same frame as the selection.
  const reducedMotion = useReducedMotion();

  // Sliding accent pill: place the selected option's indicator from CACHED
  // geometry, and refresh that cache after paint.
  //
  // Why: reading `offsetLeft/offsetWidth` right after the commit that changed the
  // selection forces a synchronous layout flush of the whole host sheet — on the
  // report tab bar that is an 1 818-node sheet, and the flush measured 32–115 ms
  // of self time INSIDE the tab-switch click handler (Long Task + INP every
  // switch). The geometry itself is stable, so the control now:
  //   1. applies the cached box for the new value — zero layout reads in the
  //      commit that follows a selection change,
  //   2. refreshes the cache in a batched post-paint pass, one read covering ALL
  //      options (never one read per option), and
  //   3. re-reads on the events that can actually change geometry: container
  //      resize, web-font swap, and a change to the option set.
  // The cost of a flush is not removed, it is moved off the input path — which is
  // what the interaction latency measures.
  const [pill, setPill] = useState<PillBox | null>(null);
  const pillCacheRef = useRef<Map<string, PillBox>>(new Map());
  const pillRafRef = useRef(0);
  const valueRef = useRef(value);

  const applyPill = useCallback((box: PillBox | null) => {
    if (!box) return;
    setPill((prev) =>
      prev && prev.left === box.left && prev.top === box.top && prev.width === box.width && prev.height === box.height
        ? prev
        : box
    );
  }, []);

  /** ONE batched read covering every option (a single layout pass). */
  const readPillBoxes = useCallback((): Map<string, PillBox> | null => {
    const root = rootRef.current;
    if (!root) return null;
    const boxes = new Map<string, PillBox>();
    for (const el of root.querySelectorAll<HTMLElement>('[data-seg-id]')) {
      const id = el.dataset.segId;
      if (id) {
        boxes.set(id, { left: el.offsetLeft, top: el.offsetTop, width: el.offsetWidth, height: el.offsetHeight });
      }
    }
    return boxes.size > 0 ? boxes : null;
  }, []);

  /** Re-measure AFTER paint (layout is clean by then) and re-apply the pill. */
  const refreshPill = useCallback(() => {
    if (!indicator) return;
    if (pillRafRef.current) cancelAnimationFrame(pillRafRef.current);
    pillRafRef.current = requestAnimationFrame(() => {
      // Second frame: the commit has been laid out and painted.
      pillRafRef.current = requestAnimationFrame(() => {
        pillRafRef.current = 0;
        const boxes = readPillBoxes();
        if (!boxes) return;
        pillCacheRef.current = boxes;
        applyPill(boxes.get(valueRef.current) ?? null);
      });
    });
  }, [indicator, readPillBoxes, applyPill]);

  // Selection changed (or the option set did): cancel any pending refresh, place
  // the pill from cache — no layout read here — then schedule a post-paint pass.
  useLayoutEffect(() => {
    if (!indicator) return;
    valueRef.current = value;
    applyPill(pillCacheRef.current.get(value) ?? null);
    refreshPill();
    return () => {
      if (pillRafRef.current) {
        cancelAnimationFrame(pillRafRef.current);
        pillRafRef.current = 0;
      }
    };
  }, [indicator, value, options.length, applyPill, refreshPill]);

  useEffect(() => {
    if (!indicator) return;
    const onGeometryChange = () => refreshPill();
    window.addEventListener('resize', onGeometryChange);
    let ro: ResizeObserver | undefined;
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(onGeometryChange);
      if (rootRef.current) ro.observe(rootRef.current);
    }
    // Web-font swap changes label metrics, so the cached boxes can go stale
    // without any resize event.
    let cancelled = false;
    const fonts = typeof document !== 'undefined' ? document.fonts : undefined;
    if (fonts && typeof fonts.ready?.then === 'function') {
      fonts.ready
        .then(() => {
          if (!cancelled) refreshPill();
        })
        .catch(() => {
          /* font loading is not observable — the resize/RO paths still cover it */
        });
    }
    return () => {
      cancelled = true;
      window.removeEventListener('resize', onGeometryChange);
      ro?.disconnect();
    };
  }, [indicator, refreshPill]);

  const moveFocus = (dir: 1 | -1) => {
    const enabled = options.filter((o) => !o.disabled);
    if (enabled.length === 0) return;
    const cur = enabled.findIndex((o) => o.id === value);
    const next = enabled[(Math.max(cur, 0) + dir + enabled.length) % enabled.length];
    if (!next || next.id === value) return;
    onChange(next.id);
    requestAnimationFrame(() => {
      rootRef.current?.querySelector<HTMLElement>(`[data-seg-id="${next.id}"]`)?.focus();
    });
  };

  return (
    <div
      ref={rootRef}
      role={role}
      aria-label={ariaLabel}
      className={`relative ${stretch ? 'grid' : 'inline-flex items-stretch'} rounded-[9px] bg-[var(--fill)] ${sizeCls} ${className}`}
      style={stretch ? { gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))` } : undefined}
    >
      {indicator && pill && (
        /* The indicator is positioned with translate() rather than left/top and
           only ever animates composited properties: an in-flow or left/top
           animation on a visible box is an invisible-to-the-user but REAL
           layout shift (measured CLS 0.0005 per tab switch on the report tab
           bar). With equal-width (stretch) segments the box is also constant
           sized, so a switch costs no layout at all. */
        <span
          aria-hidden="true"
          className={`absolute left-0 top-0 rounded-[7px] bg-[var(--segmented-active-bg)] bw-segmented-active-shadow pointer-events-none ${
            reducedMotion ? 'transition-none' : 'transition-[transform,width,height] duration-200 ease-apple'
          }`}
          style={{
            transform: `translate(${pill.left}px, ${pill.top}px)`,
            width: pill.width,
            height: pill.height,
          }}
          data-testid="segmented-indicator"
        />
      )}
      {options.map((opt) => {
        const selected = opt.id === value;
        return (
          <button
            key={opt.id}
            type="button"
            role={isTablist ? 'tab' : 'radio'}
            data-seg-id={opt.id}
            id={isTablist && optionIdPrefix ? `${optionIdPrefix}-${opt.id}` : undefined}
            aria-selected={isTablist ? selected : undefined}
            aria-checked={isTablist ? undefined : selected}
            aria-controls={isTablist ? panelId : undefined}
            title={opt.title}
            tabIndex={selected ? 0 : -1}
            disabled={opt.disabled}
            onClick={() => onChange(opt.id)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
                e.preventDefault();
                moveFocus(1);
              } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
                e.preventDefault();
                moveFocus(-1);
              }
            }}
            className={`relative z-[1] flex min-w-0 flex-1 items-center justify-center gap-1.5 rounded-[7px] px-2.5 font-medium ${ui('base')} focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] disabled:opacity-40 ${
              selected
                ? `text-[var(--segmented-active-label)] font-semibold ${indicator ? '' : 'bg-[var(--segmented-active-bg)] bw-segmented-active-shadow'}`
                : 'text-[var(--text-2)] hover:text-[var(--text-1)]'
            } ${opt.disabled ? 'cursor-not-allowed' : 'cursor-pointer'}`}
          >
            {opt.icon}
            <span className="truncate">{opt.label}</span>
            {opt.badge !== undefined && opt.badge !== null && opt.badge !== 0 && (
              <span
                className={`inline-flex items-center justify-center min-w-[1.1rem] h-[1.1rem] px-1 rounded-full text-[10px] font-bold ui-font-tabular shrink-0 ${
                  selected ? 'bg-[var(--accent)] text-white' : 'bg-[var(--accent-tint)] text-[var(--accent-ink)]'
                }`}
                title={`${opt.badge} warning${Number(opt.badge) === 1 ? '' : 's'}`}
              >
                {opt.badge}
              </span>
            )}
            {opt.sublabel && (
              <span
                className={`hidden text-[10px] font-normal sm:inline ${
                  selected ? 'text-[var(--segmented-active-sublabel)]' : ''
                }`}
              >
                {opt.sublabel}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/* ================================================================== */
/* 5. Sheet — centered modal with scrim (ESC, focus, scroll lock)      */
/* ================================================================== */

export interface SheetProps {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  widthClass?: string;
  footer?: React.ReactNode;
  /** Stacking override for sheets that must sit above another modal (e.g. reset). */
  zIndex?: number;
}

export const Sheet: React.FC<SheetProps> = ({
  open,
  onClose,
  title,
  subtitle,
  children,
  widthClass = 'max-w-lg',
  footer,
  zIndex = Z_INDEX.sheet,
}) => {
  const titleId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const presence = usePresence(open, MOTION.duration.panel);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', onKey);
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const t = window.setTimeout(() => {
      const focusables = panelRef.current?.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      (focusables && focusables.length > 0 ? focusables[0] : panelRef.current)?.focus();
    }, 0);
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = originalOverflow;
      window.clearTimeout(t);
    };
  }, [open, onClose]);

  if (!presence.mounted) return null;

  return ReactDOM.createPortal(
    <div className="fixed inset-0 flex items-center justify-center p-4" style={{ zIndex }}>
      <div
        className={`${presence.exiting ? 'animate-scrim-out' : 'animate-scrim'} absolute inset-0 bg-black/35 backdrop-blur-[2px]`}
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={`${presence.exiting ? 'animate-sheet-out' : 'animate-sheet-in'} relative flex max-h-[min(85vh,720px)] w-full flex-col ${widthClass} vibrancy-panel rounded-[16px] shadow-2xl focus:outline-none`}
      >
        <div className="flex items-start justify-between gap-3 border-b border-[var(--hairline)] px-5 py-3.5">
          <div className="min-w-0">
            <h2 id={titleId} className="text-[15px] font-semibold tracking-tight text-[var(--text-1)]">
              {title}
            </h2>
            {subtitle && <p className="mt-0.5 text-[12px] text-[var(--text-2)]">{subtitle}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className={`rounded-[8px] p-1.5 text-[var(--text-3)] hover:bg-[var(--fill)] hover:text-[var(--text-1)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] ${ui('base')}`}
          >
            <svg width="14" height="14" viewBox="0 0 12 12" fill="none" aria-hidden="true">
              <path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className="scrollbar-apple min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="border-t border-[var(--hairline)] px-5 py-3">{footer}</div>}
      </div>
    </div>,
    document.body
  );
};

/* ================================================================== */
/* 7. Tooltip — hover/focus, page-edge aware                           */
/* ================================================================== */

export interface TooltipProps {
  label: string;
  children: React.ReactElement;
  placeAbove?: boolean;
}

export const Tooltip: React.FC<TooltipProps> = ({ label, children, placeAbove = true }) => {
  const [show, setShow] = useState(false);
  const [flip, setFlip] = useState(false);
  const wrapRef = useRef<HTMLSpanElement>(null);

  const updateFlip = useCallback(() => {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    setFlip(placeAbove && rect.top < 48);
  }, [placeAbove]);

  const child = React.Children.only(children);
  const childProps = child.props as React.HTMLAttributes<HTMLElement>;
  const mergedProps: React.HTMLAttributes<HTMLElement> = {
    ...childProps,
    'aria-label': childProps['aria-label'] ?? label,
  };
  return (
    <span
      ref={wrapRef}
      className="relative inline-flex"
      onPointerEnter={() => {
        updateFlip();
        setShow(true);
      }}
      onPointerLeave={() => setShow(false)}
      onFocusCapture={() => {
        updateFlip();
        setShow(true);
      }}
      onBlurCapture={() => setShow(false)}
    >
      {React.cloneElement(child, mergedProps)}
      {show && (
        <span
          role="tooltip"
          className={`animate-popover-open pointer-events-none absolute left-1/2 z-[1050] w-max max-w-[240px] -translate-x-1/2 rounded-[8px] bg-[var(--text-1)] px-2 py-1 text-center text-[11px] font-medium leading-snug text-[var(--bg-page)] shadow-lg ${
            (placeAbove && !flip) || (!placeAbove && flip) ? 'bottom-[calc(100%+6px)]' : 'top-[calc(100%+6px)]'
          }`}
          style={{ zIndex: Z_INDEX.popover }}
        >
          {label}
        </span>
      )}
    </span>
  );
};

/* ================================================================== */
/* 8. Toast — portal viewport + hook API (useToast)                    */
/* ================================================================== */

const TOAST_TONE_PATH: Record<NonNullable<ToastItem['tone']>, string> = {
  neutral: 'M6 2.5a3.5 3.5 0 013.5 3.5c0 2.5 1 3 1 3H1.5s1-.5 1-3A3.5 3.5 0 016 2.5zM4.8 10.5a1.2 1.2 0 002.4 0',
  success: 'M2.5 6.5l2.5 2.5 4.5-5',
  warning: 'M6 2L11 10H1L6 2zM6 5.5v2M6 9.2v.1',
  critical: 'M6 1.75a4.25 4.25 0 100 8.5 4.25 4.25 0 000-8.5zM6 3.75v3M6 8.9v.1',
};

export const ToastViewport: React.FC = () => {
  const { toasts, exitingToasts, dismissToast } = useDesign();
  if (toasts.length === 0) return null;
  return ReactDOM.createPortal(
    <div
      className="pointer-events-none fixed bottom-4 left-1/2 flex w-max max-w-[min(92vw,420px)] -translate-x-1/2 flex-col items-center gap-2"
      style={{ zIndex: Z_INDEX.toast }}
      role="region"
      aria-label="Notifications"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          role="status"
          data-exiting={exitingToasts.includes(t.id) ? 'true' : 'false'}
          className={`${exitingToasts.includes(t.id) ? 'animate-toast-out pointer-events-none' : 'animate-toast-in pointer-events-auto'} flex items-center gap-2.5 rounded-[12px] px-3.5 py-2.5 shadow-xl vibrancy-panel ${ui('slow')}`}
        >
          {t.tone && t.tone !== 'neutral' && (
            <svg
              width="14"
              height="14"
              viewBox="0 0 12 12"
              fill="none"
              aria-hidden="true"
              className={`shrink-0 ${
                t.tone === 'success'
                  ? 'text-[var(--semantic-green-ink)]'
                  : t.tone === 'warning'
                    ? 'text-[var(--semantic-amber-ink)]'
                    : 'text-[var(--semantic-red-ink)]'
              }`}
            >
              <path d={TOAST_TONE_PATH[t.tone]} stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
          <span className="text-[12.5px] font-medium text-[var(--text-1)]">{t.message}</span>
          <button
            type="button"
            onClick={() => dismissToast(t.id)}
            aria-label="Dismiss notification"
            className={`rounded-full p-0.5 text-[var(--text-3)] hover:text-[var(--text-1)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] ${ui('base')}`}
          >
            <svg width="10" height="10" viewBox="0 0 12 12" fill="none" aria-hidden="true">
              <path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      ))}
    </div>,
    document.body
  );
};

/* ================================================================== */
/* 9. Stepper — numeric stepper (tabular value display, inline edit)   */
/* ================================================================== */

export interface StepperProps {
  label: string;
  value: number | string;
  onStep?: (direction: 1 | -1) => void;
  onCommit?: (raw: string) => void;
  formatValue?: (v: number | string) => string;
  disabled?: boolean;
  className?: string;
}

export const Stepper: React.FC<StepperProps> = ({
  label,
  value,
  onStep,
  onCommit,
  formatValue,
  disabled = false,
  className = '',
}) => {
  const [editing, setEditing] = useState<string | null>(null);
  const [pressed, setPressed] = useState<0 | 1 | -1>(0);
  const timerRef = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timerRef.current), []);

  const step = (dir: 1 | -1) => {
    if (disabled || !onStep) return;
    onStep(dir);
    setPressed(dir);
    window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => setPressed(0), 150);
  };

  const commit = () => {
    if (editing !== null) onCommit?.(editing);
    setEditing(null);
  };

  const display = formatValue ? formatValue(value) : String(value);

  return (
    <div className={`inline-flex h-7 items-center rounded-[8px] border border-[var(--hairline)] bg-[var(--fill)] ${className}`}>
      <button
        type="button"
        aria-label={`Decrease ${label}`}
        disabled={disabled}
        onClick={() => step(-1)}
        className={`flex h-full w-7 items-center justify-center rounded-l-[7px] text-[var(--text-2)] hover:bg-[var(--fill-hover)] hover:text-[var(--text-1)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--accent)] disabled:opacity-40 ${
          pressed === -1 ? 'scale-90' : ''
        } ${ui('fast')}`}
      >
        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
          <path d="M1.5 5h7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      </button>
      {editing !== null ? (
        <input
          aria-label={label}
          autoFocus
          inputMode="decimal"
          value={editing}
          onChange={(e) => setEditing(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit();
            if (e.key === 'Escape') setEditing(null);
          }}
          className={`h-full w-[64px] border-x border-[var(--hairline)] bg-transparent text-center text-[12px] font-semibold text-[var(--text-1)] outline-none ${tabularCls}`}
        />
      ) : (
        <button
          type="button"
          aria-label={`Edit ${label}`}
          disabled={disabled}
          onClick={() => setEditing(String(value))}
          className={`h-full w-[64px] border-x border-[var(--hairline)] text-center text-[12px] font-semibold text-[var(--text-1)] hover:bg-[var(--fill-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--accent)] disabled:opacity-40 ${tabularCls} ${ui(
            'fast'
          )}`}
        >
          {display}
        </button>
      )}
      <button
        type="button"
        aria-label={`Increase ${label}`}
        disabled={disabled}
        onClick={() => step(1)}
        className={`flex h-full w-7 items-center justify-center rounded-r-[7px] text-[var(--text-2)] hover:bg-[var(--fill-hover)] hover:text-[var(--text-1)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--accent)] disabled:opacity-40 ${
          pressed === 1 ? 'scale-90' : ''
        } ${ui('fast')}`}
      >
        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
          <path d="M1.5 5h7M5 1.5v7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      </button>
    </div>
  );
};

/* ================================================================== */
/* 10. IconButton — focus ring, hit target, motion                     */
/* ================================================================== */

export interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Accessible name; doubles as default tooltip label */
  label: string;
  active?: boolean;
}

export const IconButton = React.forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, active = false, className = '', type = 'button', style, children, ...rest },
  ref
) {
  return (
    <button
      ref={ref}
      type={type}
      title={label}
      aria-label={label}
      aria-pressed={active}
      className={`relative flex items-center justify-center text-[var(--text-1)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] disabled:opacity-40 disabled:hover:bg-transparent ${
        active ? 'bg-[var(--accent-tint)] text-[var(--accent-ink)]' : 'bg-[var(--fill)] hover:bg-[var(--fill-hover)]'
      } ${ui('base')} active:scale-[0.92] ${className}`}
      style={{
        width: HIT_TARGETS.iconButton,
        height: HIT_TARGETS.iconButton,
        borderRadius: RADII.md,
        ...style,
      }}
      {...rest}
    >
      {children}
    </button>
  );
});

/* ================================================================== */
/* 11. Select — iOS-style dropdown                                     */
/* ================================================================== */

/** Menu metrics: preferred height, minimum usable height, trigger gap, frame inset. */
const MENU_MAX_HEIGHT = 264;
const MENU_MIN_HEIGHT = 132;
const MENU_GAP = 4;
const MENU_MARGIN = 8;

export interface SelectOption {
  id: string | number;
  label: string;
  /** Optional supporting line rendered under the label inside the menu. */
  description?: string;
  /**
   * Disabled option. When paired with `disabledReason` the row is rendered
   * muted, is focusable-but-unselectable (aria-disabled) and shows the reason
   * as a tooltip + inline caption, so a blocked choice always states why.
   */
  disabled?: boolean;
  disabledReason?: string;
}

export interface SelectProps {
  id?: string;
  value: string | number;
  onChange: (value: string) => void;
  options: SelectOption[];
  ariaLabel?: string;
  disabled?: boolean;
  className?: string;
}

export const Select: React.FC<SelectProps> = ({
  id,
  value,
  onChange,
  options,
  ariaLabel,
  disabled = false,
  className = '',
}) => {
  const [open, setOpen] = useState(false);
  const [coords, setCoords] = useState<{
    /** Trigger edge the menu hangs from: bottom edge below, top edge above. */
    anchor: number;
    boundsTop: number;
    boundsBottom: number;
    left: number;
    minWidth: number;
    maxWidth: number;
    maxHeight: number;
    above: boolean;
  }>({
    anchor: 0,
    boundsTop: 0,
    boundsBottom: 0,
    left: 0,
    minWidth: 0,
    maxWidth: 0,
    maxHeight: MENU_MAX_HEIGHT,
    above: false,
  });
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const generatedId = useId();
  const selectId = id ?? generatedId;
  const listboxId = `${selectId}-listbox`;

  const selected = options.find((o) => String(o.id) === String(value)) ?? options[0];

  /**
   * Anchor the menu to its trigger without ever letting it leave the frame it
   * lives in (sidebar, drawer, modal) or the viewport:
   *  - the frame is the nearest scrollable ancestor and its CONTENT box bounds
   *    the menu, so the panel lines up with the cards inside the panel instead
   *    of spilling over their edges (the old viewport-only clamp let a
   *    description widen the menu a few pixels past the sidebar);
   *  - the menu may grow past a narrow trigger to fit its labels, but only as
   *    far as that frame allows;
   *  - its height is capped to the room actually available on the chosen side,
   *    so every option stays reachable by scrolling rather than running off
   *    the bottom of the screen;
   *  - the anchor itself is finally clamped inside that frame, so a trigger
   *    near — or scrolled past — the panel's edge can never push the menu out
   *    of the panel or window it belongs to.
   */
  const updateCoords = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();

    // Frame = nearest ancestor that can scroll its overflow. Pure
    // `overflow: hidden` wrappers (e.g. the collapsible body, which animates
    // its own height) are skipped: they are not the visible frame.
    let frame: HTMLElement | null = null;
    const scrolls = (v: string) => v === 'auto' || v === 'scroll';
    for (let node = trigger.parentElement; node; node = node.parentElement) {
      const { overflowX, overflowY } = getComputedStyle(node);
      if (scrolls(overflowY) || scrolls(overflowX)) {
        frame = node;
        break;
      }
    }

    const num = (v: string) => parseFloat(v) || 0;
    let bounds = { top: 0, bottom: window.innerHeight, left: 0, right: window.innerWidth };
    if (frame) {
      const cs = getComputedStyle(frame);
      const fr = frame.getBoundingClientRect();
      const left = fr.left + frame.clientLeft + num(cs.paddingLeft);
      const top = fr.top + frame.clientTop + num(cs.paddingTop);
      bounds = {
        top,
        bottom: top + Math.max(0, frame.clientHeight - num(cs.paddingTop) - num(cs.paddingBottom)),
        left,
        right: left + Math.max(0, frame.clientWidth - num(cs.paddingLeft) - num(cs.paddingRight)),
      };
    }
    bounds = {
      top: Math.max(MENU_MARGIN, bounds.top),
      bottom: Math.min(window.innerHeight - MENU_MARGIN, bounds.bottom),
      left: Math.max(MENU_MARGIN, bounds.left),
      right: Math.min(window.innerWidth - MENU_MARGIN, bounds.right),
    };

    const minWidth = Math.max(120, Math.min(rect.width, bounds.right - bounds.left));
    const left = Math.max(bounds.left, Math.min(rect.left, Math.max(bounds.left, bounds.right - minWidth)));
    const maxWidth = Math.max(minWidth, bounds.right - left);

    const spaceBelow = bounds.bottom - rect.bottom - MENU_GAP;
    const spaceAbove = rect.top - bounds.top - MENU_GAP;
    const above = spaceBelow < MENU_MAX_HEIGHT && spaceAbove > spaceBelow;
    const available = Math.max(MENU_MIN_HEIGHT, above ? spaceAbove : spaceBelow);

    setCoords({
      left,
      minWidth,
      maxWidth,
      maxHeight: Math.min(MENU_MAX_HEIGHT, available),
      above,
      anchor: above ? rect.top - MENU_GAP : rect.bottom + MENU_GAP,
      boundsTop: bounds.top,
      boundsBottom: bounds.bottom,
    });
  }, []);

  /**
   * Clamp the anchored menu inside the frame once its real height is known:
   * when the trigger sits outside the frame (a panel scrolled past its own
   * edge) the menu slides back in rather than hanging off the bottom of the
   * window, and an over-tall menu pins to the frame's top and scrolls. Runs
   * before paint, so the clamped position is the first one painted, and it only
   * overrides the anchor when the anchor would leave the frame.
   */
  useLayoutEffect(() => {
    const menu = menuRef.current;
    if (!open || !menu) return;
    const height = menu.offsetHeight;
    const limit = Math.max(coords.boundsTop, coords.boundsBottom - height);
    const anchored = coords.above ? coords.anchor - height : coords.anchor;
    const top = Math.min(Math.max(anchored, coords.boundsTop), limit);
    menu.style.top = `${top}px`;
    menu.style.bottom = 'auto';
  }, [open, coords, options]);

  const toggle = () => {
    if (disabled) return;
    if (!open) updateCoords();
    setOpen((p) => !p);
  };

  const choose = (optionId: string | number) => {
    onChange(String(optionId));
    setOpen(false);
    triggerRef.current?.focus();
  };

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        triggerRef.current?.focus();
      } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        const idx = options.findIndex((o) => String(o.id) === String(value));
        const dir = e.key === 'ArrowDown' ? 1 : -1;
        const next = options[(idx + dir + options.length) % options.length];
        if (next) onChange(String(next.id));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        setOpen(false);
      }
    };
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      if (menuRef.current && !menuRef.current.contains(target) && triggerRef.current && !triggerRef.current.contains(target)) {
        setOpen(false);
      }
    };
    const handleReposition = () => updateCoords();
    // CAPTURE phase: an open menu owns Escape before any page-level handler can
    // consume it. In bubble phase a trusted Escape never reached this listener
    // (the menu stayed open, with no way back but clicking outside).
    window.addEventListener('keydown', onKey, true);
    document.addEventListener('mousedown', onDown);
    window.addEventListener('resize', handleReposition);
    window.addEventListener('scroll', handleReposition, true);
    return () => {
      window.removeEventListener('keydown', onKey, true);
      document.removeEventListener('mousedown', onDown);
      window.removeEventListener('resize', handleReposition);
      window.removeEventListener('scroll', handleReposition, true);
    };
  }, [open, options, value, onChange, updateCoords]);

  return (
    <>
      <button
        ref={triggerRef}
        id={selectId}
        type="button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listboxId : undefined}
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={toggle}
        // Escape is handled on the trigger as well as window-wide: a page-level
        // handler that consumes the trusted keydown (the report sheet, a modal
        // scrim, an app shortcut) used to leave the menu open with no visible
        // way back except clicking outside. A combobox must always close on
        // Escape, whatever else is listening.
        onKeyDown={(e) => {
          if (e.key === 'Escape' && open) {
            e.stopPropagation();
            setOpen(false);
            triggerRef.current?.focus();
          }
        }}
        className={`inline-flex h-8 w-full items-center justify-between gap-1.5 rounded-[10px] border border-[var(--hairline)] bg-[var(--fill)] px-2.5 text-[12.5px] font-medium text-[var(--text-1)] hover:bg-[var(--fill-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] disabled:opacity-40 ${ui('base')} ${className}`}
      >
        <span className="truncate">{selected?.label ?? ''}</span>
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true" className={`shrink-0 text-[var(--text-3)] ${ui('base')}`} style={{ transform: open ? 'rotate(180deg)' : 'rotate(0deg)' }}>
          <path d="M2 3.5L5 6.5L8 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open &&
        ReactDOM.createPortal(
          <div
            ref={menuRef}
            id={listboxId}
            role="listbox"
            aria-labelledby={selectId}
            className="animate-popover-open fixed z-[1050] min-w-[120px] overflow-y-auto overflow-x-hidden overscroll-contain rounded-[12px] vibrancy-panel shadow-xl scrollbar-apple"
            style={{
              // Anchored to the trigger here; the layout effect clamps the final
              // position inside the frame. `bottom` keeps an open-upwards menu
              // clear of the trigger without a translate, which would fight the
              // popoverOpen keyframes.
              top: coords.above ? 'auto' : coords.anchor,
              bottom: coords.above ? window.innerHeight - coords.anchor : 'auto',
              left: coords.left,
              minWidth: coords.minWidth,
              maxWidth: coords.maxWidth,
              maxHeight: coords.maxHeight,
              transformOrigin: coords.above ? 'bottom' : 'top',
            }}
          >
            {options.map((opt) => {
              const isActive = String(opt.id) === String(value);
              const isDisabled = Boolean(opt.disabled);
              return (
                <button
                  key={String(opt.id)}
                  type="button"
                  role="option"
                  aria-selected={isActive}
                  aria-disabled={isDisabled || undefined}
                  disabled={isDisabled}
                  title={isDisabled ? opt.disabledReason : opt.description}
                  onClick={() => {
                    if (isDisabled) return;
                    choose(opt.id);
                  }}
                  className={`flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-[12.5px] ${ui('base')} focus-visible:outline-none focus-visible:bg-[var(--fill-hover)] ${
                    isDisabled
                      ? 'cursor-not-allowed text-[var(--text-3)] opacity-60'
                      : isActive
                      ? 'font-semibold text-[var(--accent-ink)]'
                      : 'text-[var(--text-1)] hover:bg-[var(--fill)]'
                  }`}
                >
                  <span className="min-w-0">
                    <span className="block truncate">{opt.label}</span>
                    {opt.description && (
                      <span className="block truncate text-[11px] font-normal text-[var(--text-3)] leading-snug">
                        {opt.description}
                      </span>
                    )}
                    {isDisabled && opt.disabledReason && (
                      <span className="block truncate text-[11px] font-normal text-[var(--semantic-amber-ink)] leading-snug">
                        {opt.disabledReason}
                      </span>
                    )}
                  </span>
                  {isActive && !isDisabled && (
                    <svg width="11" height="11" viewBox="0 0 12 12" fill="none" aria-hidden="true" className="shrink-0">
                      <path d="M2.5 6.5L5 9L9.5 3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </button>
              );
            })}
          </div>,
          document.body
        )}
    </>
  );
};

/* ================================================================== */
/* 12. KEYBOARD SHORTCUTS — global key registry + help sheet          */
/* ================================================================== */

import { SHORTCUTS } from './tokens';

export type ShortcutAction = 'toggleTheme' | 'openMapStyles' | 'resetApp' | 'toggleShortcuts';

export type ShortcutHandler = (action: ShortcutAction) => void;

/** Toggle the ? shortcuts sheet from anywhere via the module-level registry. */
let toggleShortcutsSheet: (() => void) | null = null;
export function registerShortcutsSheetToggle(fn: (() => void) | null): void {
  toggleShortcutsSheet = fn;
}

/**
 * Global keyboard shortcuts (T / M / R / ?), managed via React state:
 * single-key presses only (no modifier, not while typing in form fields).
 * A focused slider / switch / button is not a typing surface, so the shortcuts
 * keep working after a control in the sidebar has been keyboard-operated.
 * Escape closes the shortcuts sheet when open.
 */
const NON_TEXT_INPUT_TYPES = new Set([
  'range',
  'checkbox',
  'radio',
  'button',
  'submit',
  'reset',
  'color',
  'file',
]);

export function useShortcuts(handler: ShortcutHandler): void {
  const handlerRef = React.useRef(handler);
  handlerRef.current = handler;

  React.useEffect(() => {
    const isTypingTarget = (el: EventTarget | null): boolean => {
      const t = el as HTMLElement | null;
      if (!t || !t.tagName) return false;
      if (t.isContentEditable) return true;
      const tag = t.tagName.toLowerCase();
      if (tag === 'textarea' || tag === 'select') return true;
      if (tag !== 'input') return false;
      // Non-text inputs accept no characters, so they must not swallow shortcuts.
      const type = ((t as HTMLInputElement).type || 'text').toLowerCase();
      return !NON_TEXT_INPUT_TYPES.has(type);
    };

    const onKeyDown = (e: KeyboardEvent): void => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const key = e.key.toLowerCase();
      if (key === 'escape') {
        if (toggleShortcutsSheet) {
          toggleShortcutsSheet();
        }
        return;
      }
      if (isTypingTarget(e.target)) return;
      if (key === 't') handlerRef.current('toggleTheme');
      else if (key === 'm') handlerRef.current('openMapStyles');
      else if (key === 'r') handlerRef.current('resetApp');
      else if (key === '?') handlerRef.current('toggleShortcuts');
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);
}

/** Sheet listing the full shortcut registry — opened with "?" anywhere. */
export const ShortcutsSheet: React.FC<{ open: boolean; onClose: () => void }> = ({ open, onClose }) => {
  React.useEffect(() => {
    if (open) registerShortcutsSheetToggle(onClose);
    return () => {
      if (toggleShortcutsSheet === onClose) registerShortcutsSheetToggle(null);
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <Sheet open={open} onClose={onClose} title="Keyboard Shortcuts" widthClass="max-w-sm">
      <ul className="flex flex-col gap-2">
        {SHORTCUTS.map((s) => (
          <li
            key={s.key}
            className="flex items-center justify-between gap-3 rounded-[10px] bg-[var(--fill)] px-3 py-2"
          >
            <span className="text-[12.5px] text-[var(--text-1)]">{s.label}</span>
            <ShortcutHint shortcutKey={s.key} />
          </li>
        ))}
      </ul>
    </Sheet>
  );
};
