/**
 * useSitePreview.ts — debounced /api/site/preview orchestration.
 * =======================================================================
 * Watches the shared boundary (+ optional coverage) and keeps the latest
 * preview response, with:
 *  - 400 ms debounce (audit spec) + in-flight abort on every change
 *  - map overlay updates via sitePreviewOverlay (local-tangent projection)
 *  - HUD state: loading shimmer / error / cached response
 * The backend is hash-cached and deterministic; this hook never mutates the
 * boundary model — it only renders it.
 */
import { useEffect, useRef, useState } from 'react';
import type { Map as MlMap } from 'maplibre-gl';
import {
  installPreviewLayers,
  updatePreviewSources,
  clearPreviewSources,
} from '../components/map/sitePreviewOverlay';
import { fetchSitePreview } from '../services/siteIntelligenceApi';
import {
  buildPreviewPayload,
  type SitePreviewResponse,
} from '../services/siteIntelligence';
import type { SharedBoundaryState } from '../services/siteBoundary';

const DEBOUNCE_MS = 400;

export interface UseSitePreviewOptions {
  /** Live MapLibre instance (owned by MapCanvas via onMapReady). */
  getMap: () => MlMap | null;
  boundary: SharedBoundaryState | null;
  coverageRatio?: number;
  enabled?: boolean;
}

export interface UseSitePreviewResult {
  preview: SitePreviewResponse | null;
  loading: boolean;
  error: string | null;
  dismiss: () => void;
}

export function useSitePreview({
  getMap,
  boundary,
  coverageRatio,
  enabled = true,
}: UseSitePreviewOptions): UseSitePreviewResult {
  const [preview, setPreview] = useState<SitePreviewResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  // A dismissal suppresses THIS boundary only. Keying it (instead of a boolean
  // latch) means re-committing a plot, or carrying it to a new pin, draws the
  // overlay again instead of leaving the site permanently preview-less.
  const dismissedKeyRef = useRef<string | null>(null);
  const boundaryKey =
    boundary && Array.isArray(boundary.vertices) && boundary.origin
      ? [
          boundary.origin.lat.toFixed(7),
          boundary.origin.lon.toFixed(7),
          boundary.frontageEdgeIndex ?? '',
          boundary.vertices.map((v) => `${v.x},${v.y}`).join(';'),
        ].join('|')
      : null;

  useEffect(() => {
    const valid =
      enabled &&
      boundary !== null &&
      Array.isArray(boundary.vertices) &&
      boundary.vertices.length >= 3;
    if (!valid) {
      setPreview(null);
      setError(null);
      setLoading(false);
      const map = getMap();
      if (map) clearPreviewSources(map);
      return;
    }
    if (dismissedKeyRef.current !== null && dismissedKeyRef.current === boundaryKey) return;

    const boundaryState = boundary as SharedBoundaryState;
    const controller = new AbortController();
    setLoading(true);
    setError(null);

    const timer = setTimeout(() => {
      fetchSitePreview(buildPreviewPayload(boundaryState, coverageRatio), controller.signal)
        .then((resp) => {
          setPreview(resp);
          const map = getMap();
          if (map) {
            installPreviewLayers(map);
            updatePreviewSources(map, {
              preview: resp,
              origin: boundaryState.origin,
            });
          }
        })
        .catch((e: unknown) => {
          if (controller.signal.aborted) return;
          setPreview(null);
          const map = getMap();
          if (map) clearPreviewSources(map);
          setError(e instanceof Error ? e.message : 'Site preview unavailable.');
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, DEBOUNCE_MS);

    return () => {
      controller.abort();
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    boundary?.vertices,
    boundary?.origin.lat,
    boundary?.origin.lon,
    boundary?.frontageEdgeIndex,
    boundary?.source,
    coverageRatio,
    enabled,
    boundaryKey,
    getMap,
  ]);

  const dismiss = (): void => {
    dismissedKeyRef.current = boundaryKey;
    setPreview(null);
    setError(null);
    setLoading(false);
    const map = getMap();
    if (map) clearPreviewSources(map);
  };

  return { preview, loading, error, dismiss };
}
