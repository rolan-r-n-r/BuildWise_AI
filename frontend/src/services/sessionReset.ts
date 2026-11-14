/**
 * sessionReset.ts — THE reset contract: pristine first-run state, one reducer.
 * ============================================================================
 * Reset used to be a hand-written list of `set*` calls in App.tsx, kept in
 * parallel with the first-run initialisers. The two drifted: the boundary was
 * never cleared (the chip, the preview overlay and the requests kept the old
 * plot), default parameters differed from first run (no coverage ratio, a
 * different AI provider) and the deep-link URL survived, so a reload restored
 * the site the user had just reset away. A reset must be the SAME state a
 * first-time visitor gets, not an approximation of it.
 *
 * This module is the single source of that contract:
 *   - PRISTINE_REQUEST / DEFAULT_SITE seed the app's first render,
 *   - sessionDataReducer({type:'reset'}) produces exactly those seeds again,
 *   - DATA_STORAGE_KEYS names every stored value a reset must drop.
 *
 * Preferences (theme, units, coach marks, the ASSISTED notice dismissal) are
 * deliberately NOT in this module: reset clears data, not preferences.
 */
import type {
  AnalysisParams,
  AnalysisResponse,
  FloorPlanResponse,
  SiteVisionResponse,
} from './types';
import type { SharedBoundaryState } from './siteBoundary';
import type { ProjectDetail } from './projectApi';

/** Where the site is. One pair of numbers, one owner — see `siteLocation`. */
export interface SiteLocation {
  latitude: number;
  longitude: number;
}

/** The app's default site (Bengaluru Urban) — the first-run map position. */
export const DEFAULT_SITE: SiteLocation = { latitude: 12.9716, longitude: 77.5946 };

/** First-run camera zoom over a located site (matches MapCanvas's located view). */
export const DEFAULT_SITE_ZOOM = 16;

/**
 * THE first-run parameters. `createInitialSessionData` and the reset reducer
 * both read this object, so the two states cannot disagree. Optional keys that
 * are absent here (client_requirements, extracted_constraints, overrides) are
 * data and must not survive a reset.
 */
export const PRISTINE_REQUEST: AnalysisParams = {
  built_up_area_sqft: 2000,
  quality_grade: 'standard',
  building_typology: 'residential_single',
  floors: 1,
  ai_provider: 'groq',
  ground_coverage_ratio: 0.6,
};

export type AiProvider = 'groq' | 'gemini' | 'mock';

/**
 * Every reset-critical datum the app holds. UI-only state (report tab, scroll
 * offsets, drawers, dialogs, the stale-plan guard's inputs) lives with its
 * owning component or is reset explicitly by App.performReset; everything that
 * describes a SITE or a PLAN lives here.
 */
export interface SessionDataState {
  /** The pin, owned by setSite. Only ever the site when no plot exists. */
  site: SiteLocation | null;
  /** The captured plot. Null means no boundary in state or on the map. */
  boundary: SharedBoundaryState | null;
  /** Analysis parameters (never coordinates — the plot/pin owns those). */
  request: AnalysisParams;
  analysisData: AnalysisResponse | null;
  siteVisionData: SiteVisionResponse | null;
  floorPlanData: FloorPlanResponse | null;
  overrideLandRate: number | null;
  overridePlotArea: number | null;
  /** Dev/test seam list (`window.__setTestWarnings`), also data. */
  testWarnings: string[] | null;
  /** A pin move held until the user decides what happens to the plot. */
  pendingSiteMove: { lat: number; lon: number } | null;
  /** Active saved project reference if this session originated from or was saved to SQLite. */
  activeProjectId: string | null;
  activeProjectName: string | null;
  /**
   * Bumped by reset only. Used as the `key` of data surfaces (ReportSheet) so
   * a reset is an unmount, not a prop update: no internal tab, scroll, plan or
   * generator state can outlive the session it belongs to.
   */
  sessionEpoch: number;
}

export type SessionDataAction =
  | { type: 'reset'; provider?: AiProvider }
  | { type: 'site'; site: SiteLocation | null }
  | { type: 'boundary'; boundary: SharedBoundaryState | null }
  | { type: 'request'; patch: Partial<AnalysisParams> }
  | { type: 'analysis'; analysis: AnalysisResponse | null }
  | { type: 'siteVision'; data: SiteVisionResponse | null }
  | { type: 'floorPlan'; plan: FloorPlanResponse | null }
  | { type: 'overrides'; rate: number | null; area: number | null }
  | { type: 'testWarnings'; warnings: string[] | null }
  | { type: 'pendingSiteMove'; move: { lat: number; lon: number } | null }
  | { type: 'setActiveProject'; id: string; name: string }
  | { type: 'clearActiveProject' }
  | { type: 'clearSite' }
  | { type: 'loadProject'; project: ProjectDetail };

/**
 * First-run state. A shared-site deep link is the ONLY input: it seeds the pin
 * before the first render (the map is created exactly once, already centred).
 */
export function createInitialSessionData(
  deepLinkSite: SiteLocation | null = null,
  provider: AiProvider = 'groq',
): SessionDataState {
  return {
    site: deepLinkSite ?? DEFAULT_SITE,
    boundary: null,
    request: { ...PRISTINE_REQUEST, ai_provider: provider },
    analysisData: null,
    siteVisionData: null,
    floorPlanData: null,
    overrideLandRate: null,
    overridePlotArea: null,
    testWarnings: null,
    pendingSiteMove: null,
    activeProjectId: null,
    activeProjectName: null,
    sessionEpoch: 0,
  };
}

/** The pristine state a reset must produce. */
export function pristineSessionData(provider: AiProvider = 'groq'): SessionDataState {
  return createInitialSessionData(null, provider);
}

/**
 * THE session reducer. Pure and framework-free so the reset contract can be
 * unit-tested without mounting the app (`scripts/test_reset_reducer.cjs`).
 *
 * `reset` deliberately recreates the seeds rather than patching fields one by
 * one: a newly added data field is cleared by construction, not by remembering
 * to add another `set*(null)` line.
 */
export function sessionDataReducer(
  state: SessionDataState,
  action: SessionDataAction,
): SessionDataState {
  switch (action.type) {
    case 'reset': {
      const pristine = pristineSessionData(action.provider ?? 'groq');
      return { ...pristine, sessionEpoch: state.sessionEpoch + 1 };
    }
    case 'site':
      return { ...state, site: action.site };
    case 'boundary':
      return {
        ...state,
        boundary: action.boundary,
        // A committed plot owns the site through its own origin; clearing it
        // leaves the pin where it was.
        site: action.boundary
          ? { latitude: action.boundary.origin.lat, longitude: action.boundary.origin.lon }
          : state.site,
      };
    case 'request':
      return { ...state, request: { ...state.request, ...action.patch } };
    case 'analysis':
      return { ...state, analysisData: action.analysis };
    case 'siteVision':
      return { ...state, siteVisionData: action.data };
    case 'floorPlan':
      return { ...state, floorPlanData: action.plan };
    case 'overrides':
      return { ...state, overrideLandRate: action.rate, overridePlotArea: action.area };
    case 'testWarnings':
      return { ...state, testWarnings: action.warnings };
    case 'pendingSiteMove':
      return { ...state, pendingSiteMove: action.move };
    case 'setActiveProject':
      return {
        ...state,
        activeProjectId: action.id,
        activeProjectName: action.name,
      };
    case 'clearActiveProject':
      return {
        ...state,
        activeProjectId: null,
        activeProjectName: null,
      };
    case 'clearSite':
      return {
        ...state,
        site: null,
        boundary: null,
        pendingSiteMove: null,
        analysisData: null,
        siteVisionData: null,
        floorPlanData: null,
        activeProjectId: null,
        activeProjectName: null,
      };
    case 'loadProject': {
      const p = action.project;
      const validBoundary =
        p.boundary && Array.isArray(p.boundary.vertices) && p.boundary.origin
          ? (p.boundary as SharedBoundaryState)
          : null;
      const loadedSite = validBoundary?.origin
        ? { latitude: validBoundary.origin.lat, longitude: validBoundary.origin.lon }
        : { latitude: p.latitude, longitude: p.longitude };
      return {
        ...state,
        site: loadedSite,
        boundary: validBoundary,
        request: {
          ...PRISTINE_REQUEST,
          ...(p.parameters as Partial<AnalysisParams>),
        },
        analysisData: p.analysis_data as AnalysisResponse | null,
        siteVisionData: p.site_vision_data as SiteVisionResponse | null,
        floorPlanData: p.floor_plan_data as FloorPlanResponse | null,
        overrideLandRate: null,
        overridePlotArea: null,
        pendingSiteMove: null,
        sessionEpoch: state.sessionEpoch + 1,
        activeProjectId: p.id,
        activeProjectName: p.name,
      };
    }
    default:
      return state;
  }
}

/* ==================================================================== */
/* Stored data a reset drops                                             */
/* ==================================================================== */

/** localStorage key holding the report's per-section collapse map. */
export const REPORT_SECTIONS_KEY = 'bw.report.sections.v1';
/** sessionStorage prefix for the report's remembered per-tab scroll offset. */
export const REPORT_SCROLL_PREFIX = 'bw.report.scroll.';
/** sessionStorage key holding draft site parameters for in-tab reloads. */
export const ACTIVE_SESSION_STORAGE_KEY = 'bw.session.active.v1';
/** sessionStorage key holding in-tab active analysis so accidental refresh keeps state. */
export const ACTIVE_TAB_ANALYSIS_KEY = 'bw.tab.analysis.v1';

/**
 * Checks whether a session state equals the default pristine first-run state.
 */
export function isPristineSession(state: SessionDataState): boolean {
  if (state.boundary !== null) return false;
  if (state.analysisData !== null) return false;
  if (state.floorPlanData !== null) return false;
  if (state.siteVisionData !== null) return false;
  if (state.overrideLandRate !== null || state.overridePlotArea !== null) return false;
  if (state.testWarnings !== null) return false;
  if (state.activeProjectId !== null || state.activeProjectName !== null) return false;
  if (
    state.site &&
    (Math.abs(state.site.latitude - DEFAULT_SITE.latitude) > 1e-4 ||
      Math.abs(state.site.longitude - DEFAULT_SITE.longitude) > 1e-4)
  ) {
    return false;
  }
  if (
    state.request.built_up_area_sqft !== PRISTINE_REQUEST.built_up_area_sqft ||
    state.request.quality_grade !== PRISTINE_REQUEST.quality_grade ||
    state.request.building_typology !== PRISTINE_REQUEST.building_typology ||
    state.request.floors !== PRISTINE_REQUEST.floors ||
    state.request.ground_coverage_ratio !== PRISTINE_REQUEST.ground_coverage_ratio
  ) {
    return false;
  }
  return true;
}

/**
 * Saves non-pristine session state to sessionStorage (tab-scoped).
 * Draft inputs (site, boundary, request) are stored in sessionStorage so they survive
 * in-tab reloads, but never bleed across tabs, browser restarts, or fresh sessions.
 * Full analysis & budget results are also kept in sessionStorage for in-tab refreshes only.
 * Any legacy localStorage draft key is actively purged.
 */
export function saveActiveSession(state: SessionDataState): void {
  if (typeof window === 'undefined') return;
  try {
    // Purge any legacy localStorage entry from earlier versions
    window.localStorage?.removeItem(ACTIVE_SESSION_STORAGE_KEY);

    if (isPristineSession(state)) {
      window.sessionStorage?.removeItem(ACTIVE_SESSION_STORAGE_KEY);
      window.sessionStorage?.removeItem(ACTIVE_TAB_ANALYSIS_KEY);
      return;
    }
    const payload = {
      site: state.site,
      boundary: state.boundary,
      request: state.request,
      activeProjectId: state.activeProjectId,
      activeProjectName: state.activeProjectName,
      savedAt: Date.now(),
    };
    window.sessionStorage?.setItem(ACTIVE_SESSION_STORAGE_KEY, JSON.stringify(payload));

    // Ephemeral analysis is stored in sessionStorage for in-tab refreshes only
    if (window.sessionStorage) {
      if (state.analysisData) {
        window.sessionStorage.setItem(
          ACTIVE_TAB_ANALYSIS_KEY,
          JSON.stringify({
            analysisData: state.analysisData,
            siteVisionData: state.siteVisionData,
            floorPlanData: state.floorPlanData,
            overrideLandRate: state.overrideLandRate,
            overridePlotArea: state.overridePlotArea,
          })
        );
      } else {
        window.sessionStorage.removeItem(ACTIVE_TAB_ANALYSIS_KEY);
      }
    }
  } catch {
    /* storage quota exceeded or disabled */
  }
}

/**
 * Loads the active session snapshot from sessionStorage (tab-scoped).
 * Purges any legacy localStorage draft key so old boundary or budget data is never restored.
 */
export function loadActiveSession(): Partial<SessionDataState> | null {
  if (typeof window === 'undefined') return null;
  try {
    // Purge any legacy localStorage entry
    window.localStorage?.removeItem(ACTIVE_SESSION_STORAGE_KEY);

    if (!window.sessionStorage) return null;
    const raw = window.sessionStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    return parsed;
  } catch {
    return null;
  }
}

/**
 * Restores session from storage.
 * On a fresh page / new browser session, completed analysis results and budgets are NEVER restored automatically.
 */
export function restoreSessionData(
  deepLinkSite: SiteLocation | null = null,
  provider: AiProvider = 'groq',
): SessionDataState {
  const pristine = createInitialSessionData(deepLinkSite, provider);
  if (typeof window === 'undefined') return pristine;
  const saved = loadActiveSession();
  if (!saved) return pristine;

  // Check if an ephemeral analysis exists in this specific tab session
  let tabAnalysis: any = null;
  try {
    if (window.sessionStorage) {
      const rawTab = window.sessionStorage.getItem(ACTIVE_TAB_ANALYSIS_KEY);
      if (rawTab) tabAnalysis = JSON.parse(rawTab);
    }
  } catch {
    tabAnalysis = null;
  }

  return {
    ...pristine,
    site: deepLinkSite ?? saved.site ?? pristine.site,
    boundary: saved.boundary ?? null,
    request: { ...pristine.request, ...(saved.request ?? {}) },
    analysisData: tabAnalysis?.analysisData ?? null,
    siteVisionData: tabAnalysis?.siteVisionData ?? null,
    floorPlanData: tabAnalysis?.floorPlanData ?? null,
    overrideLandRate: tabAnalysis?.overrideLandRate ?? null,
    overridePlotArea: tabAnalysis?.overridePlotArea ?? null,
    activeProjectId: saved.activeProjectId ?? null,
    activeProjectName: saved.activeProjectName ?? null,
  };
}

/**
 * A reset drops these. Everything else in storage is a preference or an
 * infrastructure cache and survives by design:
 *   buildwise.units          unit preference (may survive)
 *   bw.coach.*               coach marks (may survive)
 *   bw.assisted.continue     session notice dismissal (preference)
 *   bw.played.*              one-shot animation bookkeeping (ephemeral, not data)
 *   bw_geocode_v1:*          geocode response cache (24 h, location-agnostic)
 */
export function clearSessionDataStorage(): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(REPORT_SECTIONS_KEY);
    window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
  } catch {
    /* storage unavailable — nothing persisted to clear */
  }
  try {
    const session = window.sessionStorage;
    if (session) {
      session.removeItem(ACTIVE_SESSION_STORAGE_KEY);
      session.removeItem(ACTIVE_TAB_ANALYSIS_KEY);
      const doomed: string[] = [];
      for (let i = 0; i < session.length; i += 1) {
        const key = session.key(i);
        if (key && key.startsWith(REPORT_SCROLL_PREFIX)) doomed.push(key);
      }
      doomed.forEach((key) => session.removeItem(key));
    }
  } catch {
    /* storage unavailable */
  }
}

/**
 * Remove every transient URL input a reset must not leave behind, in place.
 *
 * `?lat=&lon=` is the shared-site deep link: it is read into the INITIAL state,
 * so leaving it in the address bar makes a reload restore the site the user
 * just reset. `start=capture` would reopen the wizard, and `#report` is the
 * open-report marker. History is patched (replaceState), never pushed: the
 * reset must not create a Back entry.
 */
export function stripTransientUrl(): void {
  if (typeof window === 'undefined') return;
  const url = new URL(window.location.href);
  ['lat', 'lon', 'start'].forEach((key) => url.searchParams.delete(key));
  const search = url.searchParams.toString();
  const next = `${url.pathname}${search ? `?${search}` : ''}${url.hash === '#report' ? '' : url.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next !== current) {
    window.history.replaceState(null, '', next);
  }
}
