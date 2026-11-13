import React, { useRef, useCallback } from 'react';

export type SheetGestureState = {
  mode: 'none' | 'pan' | 'pinch';
  dist: number;
  zoom: number;
  x: number;
  y: number;
};

export interface SheetGestureHookOpts {
  getPan: () => { x: number; y: number };
  setPan: (p: { x: number; y: number } | ((prev: { x: number; y: number }) => { x: number; y: number })) => void;
  getZoom: () => number;
  setZoom: (z: number | ((prev: number) => number)) => void;
  minZoom: number;
  maxZoom: number;
  onDoubleTap?: () => void;
}

/**
 * Direct-manipulation gestures for a fixed-fidelity drawing sheet:
 * one-finger drag pans, two-finger pinch zooms, and double-tap steps zoom.
 * State & refs are encapsulated to avoid render-time ref mutations and object recreations.
 */
export function useSheetGestures(opts: SheetGestureHookOpts) {
  const { getPan, setPan, getZoom, setZoom, minZoom, maxZoom, onDoubleTap } = opts;
  const gestureRef = useRef<SheetGestureState>({ mode: 'none', dist: 0, zoom: 1, x: 0, y: 0 });
  const panStartRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const lastTapRef = useRef<{ t: number; x: number; y: number }>({ t: 0, x: 0, y: 0 });
  const movedRef = useRef<boolean>(false);

  const onTouchStart = useCallback(
    (e: React.TouchEvent<HTMLDivElement>) => {
      const g = gestureRef.current;
      if (e.touches.length === 2) {
        const a = e.touches[0];
        const b = e.touches[1];
        g.mode = 'pinch';
        g.dist = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
        g.zoom = getZoom();
      } else if (e.touches.length === 1) {
        g.mode = 'pan';
        g.x = e.touches[0].clientX;
        g.y = e.touches[0].clientY;
        panStartRef.current = { ...getPan() };
        movedRef.current = false;
      }
    },
    [getPan, getZoom]
  );

  const onTouchMove = useCallback(
    (e: React.TouchEvent<HTMLDivElement>) => {
      const g = gestureRef.current;
      if (g.mode === 'pinch' && e.touches.length === 2) {
        const a = e.touches[0];
        const b = e.touches[1];
        const dist = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
        if (g.dist > 0) {
          const next = Math.min(maxZoom, Math.max(minZoom, g.zoom * (dist / g.dist)));
          setZoom(Number(next.toFixed(2)));
        }
      } else if (g.mode === 'pan' && e.touches.length === 1) {
        const dx = e.touches[0].clientX - g.x;
        const dy = e.touches[0].clientY - g.y;
        if (Math.abs(dx) + Math.abs(dy) > 6) {
          movedRef.current = true;
        }
        setPan({ x: panStartRef.current.x + dx, y: panStartRef.current.y + dy });
      }
    },
    [maxZoom, minZoom, setPan, setZoom]
  );

  const onTouchEnd = useCallback(
    (e: React.TouchEvent<HTMLDivElement>) => {
      const g = gestureRef.current;
      if (g.mode === 'pan' && e.changedTouches.length > 0 && !movedRef.current) {
        const t = e.changedTouches[0];
        const now = Date.now();
        const last = lastTapRef.current;
        if (now - last.t < 300 && Math.hypot(t.clientX - last.x, t.clientY - last.y) < 24) {
          onDoubleTap?.();
          lastTapRef.current = { t: 0, x: 0, y: 0 };
        } else {
          lastTapRef.current = { t: now, x: t.clientX, y: t.clientY };
        }
      }
      g.mode = 'none';
    },
    [onDoubleTap]
  );

  return { onTouchStart, onTouchMove, onTouchEnd, movedRef };
}
