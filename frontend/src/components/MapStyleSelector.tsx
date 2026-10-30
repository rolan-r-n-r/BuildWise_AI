import React, { useEffect, useRef, useState } from 'react';
import { Icon, type IconName } from './Icon';

export type MapStyleMode = 'standard' | 'satellite' | 'terrain';

interface MapStyleSelectorProps {
  currentStyle: MapStyleMode;
  onStyleChange: (style: MapStyleMode) => void;
  /** Fired when the popover opens — used to pre-warm raster tiles for a snappy switch. */
  onOpen?: () => void;
  className?: string;
}

interface StyleOption {
  id: MapStyleMode;
  title: string;
  subtitle: string;
  icon: IconName;
}

const STYLE_OPTIONS: StyleOption[] = [
  {
    id: 'standard',
    title: 'Standard',
    subtitle: 'Streets & 3D buildings',
    icon: 'map',
  },
  {
    id: 'satellite',
    title: 'Satellite',
    subtitle: 'Aerial imagery + roads',
    icon: 'satellite',
  },
  {
    id: 'terrain',
    title: 'Terrain',
    subtitle: 'Topographic relief',
    icon: 'mountain',
  },
];

/** 36x36 Apple Maps-style mini preview card for each map mode (pure SVG, zero network). */
const StyleThumb: React.FC<{ mode: MapStyleMode }> = ({ mode }) => {
  if (mode === 'standard') {
    return (
      <svg width="36" height="36" viewBox="0 0 36 36" className="rounded-[9px] shrink-0" aria-hidden="true">
        <rect width="36" height="36" fill="#EAF2E6" />
        <path d="M0 26 C10 24 16 27 36 23" stroke="#FFFFFF" strokeWidth="3.5" fill="none" />
        <path d="M0 13 C12 11 20 15 36 11" stroke="#FFFFFF" strokeWidth="3" fill="none" />
        <path d="M9 0 L11 36" stroke="#FFD88A" strokeWidth="3.2" fill="none" />
        <path d="M25 0 L23 36" stroke="#FFD88A" strokeWidth="2.6" fill="none" />
        <rect x="14" y="15" width="6" height="6" rx="1" fill="#D8D5CE" />
        <rect x="28" y="17" width="5" height="5" rx="1" fill="#D8D5CE" />
        <circle cx="20" cy="7" r="4.5" fill="#BFE3B4" />
      </svg>
    );
  }
  if (mode === 'satellite') {
    return (
      <svg width="36" height="36" viewBox="0 0 36 36" className="rounded-[9px] shrink-0" aria-hidden="true">
        <defs>
          <linearGradient id="thumb-sat" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#3E5B3A" />
            <stop offset="0.55" stopColor="#57724A" />
            <stop offset="1" stopColor="#8A9168" />
          </linearGradient>
        </defs>
        <rect width="36" height="36" fill="url(#thumb-sat)" />
        <path d="M0 27 C9 25 15 28 36 24" stroke="#C9CDBD" strokeWidth="2.2" fill="none" opacity="0.85" />
        <path d="M8 0 L10 36" stroke="#D6D9CB" strokeWidth="1.8" fill="none" opacity="0.7" />
        <circle cx="24" cy="10" r="6" fill="#2C4A2E" opacity="0.9" />
        <rect x="13" y="19" width="7" height="5" rx="1" fill="#9BA0A6" opacity="0.9" />
      </svg>
    );
  }
  return (
    <svg width="36" height="36" viewBox="0 0 36 36" className="rounded-[9px] shrink-0" aria-hidden="true">
      <rect width="36" height="36" fill="#F4EBDD" />
      <path d="M2 24 C8 16 12 28 18 20 C24 12 28 22 34 16" stroke="#C9A876" strokeWidth="1.4" fill="none" />
      <path d="M2 18 C8 10 12 22 18 14 C24 6 28 16 34 10" stroke="#C9A876" strokeWidth="1.2" fill="none" opacity="0.8" />
      <path d="M2 30 C8 22 12 34 18 26 C24 18 28 28 34 22" stroke="#C9A876" strokeWidth="1.2" fill="none" opacity="0.8" />
      <path d="M11 12 L17 6 L22 13 L27 9" stroke="#8B6F47" strokeWidth="2.4" fill="none" strokeLinejoin="round" />
      <circle cx="17" cy="6.5" r="1.6" fill="#7A5C39" />
    </svg>
  );
};

export const MapStyleSelector: React.FC<MapStyleSelectorProps> = ({
  currentStyle,
  onStyleChange,
  onOpen,
  className = '',
}) => {
  const [isOpen, setIsOpen] = useState(false);

  // Global shortcut: 'M' opens this menu (event dispatched by useShortcuts).
  useEffect(() => {
    const openFromShortcut = (): void => setIsOpen(true);
    window.addEventListener('bw:open-map-styles', openFromShortcut);
    return () => window.removeEventListener('bw:open-map-styles', openFromShortcut);
  }, []);

  // Opening the picker is the strongest signal the user is about to switch styles:
  // give the raster modes a head start downloading tiles while they choose.
  useEffect(() => {
    if (isOpen) onOpen?.();
  }, [isOpen, onOpen]);
  const containerRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;

    const handlePointerDown = (e: MouseEvent | TouchEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsOpen(false);
        return;
      }

      // roving-focus arrow navigation, macOS menu behaviour
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        const buttons = listRef.current?.querySelectorAll<HTMLButtonElement>('[role="radio"]');
        if (!buttons || buttons.length === 0) return;
        const arr = Array.from(buttons);
        const idx = arr.indexOf(document.activeElement as HTMLButtonElement);
        const next =
          e.key === 'ArrowDown'
            ? arr[(idx + 1 + arr.length) % arr.length]
            : arr[(idx - 1 + arr.length) % arr.length];
        next?.focus();
      }

      if (e.key === 'Enter' || e.key === ' ') {
        const active = document.activeElement as HTMLButtonElement | null;
        if (active && listRef.current?.contains(active) && active.getAttribute('role') === 'radio') {
          e.preventDefault();
          const id = active.dataset.mode as MapStyleMode | undefined;
          if (id) {
            onStyleChange(id);
            setIsOpen(false);
          }
        }
      }
    };

    document.addEventListener('pointerdown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('pointerdown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onStyleChange]);

  return (
    <div ref={containerRef} className={`relative inline-block ${className}`}>
      {/* Trigger Button: Apple Maps Vibrancy Squircle */}
      <button
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        className={`bw-touch-target w-8 h-8 rounded-[10px] vibrancy-panel flex items-center justify-center transition-colors border border-[var(--panel-border-color)] shadow-md active:scale-95 ${
          isOpen || currentStyle !== 'standard'
            ? 'text-[var(--accent-ink)] bg-[var(--accent-tint)]'
            : 'text-[var(--text-1)] hover:bg-[var(--fill)]'
        }`}
        title="Map details (standard / satellite / terrain)"
        aria-label="Map details (standard / satellite / terrain)"
        aria-keyshortcuts="M"
        aria-expanded={isOpen}
        aria-haspopup="menu"
      >
        <Icon name="layers" size={15} />
      </button>

      {/* iOS Popover Sheet */}
      {isOpen && (
        <div
          role="dialog"
          aria-label="Map Details"
          className="absolute bottom-full mb-2 left-0 z-[1100] w-[264px] vibrancy-panel rounded-[16px] p-1.5 border border-[var(--panel-border-color)] shadow-2xl animate-popover-open origin-bottom-left select-none"
        >
          <div className="px-2.5 pt-1.5 pb-1 flex items-center justify-between text-[10px] font-semibold tracking-wider uppercase text-[var(--text-3)]">
            <span>Map Details</span>
          </div>

          <div className="h-[1px] w-full bg-[var(--hairline)] my-1" />

          <div ref={listRef} className="flex flex-col gap-0.5" role="radiogroup" aria-label="Map style">
            {STYLE_OPTIONS.map((opt) => {
              const isSelected = currentStyle === opt.id;
              return (
                <button
                  key={opt.id}
                  type="button"
                  data-mode={opt.id}
                  onClick={() => {
                    onStyleChange(opt.id);
                    setIsOpen(false);
                  }}
                  className={`w-full flex items-center gap-2.5 px-2 py-2 rounded-[11px] text-left transition-colors cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] ${
                    isSelected
                      ? 'bg-[var(--accent-tint)]'
                      : 'hover:bg-[var(--fill)]'
                  }`}
                  role="radio"
                  aria-checked={isSelected}
                  tabIndex={isSelected ? 0 : -1}
                >
                  <div
                    className={`rounded-[9px] shrink-0 overflow-hidden ring-1 transition-shadow ${
                      isSelected
                        ? 'ring-[var(--accent)] shadow-sm'
                        : 'ring-[var(--hairline)]'
                    }`}
                  >
                    <StyleThumb mode={opt.id} />
                  </div>

                  <div className="flex-1 min-w-0">
                    <div
                      className={`text-[12.5px] leading-tight font-medium ${
                        isSelected ? 'text-[var(--accent-ink)]' : 'text-[var(--text-1)]'
                      }`}
                    >
                      {opt.title}
                    </div>
                    <div className="text-[10.5px] text-[var(--text-2)] leading-tight truncate">
                      {opt.subtitle}
                    </div>
                  </div>

                  {isSelected && (
                    <Icon
                      name="check"
                      size={14}
                      className="text-[var(--accent-ink)] shrink-0 ml-1"
                    />
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};
