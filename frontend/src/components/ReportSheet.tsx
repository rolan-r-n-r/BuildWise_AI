import React, { useState, useEffect, useLayoutEffect, useMemo, useRef, useCallback } from 'react';
import { flushSync } from 'react-dom';
import type {
  AnalysisResponse,
  SiteVisionResponse,
  FloorPlanResponse,
  ReportRequestPayload,
  AnalysisParams,
} from '../services/types';
import { ReportHeroHeader } from './report/ReportHeroHeader';
import { CollapsibleSection } from './report/CollapsibleSection';
import { WarningsBanner } from './report/WarningsBanner';
import { bannerWarnings } from '../services/planWarnings';
import { ProvenanceFactorCard } from './report/ProvenanceFactorCard';
import { CertificatePanel } from './report/CertificatePanel';
import { LandEconomicsPanel } from './report/LandEconomicsPanel';
import { ArrivalSlice } from './report/ArrivalSlice';
import { CostRangeBar } from './report/CostRangeBar';
import { WindRose } from './report/WindRose';
import { ProvenanceFooter } from './report/ProvenanceFooter';
import { SeismicZoneChip } from './report/SeismicZoneChip';
import { UnitToggle } from './report/UnitToggle';
import { CopyValueButton } from './report/CopyValueButton';
import { RecommendationPanel } from './RecommendationPanel';
import { HazardProfileCard } from './HazardProfileCard';
import { RiskMatrix } from './RiskMatrix';
import { DataSourcesDisclosure } from './DataSourcesDisclosure';
import { SiteVisionCard } from './SiteVisionCard';
import { OrientationCompass } from './OrientationCompass';
import { VastuAdvisoryCard } from './VastuAdvisoryCard';
import { CostBreakdownTable } from './CostBreakdownTable';
import { LandValueCard } from './LandValueCard';
import { FloorPlanGeneratorCard } from './FloorPlanGeneratorCard';
import type { SharedBoundaryState } from '../services/siteBoundary';
import { DownloadReportButton } from './DownloadReportButton';
import { Icon } from './Icon';
import { SegmentedControl, useMediaQuery } from '../design';
import { ReportEmptyState } from './report/ReportEmptyState';
import { CPWD_DISCLOSURE } from './report/termDisclosures';
import { TabContextBar } from './report/TabContextBar';
import { formatIN, formatINR } from '../services/numberFormat';
import { staggerClassFor } from './report/playOnce';
import { holdMapRender, releaseMapRender, holdMapRenderAcrossCommit } from '../services/mapRenderGate';
import { SectionNav } from './report/SectionNav';
import { AnimatedNumber } from './report/AnimatedNumber';

export type ResultsTab = 'overview' | 'hazards' | 'ecology' | 'cost_plan';

/**
 * Tracks whether the document is currently being prepared for printing.
 *
 * The sheet carries a SECOND copy of the whole dossier — a four-section stacked
 * tree that exists only so `window.print()` can emit all tabs at once (print
 * cannot show a tab that is not in the DOM). Kept always-mounted that copy is
 * ~1 200 nodes, 67 % of the sheet, re-rendered on every tab switch, scroll-state
 * change and unit toggle. So it is mounted for the duration of a print pass and
 * unmounted afterwards.
 *
 * Two independent signals, because no single one covers every browser:
 *   - `beforeprint` / `afterprint` — real Ctrl+P / ⌘P and the toolbar Print
 *     button. `beforeprint` fires while the print render is still pending, so the
 *     mount is flushed synchronously; anything less and the browser can snapshot
 *     the document before React commits the print tree.
 *   - `matchMedia('print')` change — the media-type override path used by
 *     DevTools "Emulate CSS media type", CDP/Puppeteer `emulateMedia`, and the
 *     browsers that flip the media type without firing `beforeprint`.
 * Leaving print mode clears the flag, so the copy never survives the pass.
 */
function usePrintMode(): [boolean, () => void] {
  // Seeded from the media type at first render, so a sheet that mounts while
  // print media is already active comes up in print mode without an effect-time
  // state write.
  const [printing, setPrinting] = useState<boolean>(() =>
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia('print').matches
      : false
  );

  /** Turn print mode ON synchronously (the snapshot may already be in flight). */
  const engage = React.useCallback(() => {
    try {
      flushSync(() => setPrinting(true));
    } catch {
      // Called while React is already rendering/committing — the plain update is
      // still correct, it just lands on the next flush.
      setPrinting(true);
    }
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;

    const onBeforePrint = () => engage();
    const onAfterPrint = () => setPrinting(false);
    window.addEventListener('beforeprint', onBeforePrint);
    window.addEventListener('afterprint', onAfterPrint);

    const mql = typeof window.matchMedia === 'function' ? window.matchMedia('print') : null;
    const onMediaChange = () => {
      if (mql?.matches) engage();
      else setPrinting(false);
      // (setting false needs no flush: unmounting early is never a correctness risk)
    };
    if (mql) {
      if (typeof mql.addEventListener === 'function') mql.addEventListener('change', onMediaChange);
      else mql.addListener?.(onMediaChange);
    }

    return () => {
      window.removeEventListener('beforeprint', onBeforePrint);
      window.removeEventListener('afterprint', onAfterPrint);
      if (mql) {
        if (typeof mql.removeEventListener === 'function') mql.removeEventListener('change', onMediaChange);
        else mql.removeListener?.(onMediaChange);
      }
    };      }, [engage]);

  return [printing, engage];
}

export interface ReportSheetProps {
  isOpen: boolean;
  onClose: () => void;
  analysisData: AnalysisResponse;
  /** Parameters only (no coordinates): the plot owns where this report is. */
  analysisRequest?: AnalysisParams;
  /** Applies a remediation's validated parameter change to the shared request. */
  onRequestPatch?: (patch: Partial<AnalysisParams>) => void;
  siteVisionData: SiteVisionResponse | null;
  isSiteVisionLoading: boolean;
  onRunSiteVision: (modeOverride?: 'segformer' | 'index-only') => void;
  hasLocation: boolean;
  floorPlanData: FloorPlanResponse | null;
  onFloorPlanGenerated: (plan: FloorPlanResponse) => void;
  overrideLandRate: number | null;
  overridePlotArea: number | null;
  onOverrideChange: (rate: number | null, area: number | null) => void;
  reportPayload: ReportRequestPayload;
  activeTab: ResultsTab;
  onTabChange: (tab: ResultsTab) => void;
  sharedBoundary?: SharedBoundaryState | null;
}

const TABS: {
  id: ResultsTab;
  label: string;
  icon: 'layers' | 'alert-triangle' | 'wind' | 'currency-rupee';
}[] = [
  { id: 'overview', label: 'Overview', icon: 'layers' },
  { id: 'hazards', label: 'Hazards', icon: 'alert-triangle' },
  { id: 'ecology', label: 'Ecology', icon: 'wind' },
  { id: 'cost_plan', label: 'Cost & Plan', icon: 'currency-rupee' },
];

/**
 * In-tab section nav links. The link id IS the `data-report-section` value, so
 * the scroll-spy drives the active state with no mapping. DOM targets are
 * `sec-<id>`.
 *
 * Coverage rule: a link exists only when its section can render. `certificate`
 * is conditional (it lives inside `floorPlanData?.qa`), so `sectionLinks`
 * filters it out until a blueprint exists — a pill that scrolls nowhere is
 * worse than no pill. Hazards and Ecology carry no links at all: both tabs are
 * a couple of screens under their own headings, so the nav renders nothing for
 * them rather than an empty tray.
 *
 * Cost & Plan covers every anchor it has, including `breakdown` — the 650px
 * cost composition block used to be unmapped, so the tray sat on "Estimate"
 * for half the tab while the header read "Cost Breakdown".
 */
const TAB_SECTION_LINKS: Partial<Record<ResultsTab, { id: string; label: string }[]>> = {
  overview: [
    { id: 'summary', label: 'Summary' },
    { id: 'factors', label: 'Factors' },
    { id: 'commentary', label: 'Recommendations' },
  ],
  cost_plan: [
    { id: 'estimate', label: 'Estimate' },
    { id: 'breakdown', label: 'Cost Breakdown' },
    { id: 'landvalue', label: 'Land Value' },
    { id: 'certificate', label: 'Certificate' },
    { id: 'land', label: 'Land & Space' },
    { id: 'blueprint', label: 'Blueprint' },
  ],
};

/** sessionStorage key for a tab's remembered scroll offset. */
const scrollKeyFor = (tab: ResultsTab) => `bw.report.scroll.${tab}`;

/**
 * Minimum spacing between scroll-position writes. The write is synchronous main
 * thread I/O, so it is deliberately not attempted more than twice a second
 * however often the scroll position changes.
 */
const WRITE_INTERVAL_MS = 400;

/**
 * Height the certificate placeholder reserves before this session has ever
 * measured that section (ArrivalSlice caches the real height from the first
 * arrival on, so every later arrival reserves exactly what it will occupy).
 */
const CERTIFICATE_FALLBACK_HEIGHT = 560;

/**
 * CPWD plinth-area-rate tiers (₹/sq ft). Mirrors the engine constant
 * BASE_RATES in backend/app/services/cost_service.py so the grade→cost chip can
 * show every grade's rate and the delta without a round-trip. Keep in sync.
 */
const GRADE_RATES_INR_PER_SQFT = [
  { id: 'basic', label: 'Basic', rate: 1500 },
  { id: 'standard', label: 'Standard', rate: 2200 },
  { id: 'premium', label: 'Premium', rate: 3500 },
] as const;

/** Memoized factor-card list: re-renders only when the data or unit preference changes. */
const MemoizedFactorList: React.FC<{
  factors: AnalysisResponse['factors'];
  dataSources?: AnalysisResponse['data_sources'];
  methodology?: AnalysisResponse['methodology'];
}> = React.memo(({ factors, dataSources, methodology }) => (
  <div className="divide-y divide-[var(--hairline)]">
    {factors.map((factor, idx) => (
      <ProvenanceFactorCard
        key={factor.factor_id}
        factor={factor}
        rank={idx + 1}
        dataSources={dataSources}
        methodology={methodology}
      />
    ))}
  </div>
));
MemoizedFactorList.displayName = 'MemoizedFactorList';

export const ReportSheet: React.FC<ReportSheetProps> = ({
  isOpen,
  onClose,
  analysisData,
  analysisRequest,
  sharedBoundary,
  siteVisionData,
  isSiteVisionLoading,
  onRunSiteVision,
  hasLocation,
  floorPlanData,
  onFloorPlanGenerated,
  onRequestPatch,
  overrideLandRate,
  overridePlotArea,
  onOverrideChange,
  reportPayload,
  activeTab,
  onTabChange,
}) => {
  const [copiedRef, setCopiedRef] = useState(false);
  const [activeSection, setActiveSection] = useState<string>('');
  /** True once the active tab's pane is scrolled far enough to want a "Top". */
  const [paneScrolled, setPaneScrolled] = useState(false);
  const sheetRef = useRef<HTMLDivElement>(null);
  const contentScrollRef = useRef<HTMLDivElement>(null);
  /**
   * The stacked print copy of the dossier is mounted only for the duration of a
   * print pass — see `usePrintMode`. `printing` is true from `beforeprint` (or a
   * print media-type override) until `afterprint` (or media exit).
   */
  const [printing, engagePrintMode] = usePrintMode();

  /**
   * ONE live tab bar, not two CSS-hidden ones.
   *
   * Both the desktop segmented control and the compact strip used to be
   * mounted at every width and hidden with `hidden lg:flex` / `lg:hidden`. The
   * hidden copy still contributed `role="tab"` buttons with `tabIndex=0` and a
   * 0x0 box: a phantom focus target and a duplicate
   * tab set. Mounting only the bar for the current width removes the
   * hidden set structurally: every `role="tab"` in the sheet is now a visible,
   * measured control. The hook reads the media query before first paint, so the
   * correct bar is chosen on the first render instead of flashing the other.
   */
  const desktopTabs = useMediaQuery('(min-width: 1024px)');

  /**
   * THE PLAN ARRIVAL.
   *
   * `planKey` names the plan on screen; `planArrivedNow` is true only for the
   * commit in which a plan the sheet has NOT shown yet lands (the effect records
   * it immediately after). Sections that appear WITH an arrival use it to take an
   * idle slice instead of landing inside the arrival commit — see
   * report/ArrivalSlice.tsx. A tab visit or a reopened sheet renders them at
   * once: there is no arrival to smooth, and a placeholder there would be noise.
   */
  const planKey = floorPlanData
    ? String(floorPlanData.generation_id || floorPlanData.generated_at)
    : null;
  // The plan key this sheet instance was MOUNTED with (state, not a ref: it is
  // read during render and never written). Anything else that turns up on this
  // instance is an arrival; a plan the sheet is simply opened onto is not.
  const [planKeyAtMount] = useState<string | null>(planKey);
  const planArrivedNow = planKey !== null && planKey !== planKeyAtMount;

  /**
   * Disclosure: the banner must read the SAME proportion/programme evidence the
   * PDF prints. Site-analysis warnings alone left every PROP-* line visible
   * only inside the generator card, so the report's loudest surface never
   * switched to the FAIL treatment after a plan was drawn.
   */
  const bannerData = React.useMemo(() => {
    const warnings = bannerWarnings(analysisData, floorPlanData);
    if (warnings.length === (analysisData.warnings ?? []).length) return analysisData;
    return { ...analysisData, warnings };
  }, [analysisData, floorPlanData]);

  /**
   * The sheet covers ~96 % of the viewport, map included. Holding the render
   * gate for as long as it is open means MapLibre stops drawing behind it —
   * frames the user cannot see were landing inside every other interaction's
   * long task. Released on close, where the map is resized and repainted once so
   * it is current on the first frame after the sheet disappears.
   */
  useEffect(() => {
    if (!isOpen) return;
    holdMapRender('report-sheet');
    return () => {
      // Resuming INSIDE the unmount commit would put the map's resize and its
      // first repaint in the same task that tears the sheet down — the exact
      // interleaving this gate exists to remove, now on the close path. The
      // commit hold outlives the teardown by two frames; the map is current on
      // the frame after that (resize + triggerRepaint happen on release).
      holdMapRenderAcrossCommit('sheet-close');
      releaseMapRender('report-sheet');
    };
  }, [isOpen]);

  /**
   * The active tab is split in two:
   *   - `activeTab` (immediate) drives the CHROME — tab buttons, sub-header,
   *     unit switch, section tray. It is the discrete event's own work, so the
   *     highlight and the sliding pill land in the click frame.
   *   - `panelTab` (deferred) drives the PANEL — mounting a tab's card stack is
   *     the expensive half, so React renders it as an interruptible transition
   *     instead of inside the click handler.
   * The reader sees the pill move instantly and the content follow within a
   * frame or two; no single task spans both halves.
   */
  const panelTab = React.useDeferredValue(activeTab);

  // Entrance staggers, decided once per mount: a tab switch remounts this pane,
  // and replaying eight staggered card animations (plus their layout work) on
  // every visit is the switch cost the reader feels but never asks for. Decided
  // here rather than per wrapper so the keys are greppable in one place.
  const [staggerOverview] = useState(() => staggerClassFor('report.stagger.overview'));
  const [staggerHazards] = useState(() => staggerClassFor('report.stagger.hazards'));
  const [staggerEcology] = useState(() => staggerClassFor('report.stagger.ecology'));
  const [staggerCostPlan] = useState(() => staggerClassFor('report.stagger.cost_plan'));

  /**
   * Both Print buttons go through here (the sheet's own Print, and the footer
   * CTA). `beforeprint` would mount the tree anyway, but mounting it BEFORE
   * `window.print()` means the dialog never opens on a partially committed
   * document, and the buttons stay correct in browsers that omit `beforeprint`.
   */
  const handlePrint = useCallback(() => {
    engagePrintMode();
    window.print();
  }, [engagePrintMode]);

  // Copy Reference ID
  const handleCopyRef = () => {
    navigator.clipboard.writeText(analysisData.request_id);
    setCopiedRef(true);
    setTimeout(() => setCopiedRef(false), 1500);
  };

  // Persist the outgoing tab's scroll offset, then switch.
  const handleTabChange = useCallback(
    (tab: ResultsTab) => {
      const el = contentScrollRef.current;
      if (el) {
        try {
          sessionStorage.setItem(scrollKeyFor(activeTab), String(el.scrollTop));
        } catch {
          /* storage unavailable — position is not remembered this session */
        }
      }
      onTabChange(tab);
    },
    [onTabChange, activeTab]
  );

  // Remember the active tab's scroll offset as the user scrolls it.
  //
  // The write is debounced to idle rather than issued per frame: sessionStorage
  // is synchronous I/O and a write per scroll frame measured 67 ms of self time
  // across one 5 s scroll, all of it on the main thread. The position is flushed
  // on the ways it can actually be lost — scroll idle, the page being hidden and
  // the pane/tab going away — so it is still there on the next visit.
  useEffect(() => {
    const el = contentScrollRef.current;
    if (!el || !isOpen) return;
    let raf = 0;
    let writeTimer = 0;
    let lastWrite = 0;
    const persist = (force = false) => {
      const now = performance.now();
      if (!force && now - lastWrite < WRITE_INTERVAL_MS) return;
      lastWrite = now;
      try {
        sessionStorage.setItem(scrollKeyFor(activeTab), String(el.scrollTop));
      } catch {
        /* storage unavailable — position is not remembered this session */
      }
    };
    /**
     * At most ONE pending trailing write, created at most once per interval.
     *
     * Two failure modes have to be avoided at once: a write per scroll frame
     * (67 ms of self time for the storage call alone), and a timer armed and
     * cleared per frame (83 ms). Writes are also rate-limited inside `persist`
     * because the coalescing signal is not always rare — a programmatic scroll
     * emits `scrollend` for every step, which stormed 261 storage writes through
     * this pane. Both the rate limit and the single pending timer keep the cost
     * flat however chatty the engine is, and the trailing write still lands
     * within one interval of the last movement.
     */
    const schedulePersist = () => {
      if (writeTimer) return;
      const wait = Math.max(0, WRITE_INTERVAL_MS - (performance.now() - lastWrite));
      writeTimer = window.setTimeout(() => {
        writeTimer = 0;
        persist();
      }, wait);
    };
    const onScroll = () => {
      // Cheap UI state (drives the "Top" pill) still needs to be current.
      if (!raf) {
        raf = requestAnimationFrame(() => {
          raf = 0;
          setPaneScrolled(el.scrollTop > 120);
        });
      }
      schedulePersist();
    };
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') persist(true);
    };
    const hasScrollEnd = 'onscrollend' in el || 'onscrollend' in window;
    el.addEventListener('scroll', onScroll, { passive: true });
    if (hasScrollEnd) el.addEventListener('scrollend', schedulePersist);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      el.removeEventListener('scroll', onScroll);
      if (hasScrollEnd) el.removeEventListener('scrollend', schedulePersist);
      document.removeEventListener('visibilitychange', onVisibility);
      if (raf) cancelAnimationFrame(raf);
      if (writeTimer) clearTimeout(writeTimer);
      // The pane can disappear before any of the above fires (tab switch, close).
      persist(true);
    };
  }, [isOpen, activeTab]);

  // Restore the incoming tab's remembered scroll offset (0 when none saved).
  //
  // Keyed on the DEFERRED tab, not the immediate one: the pane's content only
  // becomes the incoming tab when the transition lands, and applying an offset
  // before that measures it against the OUTGOING content's height — which clamps
  // it whenever the incoming tab is shorter (returning to a tab you had scrolled
  // to the bottom of landed mid-page). One frame later the height is the real one.
  useEffect(() => {
    const el = contentScrollRef.current;
    if (!el || !isOpen) return;
    let target = 0;
    try {
      target = Number(sessionStorage.getItem(scrollKeyFor(panelTab)) ?? '0') || 0;
    } catch {
      target = 0;
    }
    el.scrollTop = target;
  }, [isOpen, panelTab]);

  // Smooth anchor scrolling that clears the sticky chrome (sections carry
  // scroll-margin-top). Reduced motion is honoured by the global CSS rule
  // (scroll-behavior: auto), so a plain scrollIntoView is correct here.
  const handleSectionNavigate = useCallback((sectionId: string) => {
    const target = document.getElementById(`sec-${sectionId}`);
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, []);

  // The section nav's "Top" action returns to the start of the active tab.
  // Reduced motion is honoured by the global scroll-behavior rule.
  const handleBackToTop = useCallback(() => {
    contentScrollRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
  }, []);

  // Number-key tab switching (1-4); ignored while typing in form fields
  useEffect(() => {
    if (!isOpen) return;
    const handleTabKeys = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.tagName === 'SELECT' ||
          target.isContentEditable)
      ) {
        return;
      }
      const idx = ['1', '2', '3', '4'].indexOf(e.key);
      if (idx >= 0 && TABS[idx]) {
        e.preventDefault();
        handleTabChange(TABS[idx].id);
      }
    };
    window.addEventListener('keydown', handleTabKeys);
    return () => window.removeEventListener('keydown', handleTabKeys);
  }, [isOpen, handleTabChange]);

  /**
   * Which anchored section is the reader on? Measured from geometry, not from
   * IntersectionObserver entry order: on Cost & Plan the Land Value card and
   * the Blueprint card sit side by side, so two sections can share the top of
   * the reading band, and "first entry wins" highlighted whichever one the
   * observer reported first (Land Value, while the blueprint filled the pane).
   *
   * The rule is deterministic: the section with the largest overlap of the
   * reading band (the top 15–30% of the pane) wins; failing that, the section
   * the reader most recently scrolled past; failing that, the first one. The
   * tray therefore always has exactly one highlighted pill — never none.
   *
   * At the very bottom of the pane the LAST section wins outright: the Cost &
   * Plan tab lays the land-value card and the blueprint card out side by side,
   * so near the end both overlap the band equally and "largest overlap" would
   * fall back to DOM order — highlighting Land Value while the blueprint filled
   * the screen. At the end of the scroll the last section is the honest answer.
   */
  /**
   * Section geometry, measured ONCE per layout change and reused per frame.
   *
   * The rule above needs every section's box, but re-deriving it per scroll
   * frame cost a `querySelectorAll` per frame (~200 ms of self time across one
   * 5 s scroll) plus a `getBoundingClientRect` per section (~45 ms) — the single
   * largest cost of the scroll path. Boxes are cached relative to the pane, so a
   * frame only needs `scrollTop` plus these numbers: no DOM query, no layout
   * read, no forced flush.
   */
  const sectionBoxesRef = useRef<{ id: string; top: number; height: number }[]>([]);

  const measureSectionBoxes = useCallback(() => {
    const root = contentScrollRef.current;
    if (!root) return;
    const boxes: { id: string; top: number; height: number }[] = [];
    for (const el of root.querySelectorAll<HTMLElement>('[data-report-section]')) {
      const id = el.getAttribute('data-report-section');
      if (!id) continue;
      // `offsetTop` is relative to the nearest positioned ancestor, and several
      // wrappers sit between a section and the pane, so accumulate up to the pane.
      let top = 0;
      let node: HTMLElement | null = el;
      while (node && node !== root) {
        top += node.offsetTop;
        node = node.offsetParent as HTMLElement | null;
      }
      if (node === root) boxes.push({ id, top, height: el.offsetHeight });
    }
    sectionBoxesRef.current = boxes;
  }, []);

  const refreshActiveSection = useCallback(() => {
    const root = contentScrollRef.current;
    if (!root) return;
    const sections = sectionBoxesRef.current;
    if (sections.length === 0) return;
    const viewHeight = root.clientHeight;
    const bandTop = viewHeight * 0.15;
    const bandBottom = viewHeight * 0.3;
    const scrollTop = root.scrollTop;
    let best = '';
    let bestOverlap = 0;
    let passed = '';
    let first = '';
    let last = '';
    for (const s of sections) {
      if (!first) first = s.id;
      last = s.id;
      const top = s.top - scrollTop;
      const bottom = top + s.height;
      if (top <= bandTop) passed = s.id;
      const overlap = Math.min(bottom, bandBottom) - Math.max(top, bandTop);
      if (overlap > bestOverlap) {
        bestOverlap = overlap;
        best = s.id;
      }
    }
    const atEnd = scrollTop + viewHeight >= root.scrollHeight - 4;
    setActiveSection((atEnd && last) || best || passed || first);
  }, []);

  /**
   * The nav's link list for the active tab, minus any link whose section did
   * not render: the Certificate only exists once a blueprint has a QA panel, so
   * before that the tray has no pill pointing at nothing. Declared with the
   * other hooks — above the `!isOpen` early return, where a hook is illegal.
   */
  // Land economics rides on the same response as the blueprint: no plan, no
  // certificate, so the tray link is withheld until the certificate exists.
  const landEconomics =
    floorPlanData?.land_economics ?? floorPlanData?.multi_storey?.land_economics ?? null;
  const sectionLinks = useMemo(() => {
    const links = TAB_SECTION_LINKS[activeTab] ?? [];
    return links.filter((link) => {
      if (link.id === 'certificate') return Boolean(floorPlanData?.qa);
      if (link.id === 'land') return Boolean(landEconomics);
      return true;
    });
    // Keyed on the IMMEDIATE tab: the tray is chrome, so it must describe the tab
    // the pill just moved to, not the one the pane is still showing.
  }, [activeTab, floorPlanData?.qa, landEconomics]);

  // Initial read for the tab that is about to paint (a layout effect, so the
  // first frame already highlights the right pill instead of flashing an
  // unhighlighted tray).
  useLayoutEffect(() => {
    if (!isOpen) return;
    measureSectionBoxes();
    refreshActiveSection();
  }, [isOpen, activeTab, measureSectionBoxes, refreshActiveSection]);

  // Keep it honest while the pane scrolls and while sections mount or unmount
  // under it (the Certificate appears with a generated blueprint). Both
  // watchers are only change signals — the geometry above decides the answer.
  useEffect(() => {
    if (!isOpen) return;
    const root = contentScrollRef.current;
    if (!root) return;
    let raf = 0;
    const schedule = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        refreshActiveSection();
      });
    };
    let measureRaf = 0;
    /** Re-measure then repaint the highlight, always a frame later. */
    const remeasure = () => {
      if (measureRaf) return;
      measureRaf = requestAnimationFrame(() => {
        measureRaf = 0;
        measureSectionBoxes();
        refreshActiveSection();
      });
    };
    // A scroll frame decides from cached geometry only — no query, no read.
    root.addEventListener('scroll', schedule, { passive: true });
    // The observer is a CHANGE SIGNAL, not the decision (a section mounting,
    // unmounting or entering the padded band): its callback re-measures, because
    // that is the only time the cached boxes can go stale.
    const observer =
      typeof IntersectionObserver === 'undefined'
        ? null
        : new IntersectionObserver(remeasure, { root, rootMargin: '15% 0px -30% 0px', threshold: 0 });
    const watch = () => {
      measureSectionBoxes();
      root.querySelectorAll('[data-report-section]').forEach((s) => observer?.observe(s));
    };
    watch();
    // Mutations are batched into a frame: a MutationObserver callback is a
    // microtask, so measuring inside it would extend the very task that caused
    // the mutation (the tab-switch click handler).
    const mutations =
      typeof MutationObserver === 'undefined'
        ? null
        : new MutationObserver(() => {
            remeasure();
          });
    mutations?.observe(root, { childList: true, subtree: true });
    // The reading band is a fraction of the pane, so its own resize matters.
    window.addEventListener('resize', remeasure);
    return () => {
      root.removeEventListener('scroll', schedule);
      window.removeEventListener('resize', remeasure);
      if (measureRaf) cancelAnimationFrame(measureRaf);
      observer?.disconnect();
      mutations?.disconnect();
      if (raf) cancelAnimationFrame(raf);
    };
  }, [isOpen, panelTab, refreshActiveSection, measureSectionBoxes]);

  // Body scroll lock and focus trap while open
  useEffect(() => {
    if (!isOpen) return;

    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    // Focus first focusable element inside the sheet
    const focusTimer = setTimeout(() => {
      if (sheetRef.current) {
        const focusable = sheetRef.current.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        if (focusable.length > 0) {
          focusable[0].focus();
        }
      }
    }, 50);

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
        return;
      }

      if (e.key === 'Tab' && sheetRef.current) {
        const focusable = Array.from(
          sheetRef.current.querySelectorAll<HTMLElement>(
            'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
          )
        ).filter((el) => el.offsetParent !== null);

        if (focusable.length === 0) return;

        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (e.shiftKey) {
          if (document.activeElement === first) {
            e.preventDefault();
            last.focus();
          }
        } else {
          if (document.activeElement === last) {
            e.preventDefault();
            first.focus();
          }
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);

    return () => {
      document.body.style.overflow = originalOverflow;
      window.removeEventListener('keydown', handleKeyDown);
      clearTimeout(focusTimer);
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  // INR Formatting Helper (compact above a lakh; the exact-rupee branch uses the
  // shared cached currency formatter — this used to build a new Intl.NumberFormat
  // per call, which the profile charged 42 ms of self time for on one scroll.)
  const formatInr = (val: number) => {
    if (val >= 10000000) {
      return `₹${(val / 10000000).toFixed(2)} Cr`;
    } else if (val >= 100000) {
      return `₹${(val / 100000).toFixed(2)} Lakh`;
    }
    return formatINR(val);
  };

  /** Degradation notices drive the Hazards tab badge and the context strip. */
  const warningCount = analysisData.warnings?.length ?? 0;

  // Land value and combined calculations
  const effectiveLandRate =
    overrideLandRate !== null
      ? overrideLandRate
      : analysisData.land_value?.indicative_rate_per_sqft ?? null;

  const currentPlotArea =
    overridePlotArea !== null
      ? overridePlotArea
      : analysisData.land_value?.plot_area_sqft ?? 0;

  const currentLandCost =
    effectiveLandRate !== null && effectiveLandRate > 0 && currentPlotArea > 0
      ? Math.round(effectiveLandRate * currentPlotArea)
      : analysisData.land_value?.land_cost_inr ?? null;

  const currentCombinedTotal =
    currentLandCost !== null
      ? analysisData.cost_estimate.total_estimated_cost_inr + currentLandCost
      : null;

  return (
    <>
      {/* Behind it: rgba(0,0,0,0.20) scrim over the map */}
      <div
        className="report-sheet-scrim fixed inset-0 bg-black/20 z-[1999] transition-opacity cursor-pointer pointer-events-auto"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Surface: fixed inset-3 on desktop, inset-0 below 1024px; radius 24 (0 on mobile) */}
      <div
        ref={sheetRef}
        role="dialog"
        aria-modal="true"
        aria-label="Site Feasibility Report"
        className="fixed inset-3 max-lg:inset-0 rounded-[24px] max-lg:rounded-none z-[2000] report-sheet-surface border border-[var(--panel-border-color)] shadow-2xl flex flex-col overflow-hidden animate-sheet-open pointer-events-auto"
        style={{
          backgroundColor: 'var(--sheet-bg)',
          backdropFilter: 'blur(40px) saturate(180%)',
          WebkitBackdropFilter: 'blur(40px) saturate(180%)',
        }}
      >
        {/* Sticky Sheet Header (56px) */}
        <header className="h-[56px] min-h-[56px] border-b border-[var(--hairline)] px-3 sm:px-6 flex items-center justify-between gap-2 sm:gap-3 shrink-0 select-none bg-[var(--sheet-bg)]">
          {/* Left: Shield Icon + "Site Feasibility Report" 15px/600 + Ref Copy Pill */}
          <div className="flex items-center gap-2 sm:gap-2.5 min-w-0">
            <div className="w-7 h-7 rounded-[8px] bg-[var(--accent-tint)] text-[var(--accent-ink)] flex items-center justify-center shrink-0">
              <Icon name="shield" size={16} />
            </div>
            <h1 className="text-[14px] sm:text-[15px] font-semibold text-[var(--text-1)] tracking-tight truncate">
              <span className="hidden xs:inline">Site Feasibility </span>Report
            </h1>
            <button
              type="button"
              onClick={handleCopyRef}
              className="hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[var(--fill)] hover:bg-[var(--fill-hover)] text-[12px] font-mono text-[var(--text-2)] hover:text-[var(--text-1)] transition-colors cursor-pointer select-none shrink-0"
              title="Click to copy analysis reference ID"
            >
              <Icon
                name={copiedRef ? 'check' : 'copy'}
                size={12}
                className={copiedRef ? 'text-[var(--semantic-green-ink)]' : 'text-[var(--text-3)]'}
              />
              <span>{copiedRef ? 'Copied' : `Ref: ${analysisData.request_id.slice(0, 8)}`}</span>
            </button>
          </div>

          {/* Center: Desktop Segmented Tab Bar (mounted only at >=1024px; below
              that the compact strip is the one live tab set) */}
          {desktopTabs && (
          <div className="report-sheet-tabs-nav flex items-center justify-center flex-1 max-w-md mx-auto">
            <SegmentedControl
              role="tablist"
              ariaLabel="Report sections"
              panelId="report-tabpanel"
              optionIdPrefix="report-tab"
              value={activeTab}
              onChange={handleTabChange}
              stretch
              indicator
              className="w-full"
              options={TABS.map((tab, idx) => ({
                id: tab.id,
                label: tab.label,
                icon: <Icon name={tab.icon} size={12} className="shrink-0" />,
                badge: tab.id === 'hazards' && warningCount > 0 ? warningCount : undefined,
                title:
                  tab.id === 'hazards' && warningCount > 0
                    ? `${tab.label} — ${warningCount} degradation notice${warningCount === 1 ? '' : 's'} (press ${idx + 1})`
                    : `${tab.label} (press ${idx + 1})`,
              }))}
            />
          </div>
          )}

          {/* Right: unit switch, Download PDF (primary), Print, Close. The
              scroll-spy caption that used to sit here is gone: the section nav
              in the sub-header is the read-out now, and this one had no label
              for three Cost & Plan sections, so it rendered as an empty pill
              from the cost breakdown down to the end of the report. */}
          <div className="report-sheet-header-actions flex items-center gap-1.5 sm:gap-2 shrink-0">
            {/* Metric/imperial switch, applied report-wide */}
            <span className="hidden sm:inline-flex">
              <UnitToggle
                disabled={activeTab === 'cost_plan'}
                disabledReason="CPWD cost rates are quoted per square foot, so the unit preference does not apply on this tab."
              />
            </span>

            {/* Download PDF button (primary) */}
            <DownloadReportButton payload={reportPayload} variant="compact" />

            {/* Print button (secondary) */}
            <button
              type="button"
              onClick={handlePrint}
              className="hidden sm:flex h-8 px-3 rounded-[10px] bg-[var(--fill)] hover:bg-[var(--fill-hover)] text-[var(--text-1)] text-[12px] font-medium items-center gap-1.5 transition-colors cursor-pointer select-none"
              title="Print comprehensive report"
            >
              <Icon name="printer" size={14} />
              <span>Print</span>
            </button>

            {/* Close button (32px --fill circle) */}
            <button
              type="button"
              onClick={onClose}
              className="report-sheet-close-btn w-8 h-8 rounded-full bg-[var(--fill)] hover:bg-[var(--fill-hover)] text-[var(--text-2)] hover:text-[var(--text-1)] flex items-center justify-center transition-colors cursor-pointer shrink-0"
              aria-label="Close report sheet"
              title="Close (Esc)"
            >
              <Icon name="x" size={16} />
            </button>
          </div>
        </header>

        {/* Sub-header: the contextual read-out plus the in-tab section nav, in
            one row of one height on EVERY tab. The nav is chrome here rather
            than a sticky strip inside the pane: a per-tab strip moved the whole
            tab body by its own height whenever a switch landed on a tab without
            anchors, so the anchor-less tabs had to carry an invisible strip
            that ate pane space and frosted the content scrolling under it. */}
        <div className="print-hide flex items-center gap-x-3 px-3 sm:px-6 py-1 min-h-[38px] border-b border-[var(--hairline)] bg-[var(--sheet-bg)] shrink-0">
          {/* The read-out gets a FIXED box, not a content-sized one: it was the
              only measured layout shift in this row (0.00034 at the widest
              switch) because every element after a content-sized box — the
              section tray, and the tray's own left edge — moved with it as the
              line changed between tabs. 420px holds the longest line the report
              can publish; the 45% cap keeps it honest on a narrow pane. */}
          <div className="w-[420px] max-w-[45%] shrink-0">
            <TabContextBar
              tab={activeTab}
              data={analysisData}
              siteVision={siteVisionData}
              qualityGrade={analysisRequest?.quality_grade}
            />
          </div>
          <SectionNav
            sections={sectionLinks}
            activeSection={activeSection}
            onNavigate={handleSectionNavigate}
          />
          {/* Row-level, pinned to the row's right edge, and only while the pane
              is scrolled: nothing else in the row is sized or placed by it, so
              appearing cannot shift the read-out or the tray. Available on
              every tab — Ecology alone is 614px of scroll. */}
          {paneScrolled && (
            <button
              type="button"
              onClick={handleBackToTop}
              /* --text-2, not --text-3: measured 3.76:1 in the dark sheet at
                 11.5px (below AA); --text-2 clears it at 4.96:1 dark / 4.94:1 light. */
              className="print-hide ml-auto shrink-0 inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full text-[11.5px] font-medium text-[var(--text-2)] hover:text-[var(--text-1)] hover:bg-[var(--fill)] transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/40"
              title="Scroll back to the top of this tab"
            >
              <Icon name="arrow-up" size={13} className="shrink-0" />
              <span className="hidden sm:inline">Top</span>
            </button>
          )}
        </div>

        {/* Compact Horizontal Sub-Header Tabs (<1024px; mounted only here) */}
        {!desktopTabs && (
        <div className="report-sheet-tabs-nav border-b border-[var(--hairline)] px-4 py-2 bg-[var(--sheet-bg)] bw-tab-strip bw-fade-x shrink-0">
          <div
            role="tablist"
            className="bg-[var(--fill)] rounded-[10px] p-[2px] flex items-center gap-1 min-w-max text-[12px] font-medium"
          >
            {TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={activeTab === tab.id}
                aria-controls="report-tabpanel"
                onClick={() => handleTabChange(tab.id)}
                className={`inline-flex items-center gap-1.5 py-1.5 px-3 rounded-[8px] text-[12px] transition-[transform,opacity,background-color,border-color,color,box-shadow] duration-200 ease-apple whitespace-nowrap cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/40 ${
                  activeTab === tab.id
                    ? 'bg-[var(--segmented-active-bg)] text-[var(--segmented-active-label)] font-semibold bw-segmented-active-shadow'
                    : 'text-[var(--text-2)] hover:text-[var(--text-1)]'
                }`}
              >
                <Icon name={tab.icon} size={12} className="shrink-0" />
                {tab.label}
                {tab.id === 'hazards' && warningCount > 0 && (
                  <span
                    className={`inline-flex items-center justify-center min-w-[1.1rem] h-[1.1rem] px-1 rounded-full text-[10px] font-bold ui-font-tabular shrink-0 ${
                      activeTab === tab.id ? 'bg-[var(--accent)] text-white' : 'bg-[var(--accent-tint)] text-[var(--accent-ink)]'
                    }`}
                    title={`${warningCount} degradation notice${warningCount === 1 ? '' : 's'}`}
                  >
                    {warningCount}
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>
        )}

        {/* Content Area: overflow-y auto with scrollbar-apple, padding 24px, inner max-width 1160px centered */}
        <main
          ref={contentScrollRef}
          className="report-sheet-content flex-1 overflow-y-auto bw-scroll-pane scrollbar-apple p-4 sm:p-6"
        >
          <div className="max-w-[1400px] mx-auto w-full min-w-0 space-y-4">
            {/* ================================================================= */}
            {/* SCREEN VIEW: Render selected tab only                             */}
            {/* ================================================================= */}
            <div
              id="report-tabpanel"
              role="tabpanel"
              aria-labelledby={`report-tab-${activeTab}`}
              className="report-screen-only animate-tab-switch"
            >
              {/* TAB 1: OVERVIEW */}
              {panelTab === 'overview' && (
                <div className={`space-y-4 ${staggerOverview}`}>
                  <h2 className="text-[17px] font-bold text-[var(--text-1)] tracking-tight">
                    Site Overview
                  </h2>

                  {/* Degradation warnings: persistent banner, report top */}
                  <WarningsBanner data={bannerData} planVerdict={floorPlanData?.plan_verdict ?? null} />

                  {/* Hero summary: score, identity chips, headline tiles, data health */}
                  <section data-report-section="summary" id="sec-summary" aria-label="Summary">
                    <ReportHeroHeader data={analysisData} />
                  </section>

                  {/* b) BELOW: grid 7fr / 5fr, gap 16: left = Multi-Criteria Factor Breakdown; right = Engineering Commentary & Action Items */}
                  <div className="grid grid-cols-1 lg:grid-cols-[7fr_5fr] gap-4 items-start">
                    {/* Left Column (7fr): Multi-Criteria Factor Breakdown card */}
                    <div className="w-full min-w-0" data-report-section="factors" id="sec-factors">
                      <CollapsibleSection
                        sectionId="overview-factors"
                        title="Factor Assessment"
                        icon="layers"
                        meta={
                          <span className="text-[11px] text-[var(--text-3)] tabular-nums">
                            {analysisData.factors.length} weighted
                          </span>
                        }
                      >
                        {analysisData.factors.length > 0 ? (
                          <MemoizedFactorList factors={analysisData.factors} dataSources={analysisData.data_sources} methodology={analysisData.methodology} />
                        ) : (
                          <ReportEmptyState
                            icon="layers"
                            title="No factor scores available"
                            message="The suitability engine returned no weighted factors for this site. Re-run the analysis to score the terrain, hazard and access inputs."
                          />
                        )}
                      </CollapsibleSection>
                    </div>

                    {/* Right Column (5fr): Engineering Commentary & Action Items card (sticky filter control) */}
                    <div className="w-full min-w-0" data-report-section="commentary" id="sec-commentary">
                      <RecommendationPanel
                        summary={analysisData.engineering_summary}
                        recommendations={analysisData.detailed_recommendations}
                        recommendationItems={analysisData.recommendation_items}
                        aiMetadata={analysisData.ai_metadata}
                        parameterReflection={analysisData.parameter_reflection}
                        summaryOnly={false}
                      />
                    </div>
                  </div>

                  {/* c) BELOW: full-width export / download strip */}
                  <div className="rounded-[14px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)] p-3.5 px-4 flex flex-col sm:flex-row items-center justify-between gap-3 text-[12px] text-[var(--text-2)]">
                    <div className="flex items-center gap-2 min-w-0">
                      <Icon name="file-text" size={16} className="text-[var(--text-2)] shrink-0" />
                      <span className="truncate">
                        Site feasibility dossier ready • Ref ID:{' '}
                        <span className="font-mono text-[var(--text-1)]">{analysisData.request_id}</span>
                      </span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <DownloadReportButton payload={reportPayload} variant="compact" />
                      <button
                        type="button"
                        onClick={handlePrint}
                        className="h-8 px-3 rounded-[10px] bg-[var(--fill)] hover:bg-[var(--fill-hover)] text-[var(--text-1)] text-[12px] font-medium flex items-center gap-1.5 transition-colors cursor-pointer select-none"
                      >
                        <Icon name="printer" size={14} />
                        <span>Print Report</span>
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* TAB 2: HAZARDS */}
              {panelTab === 'hazards' && (
                <div className={`space-y-4 ${staggerHazards}`}>
                  <h2 className="text-[17px] font-bold text-[var(--text-1)] tracking-tight">
                    Hazards &amp; Resilience
                  </h2>

                  {/* Degradation warnings: same banner the Overview tab renders */}
                  <WarningsBanner data={bannerData} planVerdict={floorPlanData?.plan_verdict ?? null} />

                  {/* 3-col grid with Seismic / Hydrological / Storm side by side */}
                  <section data-report-section="profiles" aria-label="Hazard profiles">
                    <div className="flex items-center justify-between mb-2">
                      <h2 className="text-[14px] font-semibold text-[var(--text-1)] tracking-tight flex items-center gap-2">
                        <Icon name="activity" size={14} className="text-[var(--text-2)]" />
                        Seismic classification
                      </h2>
                      {analysisData.hazard_profile && (
                        <SeismicZoneChip seismic={analysisData.hazard_profile.seismic} />
                      )}
                    </div>
                    {analysisData.hazard_profile ? (
                      <HazardProfileCard hazard={analysisData.hazard_profile} layout="grid" />
                    ) : (
                      <ReportEmptyState
                        icon="activity"
                        title="Hazard profile unavailable"
                        message="Seismic, flood and storm telemetry did not return for this site. The risk register below is still complete; re-run the analysis to retry the hazard services."
                      />
                    )}
                  </section>

                  {/* Below: Full-width Risk Mitigation Matrix */}
                  <section data-report-section="risks" aria-label="Risk mitigation">
                    <CollapsibleSection
                      sectionId="hazards-risks"
                      title="Risk Register"
                      icon="shield-alert"
                      meta={
                        <span className="text-[11px] text-[var(--text-3)] tabular-nums">
                          {analysisData.risks.length} identified
                        </span>
                      }
                    >
                      <RiskMatrix risks={analysisData.risks} />
                    </CollapsibleSection>
                  </section>

                  {/* Consolidated Data Sources & Standards */}
                  <DataSourcesDisclosure category="hazards" degraded={analysisData.degraded_mode || (analysisData.warnings?.length ?? 0) > 0} />
                </div>
              )}

              {/* TAB 3: ECOLOGY */}
              {panelTab === 'ecology' && (
                <div className={`space-y-4 ${staggerEcology}`}>
                  <h2 className="text-[17px] font-bold text-[var(--text-1)] tracking-tight">
                    Ecology &amp; Orientation
                  </h2>

                  {/* 2-col grid SiteVisionCard + tree preservation list */}
                  <section data-report-section="vision" aria-label="Site vision">
                    <SiteVisionCard
                      data={siteVisionData}
                      isLoading={isSiteVisionLoading}
                      onScan={onRunSiteVision}
                      hasCoordinates={hasLocation}
                      layout="grid"
                    />
                  </section>

                  {/* Below: 2-col grid OrientationCompass + VastuAdvisoryCard side by side */}
                  <section data-report-section="orientation" aria-label="Orientation and vastu">
                    <div className="rounded-[14px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)] p-4 mb-4">
                      <h2 className="text-[14px] font-semibold text-[var(--text-1)] tracking-tight mb-3">
                        Bioclimatic orientation
                      </h2>
                      <WindRose orientation={analysisData.orientation} />
                    </div>
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
                      <OrientationCompass orientation={analysisData.orientation} />

                      {analysisData.vastu_advisory ? (
                        <VastuAdvisoryCard advisory={analysisData.vastu_advisory} />
                      ) : (
                        <ReportEmptyState
                          icon="layout-grid"
                          title="Vastu advisory unavailable"
                          message="The orientation advisory did not return for this site, so no entrance ranking or zone grid is shown. The passive-solar compass on the left is unaffected."
                        />
                      )}
                    </div>
                  </section>

                  {/* Consolidated Data Sources & Standards */}
                  <DataSourcesDisclosure category="ecology" degraded={analysisData.degraded_mode || (analysisData.warnings?.length ?? 0) > 0} />

                  {/* Full report provenance + status legend */}
                  <ProvenanceFooter data={analysisData} />
                </div>
              )}

              {/* TAB 4: COST & PLAN */}
              {panelTab === 'cost_plan' && (
                <div className={`space-y-4 ${staggerCostPlan}`}>
                  <h2 className="text-[17px] font-bold text-[var(--text-1)] tracking-tight">
                    Cost &amp; Planning
                  </h2>

                  <section data-report-section="estimate" id="sec-estimate" aria-label="Headline cost estimate">
                  {/* Grade → cost: what the selected specification grade costs per sq ft,
                      with the delta against the other CPWD tiers. */}
                  {(() => {
                    const activeId = (analysisRequest?.quality_grade ?? 'standard').toLowerCase();
                    const activeRate = analysisData.cost_estimate.base_rate_per_sqft;
                    const activeTier = GRADE_RATES_INR_PER_SQFT.find((g) => g.id === activeId);
                    const premiumDelta = activeRate - (GRADE_RATES_INR_PER_SQFT.find((g) => g.id === 'premium')?.rate ?? activeRate);
                    const basicDelta = activeRate - (GRADE_RATES_INR_PER_SQFT.find((g) => g.id === 'basic')?.rate ?? activeRate);
                    const fmtDelta = (v: number) => `${v >= 0 ? '+' : '−'}₹${formatIN(Math.abs(v))}`;
                    return (
                      <div className="bw-card rounded-[14px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)] p-3.5 mb-3.5 space-y-2">
                        <div className="flex items-center justify-between gap-2 min-w-0">
                          <span className="text-[12px] font-semibold text-[var(--text-1)]">Specification grade → cost</span>
                          <span className="inline-flex items-center gap-1 min-w-0">
                            <span
                              className="text-[11px] text-[var(--text-3)] truncate"
                              title={analysisData.cost_estimate.disclaimer}
                            >
                              CPWD plinth-area rates (₹/sq ft)
                            </span>
                            {CPWD_DISCLOSURE}
                          </span>
                        </div>
                        <div className="flex flex-wrap items-center gap-1.5">
                          {GRADE_RATES_INR_PER_SQFT.map((g) => {
                            const isActive = g.id === activeId;
                            return (
                              <span
                                key={g.id}
                                title={isActive ? 'Active specification grade for this analysis' : `CPWD rate for ${g.label} grade`}
                                className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold border ui-font-tabular ${
                                  isActive
                                    ? 'bg-[var(--accent-tint)] text-[var(--accent-ink)] border-[var(--accent)]/30'
                                    : 'bg-[var(--fill)] text-[var(--text-2)] border-[var(--hairline)]'
                                }`}
                              >
                                {g.label} @ ₹{formatIN(g.rate)}
                                {isActive && <span>• active</span>}
                              </span>
                            );
                          })}
                        </div>
                        <p className="text-[11px] text-[var(--text-2)] leading-snug">
                          {activeTier?.label ?? 'Selected'} grade applies ₹{formatIN(activeRate)}/sq ft
                          {premiumDelta !== 0 && ` (${fmtDelta(premiumDelta)} vs premium, ${fmtDelta(basicDelta)} vs basic)`}.
                        </p>
                      </div>
                    );
                  })()}

                  {/* Summary Tiles Row (4 tiles with room: label 12px, value 22px/600) */}
                  <div className="grid grid-cols-2 lg:grid-cols-4 gap-3.5">
                    <div className="bw-card bg-[var(--card-bg-subtle)] border border-[var(--hairline)] p-4 rounded-[14px] min-w-0">
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <span className="text-[12px] font-normal text-[var(--text-3)]">
                          Plinth area base rate
                        </span>
                        <CopyValueButton value={`₹${formatIN(analysisData.cost_estimate.base_rate_per_sqft)}/sq ft`} label="Plinth area base rate" />
                      </div>
                      <span className="text-[22px] font-semibold text-[var(--text-1)] tabular-nums block leading-tight">
                        <AnimatedNumber
                          playKey="report.cost.baseRate"
                          value={analysisData.cost_estimate.base_rate_per_sqft}
                          format={(n) => `₹${formatIN(Math.round(n))}/sq ft`}
                        />
                      </span>
                      <span
                        className="text-[12px] text-[var(--text-2)] block truncate mt-0.5"
                        title={analysisData.cost_estimate.disclaimer}
                      >
                        CPWD PAR baseline
                      </span>
                    </div>

                    <div className="bw-card bg-[var(--card-bg-subtle)] border border-[var(--hairline)] p-4 rounded-[14px] min-w-0">
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <span className="text-[12px] font-normal text-[var(--text-3)]">
                          Topographic modifier
                        </span>
                        <CopyValueButton value={`${analysisData.cost_estimate.terrain_multiplier.toFixed(2)}x`} label="Topographic modifier" />
                      </div>
                      <span className="text-[22px] font-semibold text-[var(--text-1)] tabular-nums block leading-tight">
                        <AnimatedNumber
                          playKey="report.cost.terrainMultiplier"
                          value={analysisData.cost_estimate.terrain_multiplier}
                          format={(n) => `${n.toFixed(2)}x`}
                        />
                      </span>
                      <span className="text-[12px] text-[var(--text-2)] block truncate mt-0.5">
                        {analysisData.cost_estimate.terrain_surcharge_inr > 0
                          ? `+${formatInr(analysisData.cost_estimate.terrain_surcharge_inr)} terrain surcharge`
                          : 'Baseline topography'}
                      </span>
                    </div>

                    <div className="bw-card bg-[var(--card-bg-subtle)] border border-[var(--hairline)] p-4 rounded-[14px] min-w-0">
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <span className="text-[12px] font-normal text-[var(--text-3)]">
                          Total civil budget
                        </span>
                        <CopyValueButton value={formatInr(analysisData.cost_estimate.total_estimated_cost_inr)} label="Total civil budget" />
                      </div>
                      <span className="text-[22px] font-semibold text-[var(--text-1)] tabular-nums block leading-tight">
                        <AnimatedNumber
                          playKey="report.cost.civilBudget"
                          value={analysisData.cost_estimate.total_estimated_cost_inr}
                          format={formatInr}
                        />
                      </span>
                      <span className="text-[12px] text-[var(--text-2)] block truncate mt-0.5">
                        Range: {formatInr(analysisData.cost_estimate.cost_range_min_inr)} –{' '}
                        {formatInr(analysisData.cost_estimate.cost_range_max_inr)}
                      </span>
                    </div>

                    <div className="bw-card bg-[var(--card-bg-subtle)] border border-[var(--hairline)] p-4 rounded-[14px] min-w-0">
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <span className="text-[12px] font-normal text-[var(--text-3)]">
                          Combined project total
                        </span>
                        <CopyValueButton
                          value={currentCombinedTotal !== null ? formatInr(currentCombinedTotal) : '—'}
                          label="Combined project total"
                        />
                      </div>
                      <span className="text-[22px] font-semibold text-[var(--text-1)] tabular-nums block leading-tight">
                        {currentCombinedTotal !== null ? (
                          <AnimatedNumber playKey="report.cost.combinedTotal" value={currentCombinedTotal} format={formatInr} />
                        ) : (
                          '—'
                        )}
                      </span>
                      <span className="text-[12px] text-[var(--text-2)] block truncate mt-0.5">
                        Civil structure + Land value
                      </span>
                    </div>
                  </div>
                  </section>

                  {/* Full-width Cost Breakdown Table */}
                  <section data-report-section="breakdown" id="sec-breakdown" aria-label="Cost breakdown">
                  <div className="bw-card rounded-[14px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)] p-4">
                    <h2 className="text-[14px] font-semibold text-[var(--text-1)] tracking-tight mb-3">
                      Cost spread &amp; composition
                    </h2>
                    <CostRangeBar cost={analysisData.cost_estimate} />
                  </div>
                  <CostBreakdownTable
                    costEstimate={analysisData.cost_estimate}
                    hideSummaryHeader={true}
                    citation={analysisData.cost_estimate.disclaimer}
                  />
                  </section>

                  {/* Below: Balanced LandValueCard + FloorPlanGeneratorCard (trailing card spans both columns if blueprint expanded) */}
                  <section aria-label="Valuation and floor plan">
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
                    {analysisData.land_value ? (
                      <div
                        className={`w-full min-w-0 ${floorPlanData ? 'lg:col-span-2' : ''}`}
                        data-report-section="landvalue"
                        id="sec-landvalue"
                      >
                        <LandValueCard
                          landValue={analysisData.land_value}
                          civilTotalCostInr={analysisData.cost_estimate.total_estimated_cost_inr}
                          onOverrideChange={onOverrideChange}
                        />
                      </div>
                    ) : (
                      <ReportEmptyState
                        icon="currency-rupee"
                        title="Land valuation unavailable"
                        message="No state guidance rate matched this jurisdiction, so no land budget is shown. The civil cost estimate above is unaffected and remains valid."
                      />
                    )}

                    {floorPlanData?.qa && (
                      <div
                        className={`w-full min-w-0 ${floorPlanData ? 'lg:col-span-2' : ''}`}
                        data-report-section="certificate"
                        id="sec-certificate"
                      >
                        {/* The panel renders nothing when the gate has no layers,
                            and a placeholder for nothing is a spinner that never
                            resolves. Slice only a section that is really coming. */}
                        {floorPlanData.qa.validation_gate?.layers?.length ? (
                          <ArrivalSlice
                            sliceId="report.certificate"
                            isArrival={planArrivedNow}
                            fallbackHeight={CERTIFICATE_FALLBACK_HEIGHT}
                            label="Validation gate certificate"
                          >
                            <CertificatePanel qa={floorPlanData.qa} variant="sheet" />
                          </ArrivalSlice>
                        ) : null}
                      </div>
                    )}

                    {landEconomics && (
                      <div
                        className="w-full min-w-0 lg:col-span-2"
                        data-report-section="land"
                        id="sec-land"
                      >
                        <LandEconomicsPanel report={landEconomics} />
                      </div>
                    )}

                    <div
                      className={`w-full min-w-0 ${floorPlanData ? 'lg:col-span-2' : ''}`}
                      data-report-section="blueprint"
                      id="sec-blueprint"
                    >
                      <FloorPlanGeneratorCard
                        defaultWidthM={
                          analysisData.land_value?.plot_area_sqft
                            ? Math.max(
                                6.0,
                                Math.min(
                                  60.0,
                                  +Math.sqrt(
                                    (analysisData.land_value.plot_area_sqft * 0.092903) / 1.2
                                  ).toFixed(1)
                                )
                              )
                            : 10.0
                        }
                        defaultDepthM={
                          analysisData.land_value?.plot_area_sqft
                            ? Math.max(
                                6.0,
                                Math.min(
                                  60.0,
                                  +(
                                    Math.sqrt(
                                      (analysisData.land_value.plot_area_sqft * 0.092903) / 1.2
                                    ) * 1.2
                                  ).toFixed(1)
                                )
                              )
                            : 12.0
                        }
                        activeFloorPlan={floorPlanData}
                        onFloorPlanGenerated={onFloorPlanGenerated}
                        onRequestPatch={onRequestPatch}
                        analysisRequest={analysisRequest}
                        sharedBoundary={sharedBoundary}
                        buildingTypology={analysisRequest?.building_typology}
                        qualityGrade={analysisRequest?.quality_grade}
                        floors={analysisRequest?.floors}
                        builtUpAreaSqft={analysisRequest?.built_up_area_sqft}
                        groundCoverageRatio={analysisRequest?.ground_coverage_ratio ?? analysisData.land_value?.ground_coverage_ratio_applied}
                        clientNotes={analysisRequest?.client_requirements}
                        aiProvider={analysisRequest?.ai_provider ?? analysisData.ai_metadata?.provider_requested}
                        solarAxisDegrees={analysisData.orientation?.optimal_axis_degrees}
                        prevailingWindDirectionDegrees={analysisData.orientation?.prevailing_wind_direction_degrees}
                      />
                    </div>
                  </div>
                  </section>
                </div>
              )}
            </div>

            {/* ================================================================= */}
            {/* PRINT VIEW: all 4 sections stacked for window.print().
                Mounted ONLY while a print pass is in flight (usePrintMode): a
                permanently-mounted copy re-renders on every tab switch,
                scroll-state change and unit toggle, and was 67 % of this
                sheet's DOM (1 224 of 1 818 nodes). */}
            {/* ================================================================= */}
            {printing && (
            <div className="report-print-all hidden space-y-10">
              {/* Document Header in Print */}
              <div className="border-b-2 border-black pb-4 mb-6">
                <h1 className="text-2xl font-bold tracking-tight text-black">
                  Comprehensive Site Feasibility Report
                </h1>
                <p className="text-sm text-gray-600 mt-1">
                  Location: {analysisData.formatted_address} ({analysisData.coordinates.latitude.toFixed(5)}, {analysisData.coordinates.longitude.toFixed(5)}) • Ref ID: {analysisData.request_id}
                </p>
              </div>

              {/* Warnings print on page 1, before the first section.  This is
                  the SAME merged list (analysis + page-1 plan warnings) the
                  downloaded PDF prints. */}
              <WarningsBanner data={bannerData} planVerdict={floorPlanData?.plan_verdict ?? null} />

              {/* SECTION 1: OVERVIEW */}
              <div className="report-print-section space-y-4">
                <div className="border-b border-gray-300 pb-1.5">
                  <h2 className="text-lg font-bold text-black uppercase tracking-wide">
                    1. Site Suitability Assessment & Overview
                  </h2>
                </div>
                <ReportHeroHeader data={analysisData} />
                <div className="grid grid-cols-2 gap-4 items-start">
                  <div className="divide-y divide-[var(--hairline)]">
                    {analysisData.factors.map((factor) => (
                      <ProvenanceFactorCard
                        key={factor.factor_id}
                        factor={factor}
                        dataSources={analysisData.data_sources}
                        methodology={analysisData.methodology}
                        variant="print"
                      />
                    ))}
                  </div>
                  <RecommendationPanel
                    summary={analysisData.engineering_summary}
                    recommendations={analysisData.detailed_recommendations}
                    recommendationItems={analysisData.recommendation_items}
                    aiMetadata={analysisData.ai_metadata}
                    parameterReflection={analysisData.parameter_reflection}
                    summaryOnly={false}
                  />
                </div>
              </div>

              {/* SECTION 2: HAZARDS */}
              <div className="report-print-section space-y-4">
                <div className="border-b border-gray-300 pb-1.5">
                  <h2 className="text-lg font-bold text-black uppercase tracking-wide">
                    2. Climate, Seismic & Environmental Hazards
                  </h2>
                </div>
                {analysisData.hazard_profile && (
                  <HazardProfileCard hazard={analysisData.hazard_profile} layout="grid" />
                )}
                <RiskMatrix risks={analysisData.risks} />
                <DataSourcesDisclosure category="hazards" degraded={analysisData.degraded_mode || (analysisData.warnings?.length ?? 0) > 0} />
              </div>

              {/* SECTION 3: ECOLOGY */}
              <div className="report-print-section space-y-4">
                <div className="border-b border-gray-300 pb-1.5">
                  <h2 className="text-lg font-bold text-black uppercase tracking-wide">
                    3. Ecological Vision, Tree Preservation & Passive Orientation
                  </h2>
                </div>
                <SiteVisionCard
                  data={siteVisionData}
                  isLoading={false}
                  onScan={() => {}}
                  hasCoordinates={hasLocation}
                  layout="grid"
                />
                <div className="grid grid-cols-2 gap-6 items-start">
                  <OrientationCompass orientation={analysisData.orientation} />
                  {analysisData.vastu_advisory && (
                    <VastuAdvisoryCard advisory={analysisData.vastu_advisory} />
                  )}
                </div>
                <DataSourcesDisclosure category="ecology" degraded={analysisData.degraded_mode || (analysisData.warnings?.length ?? 0) > 0} />
              </div>

              {/* SECTION 4: COST & PLAN */}
              <div className="report-print-section space-y-4">
                <div className="border-b border-gray-300 pb-1.5">
                  <h2 className="text-lg font-bold text-black uppercase tracking-wide">
                    4. Construction Cost Estimation & Architectural Planning
                  </h2>
                </div>
                <div className="grid grid-cols-4 gap-3.5">
                  <div className="border border-gray-300 p-3 rounded-lg">
                    <span className="text-xs text-gray-500 block">Base Rate</span>
                    <span className="text-lg font-bold text-black block">
                      ₹{formatIN(analysisData.cost_estimate.base_rate_per_sqft)}/sq ft
                    </span>
                  </div>
                  <div className="border border-gray-300 p-3 rounded-lg">
                    <span className="text-xs text-gray-500 block">Terrain Modifier</span>
                    <span className="text-lg font-bold text-black block">
                      {analysisData.cost_estimate.terrain_multiplier.toFixed(2)}x
                    </span>
                  </div>
                  <div className="border border-gray-300 p-3 rounded-lg">
                    <span className="text-xs text-gray-500 block">Civil Budget</span>
                    <span className="text-lg font-bold text-black block">
                      {formatInr(analysisData.cost_estimate.total_estimated_cost_inr)}
                    </span>
                  </div>
                  <div className="border border-gray-300 p-3 rounded-lg">
                    <span className="text-xs text-gray-500 block">Combined Total</span>
                    <span className="text-lg font-bold text-black block">
                      {currentCombinedTotal !== null ? formatInr(currentCombinedTotal) : '—'}
                    </span>
                  </div>
                </div>
                <CostBreakdownTable
                  costEstimate={analysisData.cost_estimate}
                  hideSummaryHeader={true}
                />
                {analysisData.land_value && (
                  <LandValueCard
                    landValue={analysisData.land_value}
                    civilTotalCostInr={analysisData.cost_estimate.total_estimated_cost_inr}
                  />
                )}
              </div>
            </div>
            )}
          </div>
        </main>
      </div>
    </>
  );
};
