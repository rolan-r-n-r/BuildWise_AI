/**
 * Client-side geocode API helper for BuildWise.
 *
 * Two-layer caching:
 *   1. In-memory Map (session lifetime, instant)
 *   2. localStorage (24 h TTL, survives page refresh)
 *
 * Attribution: Nominatim / OpenStreetMap contributors; Photon / Komoot
 */

import { API_BASE_URL } from './api';

export interface GeocodeResult {
  display_name: string;
  lat: number;
  lon: number;
  source: 'nominatim' | 'photon';
}

export interface GeocodeResponse {
  results: GeocodeResult[];
  provider: string;
  cached: boolean;
  error: string | null;
}

export interface ReverseGeocodeProbe {
  address: string | null;
  water: boolean;
  water_name: string | null;
  /** True when the probe could not answer; do NOT read this as "on land". */
  is_fallback: boolean;
  error?: string;
}

// -------------------------------------------------------------------------- //
// localStorage cache helpers (24 h TTL)
// -------------------------------------------------------------------------- //

const LS_PREFIX = 'bw_geocode_v1:';
const LS_TTL_MS = 86_400_000; // 24 h

function lsGet(key: string): GeocodeResponse | null {
  try {
    const raw = localStorage.getItem(LS_PREFIX + key);
    if (!raw) return null;
    const { ts, data } = JSON.parse(raw) as { ts: number; data: GeocodeResponse };
    if (Date.now() - ts > LS_TTL_MS) {
      localStorage.removeItem(LS_PREFIX + key);
      return null;
    }
    return data;
  } catch {
    return null;
  }
}

function lsSet(key: string, data: GeocodeResponse): void {
  try {
    localStorage.setItem(LS_PREFIX + key, JSON.stringify({ ts: Date.now(), data }));
  } catch {
    // quota exceeded or private-mode — silently ignore
  }
}

// -------------------------------------------------------------------------- //
// In-memory session cache
// -------------------------------------------------------------------------- //

const _memCache = new Map<string, GeocodeResponse>();

// -------------------------------------------------------------------------- //
// Public API
// -------------------------------------------------------------------------- //

/**
 * Search for up to 5 location suggestions for `query`.
 *
 * Results are cached:
 *   - in-memory (session)
 *   - localStorage (24 h)
 *
 * Never throws; always resolves with a GeocodeResponse.
 */
/**
 * Probe one coordinate for the manual-entry guard.
 * Never throws: an unreachable probe returns ``is_fallback: true`` so the UI
 * can disclose that the offshore check did not run rather than claim land.
 */
export async function reverseGeocodeProbe(lat: number, lon: number): Promise<ReverseGeocodeProbe> {
  try {
    const resp = await fetch(
      `${API_BASE_URL}/api/geocode/reverse?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`,
      { headers: { Accept: 'application/json' } },
    );
    if (!resp.ok) throw new Error(`reverse geocode HTTP ${resp.status}`);
    const data = (await resp.json()) as Partial<ReverseGeocodeProbe>;
    return {
      address: data.address ?? null,
      water: data.water === true,
      water_name: data.water_name ?? null,
      is_fallback: data.is_fallback !== false,
    };
  } catch {
    return {
      address: null,
      water: false,
      water_name: null,
      is_fallback: true,
      error: 'Offshore check unavailable.',
    };
  }
}

export async function geocodeSearch(query: string): Promise<GeocodeResponse> {
  const key = query.trim().toLowerCase();
  if (!key) {
    return { results: [], provider: 'none', cached: true, error: null };
  }

  // 1. Memory cache
  const mem = _memCache.get(key);
  if (mem) return mem;

  // 2. localStorage cache
  const ls = lsGet(key);
  if (ls) {
    _memCache.set(key, ls);
    return ls;
  }

  // 3. Backend proxy (Nominatim → Photon)
  try {
    const resp = await fetch(
      `${API_BASE_URL}/api/geocode?q=${encodeURIComponent(key)}`,
      { headers: { Accept: 'application/json' } }
    );
    if (!resp.ok) {
      throw new Error(`geocode HTTP ${resp.status}`);
    }
    const data: GeocodeResponse = await resp.json();
    if (!data.error && Array.isArray(data.results)) {
      _memCache.set(key, data);
      if (data.results.length > 0) {
        lsSet(key, data);
      }
    }
    return data;
  } catch {
    const fallback: GeocodeResponse = {
      results: [],
      provider: 'none',
      cached: false,
      error: 'Search unavailable. Enter coordinates manually.',
    };
    return fallback;
  }
}
