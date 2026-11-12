/**
 * WindowBar.tsx — a macOS window title bar.
 *
 * This is the landing's "this is a real Mac app" cue, and it is deliberately
 * structural rather than decorative:
 *  - The three lights are GREY at rest and gain their colours while the pointer
 *    is over the window (see `.bw-window:hover .bw-traffic` in index.css), which
 *    is what an unfocused window actually looks like on macOS. On touch devices
 *    the media query hands them their colour immediately.
 *  - The document title is centred and truncates, exactly like a real title bar,
 *    so a long site name degrades the way the OS degrades it.
 *  - The toolbar slot on the right is where the artefact states what it is.
 */
import React from 'react';
import { Icon } from '../components/Icon';

export interface WindowBarProps {
  /** Centred document title. */
  title: string;
  /** Secondary, dimmer fragment of the same title line. */
  subtitle?: string;
  /** Toolbar chips on the trailing edge. */
  toolbar?: React.ReactNode;
}

export const WindowBar: React.FC<WindowBarProps> = ({ title, subtitle, toolbar }) => (
  <div className="bw-window-bar">
    <span className="bw-traffic" aria-hidden>
      <span />
      <span />
      <span />
    </span>

    <p className="flex min-w-0 flex-1 items-baseline justify-center gap-2">
      <span className="truncate text-[13px] font-semibold tracking-[-0.01em] text-bw-ink">{title}</span>
      {subtitle && <span className="hidden truncate text-[12px] text-bw-ink-3 sm:inline">{subtitle}</span>}
    </p>

    <div className="flex flex-none items-center gap-0.5" aria-hidden>
      {toolbar ?? (
        <>
          <span className="bw-window-chip">
            <Icon name="search" size={13} />
          </span>
          <span className="bw-window-chip">
            <Icon name="layers" size={13} />
          </span>
        </>
      )}
    </div>
  </div>
);
