import React, { useState, useEffect, useRef, useCallback } from 'react';
import type { AnalysisParams } from '../services/types';
import { Icon, type IconName } from './Icon';
import { Select, Tooltip, useDesign } from '../design';
import { ConstraintChips } from './ConstraintChips';
import { CollapsibleSection } from './report/CollapsibleSection';
import { MethodologyPopover } from './report/MethodologyPopover';
import { parseRequirements, parseRequirementsClientFallback } from '../services/api';
import {
  TYPOLOGY_OPTIONS,
  getMaxStoreys,
  getTypologyConfig,
  type CanonicalTypology,
} from '../services/typology';
import {
  PROVIDER_STATE_LABEL,
  effectiveProviderState,
  type ProviderState,
} from '../services/providerBadge';

/** Live provider-key availability reported by /api/status. */
export interface ProviderAvailability {
  groq: boolean;
  gemini: boolean;
}

interface AnalysisFormProps {
  /** Parameters only — the site's coordinates live with the plot (App.tsx). */
  request: AnalysisParams;
  isLoading: boolean;
  hasCoordinates: boolean;
  onChange: (updated: Partial<AnalysisParams>) => void;
  onSubmit: () => void;
  /** Opened when the CTA is pressed before a boundary exists. */
  onRequestCapture?: () => void;
  /** Provider keys reported by the backend status probe (drives the status dot). */
  providerAvailability?: ProviderAvailability | null;
  /** Backend reachability from the same probe; false renders the badge Offline. */
  engineOnline?: boolean;
  /** Captured plot area (m²); lets the coverage control print the resulting cap. */
  boundaryAreaSqm?: number | null;
}

const AREA_MIN = 500;
const AREA_MAX = 50000;
/** Milestone plinth areas the slider snaps to (magnetic, never blocking). */
const AREA_PRESETS = [500, 1000, 2000, 3000, 5000, 10000, 25000, 50000];
const AREA_SNAP_TOLERANCE = 60;

const COV_MIN = 0.4;
const COV_MAX = 0.75;
/** Legal presets the coverage slider snaps to (spacious / default / dense). */
const COV_PRESETS = [0.4, 0.6, 0.75];
const COV_SNAP_TOLERANCE = 0.011;

const SQFT_PER_SQM = 10.7639;

/** Magnetic snap: land exactly on a preset when within tolerance. */
function snapTo(value: number, presets: number[], tolerance: number): number {
  for (const p of presets) {
    if (Math.abs(value - p) <= tolerance) return p;
  }
  return value;
}

function formatSqft(v: number): string {
  return `${Math.round(v).toLocaleString()} sq ft`;
}

function formatSqmFromSqft(v: number): string {
  return `${(v / SQFT_PER_SQM).toFixed(1)} m²`;
}

/** Click-to-insert brief examples (they land in the textarea and auto-parse). */
const BRIEF_EXAMPLES = ['2 baths', 'north-facing study', 'open kitchen', 'puja room', 'home office'];

interface SliderFieldProps {
  id: string;
  label: string;
  valueText: string;
  secondaryText: string;
  ariaValueText: string;
  help: React.ReactNode;
  min: number;
  max: number;
  step: number;
  value: number;
  /** 0–100 track fill percentage. */
  pct: number;
  /** Track tick positions as percentages. */
  ticks: number[];
  /** Axis captions printed under the track (min / mid / max). */
  scaleLabels: [string, string, string];
  dragging: boolean;
  bubbleText: string;
  invalid?: boolean;
  invalidMessage?: string;
  onDragChange: (dragging: boolean) => void;
  onValueChange: (value: number) => void;
}

/**
 * Tokenized slider row: header (label + info + live value), track with tick
 * marks, and a value bubble that appears while dragging or while focused.
 * The bubble is an enhancement only — every value is also in the label row.
 */
const SliderField: React.FC<SliderFieldProps> = ({
  id,
  label,
  valueText,
  secondaryText,
  ariaValueText,
  help,
  min,
  max,
  step,
  value,
  pct,
  ticks,
  scaleLabels,
  dragging,
  bubbleText,
  invalid = false,
  invalidMessage,
  onDragChange,
  onValueChange,
}) => {
  const [focused, setFocused] = useState(false);
  const showBubble = dragging || focused;
  return (
    <div className="space-y-1 min-w-0">
      <div className="flex justify-between items-baseline gap-2 min-w-0">
        <span className="flex items-center gap-1.5 min-w-0">
          <label
            htmlFor={id}
            className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--text-3)]"
          >
            {label}
          </label>
          {help}
        </span>
        <span className="text-right shrink-0">
          <span className="block text-[13px] font-medium text-[var(--text-1)] tabular-nums leading-tight">
            {valueText}
          </span>
          <span className="block text-[10px] text-[var(--text-3)] tabular-nums leading-tight">
            {secondaryText}
          </span>
        </span>
      </div>

      <div className="py-4 min-w-0">
        <div className="relative">
          {showBubble && (
            <div
              role="presentation"
              data-testid={`${id}-bubble`}
              className="pointer-events-none absolute -top-7 z-[1050] -translate-x-1/2 rounded-[7px] bg-[var(--text-1)] px-2 py-0.5 text-[11px] font-semibold tabular-nums text-[var(--bg-page)] shadow-md whitespace-nowrap"
              style={{ left: `calc(${pct}% + ${(0.5 - pct / 100) * 22}px)` }}
            >
              {bubbleText}
            </div>
          )}
          <input
            id={id}
            type="range"
            min={min}
            max={max}
            step={step}
            value={value}
            aria-valuetext={ariaValueText}
            aria-invalid={invalid || undefined}
            onPointerDown={() => onDragChange(true)}
            onPointerUp={() => onDragChange(false)}
            onPointerCancel={() => onDragChange(false)}
            onFocus={() => setFocused(true)}
            onBlur={() => {
              setFocused(false);
              onDragChange(false);
            }}
            onChange={(e) => {
              const raw = parseFloat(e.target.value);
              onValueChange(Number.isFinite(raw) ? raw : min);
            }}
            className="ios-slider"
            style={{
              background: `linear-gradient(to right, var(--accent) 0%, var(--accent) ${pct}%, var(--fill) ${pct}%, var(--fill) 100%)`,
            }}
          />
          {/* Tick marks at the labelled presets (pointer-events: none) */}
          <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 top-1/2 -mt-[3px] h-1.5">
            {ticks.map((t) => (
              <span
                key={t}
                className="absolute top-0 h-1.5 w-[2px] -translate-x-1/2 rounded-full bg-[var(--text-3)]/60"
                style={{ left: `${t}%` }}
              />
            ))}
          </div>
        </div>

        <div className="flex justify-between items-center text-[10.5px] text-[var(--text-3)] font-medium pt-2">
          <span className="w-1/3 text-left truncate">{scaleLabels[0]}</span>
          <span className="w-1/3 text-center truncate">{scaleLabels[1]}</span>
          <span className="w-1/3 text-right truncate">{scaleLabels[2]}</span>
        </div>

        {invalid && invalidMessage && (
          <p role="alert" className="text-[12px] text-[var(--semantic-red-ink)] font-medium mt-1">
            {invalidMessage}
          </p>
        )}
      </div>
    </div>
  );
};

export const AnalysisForm: React.FC<AnalysisFormProps> = ({
  request,
  isLoading,
  hasCoordinates,
  onChange,
  onSubmit,
  onRequestCapture,
  providerAvailability = null,
  engineOnline = true,
  boundaryAreaSqm = null,
}) => {
  const [isParsingConstraints, setIsParsingConstraints] = useState(false);
  const [dragSlider, setDragSlider] = useState<'area' | 'coverage' | null>(null);
  const lastParsedTextRef = useRef<string | null>(null);
  const { pushToast } = useDesign();

  // Auto-parse client requirements into editable constraint chips
  useEffect(() => {
    const text = (request.client_requirements || '').trim();
    if (!text) {
      if (lastParsedTextRef.current !== null && request.extracted_constraints) {
        lastParsedTextRef.current = null;
        onChange({ extracted_constraints: undefined });
      }
      return;
    }

    if (text === lastParsedTextRef.current) {
      return;
    }

    // Immediately provide synchronous fallback chips for instantaneous UI feedback
    if (!request.extracted_constraints) {
      const immediate = parseRequirementsClientFallback(text);
      onChange({ extracted_constraints: immediate });
    }

    const timer = setTimeout(async () => {
      lastParsedTextRef.current = text;
      setIsParsingConstraints(true);
      try {
        const parsed = await parseRequirements(text, request.ai_provider);
        onChange({ extracted_constraints: parsed });
      } catch {
        const fallback = parseRequirementsClientFallback(text);
        onChange({ extracted_constraints: fallback });
      } finally {
        setIsParsingConstraints(false);
      }
    }, 350);

    return () => clearTimeout(timer);
  }, [request.client_requirements, request.ai_provider]);

  const isAreaValid = request.built_up_area_sqft >= AREA_MIN && request.built_up_area_sqft <= AREA_MAX;
  // Without a captured boundary the CTA is not a dead end - it opens
  // the capture wizard (STEP ZERO). Analysis itself stays gated on a committed
  // valid boundary (hasCoordinates && isAreaValid).
  const needsCapture = !hasCoordinates && !isLoading;
  const ctaEnabled = isLoading ? false : hasCoordinates ? isAreaValid : Boolean(onRequestCapture);

  const ctaDisabledReason = isLoading
    ? 'Analysis already running'
    : hasCoordinates && !isAreaValid
    ? 'Built-up plinth area must be between 500 and 50,000 sq ft'
    : null;

  // Specification grade: construction specification only — it selects the CPWD
  // plinth-area rate and the finish tier printed on the schedule sheets. It has
  // no effect on the land value, which is derived from location telemetry.
  const qualityGrades: {
    id: 'basic' | 'standard' | 'premium';
    label: string;
    rate: string;
    blurb: string;
  }[] = [
    { id: 'basic', label: 'Basic', rate: '₹1,500/sq ft', blurb: 'Builder-grade tile & paint' },
    { id: 'standard', label: 'Standard', rate: '₹2,200/sq ft', blurb: 'CPWD benchmark finishes' },
    { id: 'premium', label: 'Premium', rate: '₹3,500/sq ft', blurb: 'Imported stone & timber' },
  ];

  const typologyConfig = getTypologyConfig(request.building_typology);
  const typologyDescriptions: Record<CanonicalTypology, string> = {
    T1_SINGLE_FAMILY: 'T1 - Family villa - detached plot, no shared core',
    T2_FAMILY_APARTMENT: 'T2 - Family apartment - shared core, 2-8 units',
    T3_LARGE_COMPLEX: 'T3 - Commercial complex - suites off a spine corridor',
    T4_WAREHOUSE: 'T4 - Warehouse - clear-span bay, dock & dispatch',
  };
  const typologyIcons: Record<CanonicalTypology, IconName> = {
    T1_SINGLE_FAMILY: 'blueprint',
    T2_FAMILY_APARTMENT: 'layers',
    T3_LARGE_COMPLEX: 'layout-grid',
    T4_WAREHOUSE: 'truck',
  };

  const maxAllowedStoreys = getMaxStoreys(request.building_typology);
  const floorOptions = [
    { id: 1, label: 'G (1 Level)', description: 'Single-level footprint' },
    { id: 2, label: 'G + 1 (2 Levels)', description: 'Two levels, shared core' },
    { id: 3, label: 'G + 2 (3 Levels)', description: 'Three levels, stair + lift core' },
    { id: 4, label: 'G + 3 (4 Levels)', description: 'Four levels, statutory core stack' },
  ].map((opt) =>
    opt.id <= maxAllowedStoreys
      ? opt
      : {
          ...opt,
          disabled: true,
          disabledReason: `${typologyConfig.shortCode} is capped at ${maxAllowedStoreys} levels by the typology module`,
        }
  );

  const typologyOptions = TYPOLOGY_OPTIONS.map((o) => ({
    ...o,
    description: typologyDescriptions[getTypologyConfig(o.id).canonical],
  }));

  // Provider availability: green = key configured (or no key needed),
  // amber = will fall back to the deterministic engine, unknown = the backend
  // status probe has not answered (never claim a key is missing without proof).
  const statusKnown = providerAvailability !== null;
  const hostedDescription = (keyConfigured: boolean): string =>
    !statusKnown
      ? 'Availability unknown - backend status probe unavailable'
      : keyConfigured
      ? 'Key configured - live inference'
      : 'No API key - falls back to the built-in engine';
  const providerOptions: {
    id: string;
    label: string;
    description: string;
    state: ProviderState;
  }[] = [
    {
      id: 'groq',
      label: 'Groq Cloud (gpt-oss-120b)',
      description: hostedDescription(Boolean(providerAvailability?.groq)),
      state: !statusKnown ? 'unknown' : providerAvailability?.groq ? 'live' : 'fallback',
    },
    {
      id: 'gemini',
      label: 'Google Gemini (1.5 Flash)',
      description: hostedDescription(Boolean(providerAvailability?.gemini)),
      state: !statusKnown ? 'unknown' : providerAvailability?.gemini ? 'live' : 'fallback',
    },
    {
      id: 'mock',
      label: 'Built-in deterministic engine',
      description: 'No key, no network - always available',
      state: 'deterministic',
    },
    {
      id: 'ollama',
      label: 'Ollama (local server)',
      description: 'Requires an Ollama server on localhost:11434',
      state: 'unknown',
    },
  ];
  const aiProviders = providerOptions.map((p) => ({
    id: p.id,
    label: p.label,
    description: p.description,
  }));
  const activeProvider = providerOptions.find((p) => p.id === request.ai_provider) ?? providerOptions[2];
  // One badge state from reachability + the selected author. Never show
  // "Live" for the deterministic engine, and never show a provider claim when
  // the backend itself is unreachable.
  const badgeState = effectiveProviderState(activeProvider.state, engineOnline);
  const providerStateCaption: Record<ProviderState, string> = {
    live: 'Configured - the commentary and the room programme are authored by this engine.',
    fallback:
      'No key detected - the built-in deterministic engine authors the text and the response discloses the fallback.',
    unknown:
      'Status unverified - the request still runs, and the response always discloses which engine authored the text.',
    deterministic:
      'Built-in deterministic engine - no key, no network; the response discloses the deterministic author.',
    offline: 'Backend unreachable - no analysis can run until the engine answers the health probe.',
  };

  // Calculate track fill percentages for iOS sliders
  const areaPct = Math.min(100, Math.max(0, ((request.built_up_area_sqft - AREA_MIN) / (AREA_MAX - AREA_MIN)) * 100));

  const currentCoverage = request.ground_coverage_ratio ?? 0.6;
  const covPct = Math.min(100, Math.max(0, ((currentCoverage - COV_MIN) / (COV_MAX - COV_MIN)) * 100));

  // Tick positions (percent along the track) for the labelled presets.
  const areaTicks = Array.from(new Set([AREA_MIN, 25000, AREA_MAX])).map(
    (v) => ((v - AREA_MIN) / (AREA_MAX - AREA_MIN)) * 100
  );
  const covTicks = COV_PRESETS.map((v) => ((v - COV_MIN) / (COV_MAX - COV_MIN)) * 100);

  const footprintCap = boundaryAreaSqm ? Math.round(currentCoverage * boundaryAreaSqm) : null;

  const coverageSecondary = footprintCap !== null ? `<= ${footprintCap.toLocaleString()} m² footprint` : 'cap on plot area';

  // Parse preview: a compact, honest summary of what the brief produced.
  const constraints = request.extracted_constraints;
  const parseSummary = constraints
    ? [
        `${constraints.target_bedroom_count} bed`,
        `${constraints.target_bathroom_count} bath`,
        `${constraints.specialized_spaces.length} space${constraints.specialized_spaces.length === 1 ? '' : 's'}`,
        `${constraints.orientation_preferences.length} orientation`,
      ].join(' · ')
    : null;
  const briefLength = (request.client_requirements || '').length;

  // The example chips append to the LATEST brief, not to the brief captured by
  // the last render. Two chips clicked in quick succession used to race: the
  // second handler still closed over the pre-first-click text and overwrote it,
  // so the audit (and a fast user) got only the last example. The ref advances
  // synchronously on every insert and re-syncs whenever the controlled value
  // changes from anywhere else (typing, paste, preset).
  const briefRef = useRef(request.client_requirements || '');
  useEffect(() => {
    briefRef.current = request.client_requirements || '';
  }, [request.client_requirements]);

  const insertExample = useCallback(
    (example: string) => {
      const current = briefRef.current;
      const next = (current ? `${current.replace(/,\s*$/, '')}, ` : '') + example;
      if (next.length > 240) return;
      briefRef.current = next;
      onChange({ client_requirements: next });
    },
    [onChange]
  );

  const handleCta = useCallback(() => {
    if (needsCapture) {
      onRequestCapture?.();
      return;
    }
    pushToast({ message: 'Feasibility analysis started', tone: 'neutral' });
    onSubmit();
  }, [needsCapture, onRequestCapture, onSubmit, pushToast]);

  // Enter submits from anywhere in the panel except the brief textarea (where
  // Enter is a newline) and buttons (where Enter already activates the control).
  const handlePanelKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'Enter' || e.shiftKey || e.metaKey || e.ctrlKey || e.altKey) return;
    const tag = (e.target as HTMLElement)?.tagName;
    if (tag === 'TEXTAREA' || tag === 'BUTTON') return;
    if (!ctaEnabled || isLoading) return;
    e.preventDefault();
    handleCta();
  };

  const gradeInfo = (
    <MethodologyPopover
      factorName="Specification Grade"
      title="What this affects"
      sections={[
        {
          label: 'CPWD rate applied',
          text: 'Basic ₹1,500 · Standard ₹2,200 · Premium ₹3,500 per sq ft, applied to the built-up plinth area, then scaled by storey and terrain factors.',
        },
        {
          label: 'Finish schedule on sheets',
          text: 'Rewrites the Room Schedule finish column on every floor sheet — living room: basic "Ceramic Floor Tile 600x600", standard "Polished Vitrified Tile 800x800", premium "Imported Polished Travertine 800x800".',
        },
        {
          label: 'Not the land price',
          text: 'This is a construction specification. Indicative land value is derived separately from road access and facility proximity telemetry.',
        },
      ]}
    />
  );

  const areaInfo = (
    <MethodologyPopover
      factorName="Built-up Plinth Area"
      title="What this affects"
      sections={[
        {
          label: 'Floor plates',
          text: 'Total built-up area across all storeys; divided by storeys it sets the area each floor plate must carry.',
        },
        {
          label: 'Construction cost',
          text: 'area × grade rate × storey factor (4% per extra level) × terrain factor, then split across the CPWD cost heads.',
        },
        {
          label: 'Room programme',
          text: 'Sizes the generated programme: a compact brief returns a minimal habitable core, a large brief earns the extended programme (extra bedroom, store, dining).',
        },
      ]}
    />
  );

  const coverageInfo = (
    <MethodologyPopover
      factorName="Ground Coverage Ratio"
      title="What this affects"
      sections={[
        {
          label: 'Footprint formula',
          text: 'Buildable footprint <= coverage × plot area. At 60% a 1,000 m² plot permits a 600 m² ground floor.',
        },
        {
          label: 'Where it lands',
          text: 'Caps the ground-floor envelope in the solver, sizes the site-plan footprint and parking apron, and prints as the applied coverage on the report.',
        },
        {
          label: 'Legal band',
          text: 'Sliders are limited to 0.40 (spacious) - 0.75 (dense urban). Values are validated server-side against the captured plot before use.',
        },
      ]}
    />
  );

  const briefInfo = (
    <MethodologyPopover
      factorName="Client Requirements"
      title="What this affects"
      sections={[
        {
          label: 'Parsed into constraints',
          text: 'Free text becomes editable chips: bedroom and bathroom counts, specialised spaces, adjacencies and orientation preferences.',
        },
        {
          label: 'Feeds the plan',
          text: 'The brief is sent with the room-programme request, reflected in the narrative commentary, and enforced by the solver (exclusions, orientation, wet-zone adjacency).',
        },
      ]}
    />
  );

  const narrativeInfo = (
    <MethodologyPopover
      factorName="Report Narrative Engine"
      title="What this affects"
      sections={[
        {
          label: 'What it writes',
          text: 'The engineering commentary, parameter reflection and structural recommendations. It never computes a number — scores, costs and hazard data stay deterministic.',
        },
        {
          label: 'Programme source',
          text: 'The same provider synthesizes the room programme before the geometry solver, so switching it changes which engine authored the plan.',
        },
        {
          label: 'Fallback',
          text: 'With no key, or on a failed call, the built-in deterministic engine authors the text and the response discloses the substitution.',
        },
      ]}
    />
  );

  return (
    <div className="space-y-4 w-full min-w-0" onKeyDown={handlePanelKeyDown}>
      {/* ---------------- Project Parameters ---------------- */}
      <CollapsibleSection
        sectionId="side.programme"
        title="Project Parameters"
        icon="settings"
        meta={
          <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--text-3)]">
            CPWD Standard
          </span>
        }
      >
        <div className="space-y-4 pt-1">
          <SliderField
            id="area-input"
            label="Built-up Plinth Area"
            valueText={formatSqft(request.built_up_area_sqft)}
            secondaryText={formatSqmFromSqft(request.built_up_area_sqft)}
            ariaValueText={`${formatSqft(request.built_up_area_sqft)} (${formatSqmFromSqft(
              request.built_up_area_sqft
            )})`}
            help={areaInfo}
            min={AREA_MIN}
            max={AREA_MAX}
            step={10}
            value={request.built_up_area_sqft}
            pct={areaPct}
            ticks={areaTicks}
            scaleLabels={[formatSqft(AREA_MIN), formatSqft(25000), formatSqft(AREA_MAX)]}
            dragging={dragSlider === 'area'}
            bubbleText={formatSqft(request.built_up_area_sqft)}
            invalid={!isAreaValid}
            invalidMessage="Area must be between 500 and 50,000 sq ft."
            onDragChange={(d) => setDragSlider(d ? 'area' : null)}
            onValueChange={(v) =>
              onChange({ built_up_area_sqft: snapTo(v, AREA_PRESETS, AREA_SNAP_TOLERANCE) })
            }
          />

          {/* Specification Grade - segmented cards (accent selected state) */}
          <div className="space-y-1.5 min-w-0">
            <span className="flex items-center gap-1.5">
              <span
                id="quality-grade-label"
                className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--text-3)]"
              >
                Specification Grade
              </span>
              {gradeInfo}
            </span>
            <div
              role="radiogroup"
              aria-labelledby="quality-grade-label"
              data-testid="quality-grade-group"
              className="bg-[var(--fill)] rounded-[10px] p-[2px] grid grid-cols-3 gap-1 min-w-0"
            >
              {qualityGrades.map((grade) => {
                const isActive = request.quality_grade === grade.id;
                return (
                  <button
                    key={grade.id}
                    type="button"
                    role="radio"
                    aria-checked={isActive}
                    data-testid={`quality-grade-${grade.id}`}
                    onClick={() => onChange({ quality_grade: grade.id })}
                    className={`py-1.5 px-1 rounded-[8px] text-center transition-colors duration-150 ease-apple select-none cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/40 ${
                      isActive
                        ? 'bg-[var(--segmented-active-bg)] bw-segmented-active-shadow'
                        : 'hover:bg-[var(--fill-hover)]'
                    }`}
                  >
                    <span
                      className="text-[12.5px] font-semibold block leading-tight"
                      style={{
                        color: isActive ? 'var(--segmented-active-label)' : 'var(--text-2)',
                      }}
                    >
                      {grade.label}
                    </span>
                    <span
                      className="text-[10.5px] block mt-0.5 font-medium tabular-nums leading-tight"
                      style={{
                        color: isActive ? 'var(--segmented-active-sublabel)' : 'var(--text-3)',
                      }}
                    >
                      {grade.rate}
                    </span>
                    <span
                      className="text-[10px] block mt-0.5 font-normal leading-[1.2]"
                      style={{
                        color: isActive ? 'var(--segmented-active-sublabel)' : 'var(--text-3)',
                      }}
                    >
                      {grade.blurb}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </CollapsibleSection>

      {/* ---------------- Building Configuration ---------------- */}
      <CollapsibleSection
        sectionId="side.building"
        title="Building Configuration"
        icon={typologyIcons[typologyConfig.canonical]}
        meta={
          <span className="text-[11px] font-medium tabular-nums text-[var(--text-3)]">
            {typologyConfig.canonical.replace('_', ' ')} ·{' '}
            {request.floors <= 1 ? 'G' : `G+${request.floors - 1}`}
          </span>
        }
      >
        <div className="space-y-3 pt-1">
          {/* Container query, not a viewport one: both selects live in the
              340px control panel, where a 640px viewport breakpoint still
              forced two columns and clipped the values ("Residential (Ap…",
              155px of text in a 105px cell). */}
          <div className="grid grid-cols-1 @md:grid-cols-2 gap-2.5 min-w-0">
            <div className="min-w-0">
              <label
                htmlFor="typology-select"
                className="block text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--text-3)] mb-1"
              >
                Building Typology
              </label>
              <Select
                id="typology-select"
                value={request.building_typology}
                onChange={(val) => {
                  const maxFloors = getMaxStoreys(val);
                  const newFloors = Math.min(request.floors, maxFloors);
                  onChange({ building_typology: val, floors: newFloors });
                }}
                options={typologyOptions}
                ariaLabel="Building Typology"
              />
              {/* Description line under the value (icon + one-line meaning) */}
              <p
                data-testid="typology-caption"
                className="mt-1 flex items-start gap-1.5 text-[11px] text-[var(--text-3)] leading-snug"
              >
                <Icon
                  name={typologyIcons[typologyConfig.canonical]}
                  size={12}
                  className="mt-[1px] shrink-0 text-[var(--text-3)]"
                />
                <span className="min-w-0">{typologyDescriptions[typologyConfig.canonical]}</span>
              </p>
            </div>

            <div className="min-w-0">
              <label
                htmlFor="floors-select"
                className="block text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--text-3)] mb-1"
              >
                Storeys (Levels)
              </label>
              <Select
                id="floors-select"
                value={request.floors}
                onChange={(val) => onChange({ floors: parseInt(val, 10) || 1 })}
                options={floorOptions}
                ariaLabel="Storeys (Levels)"
              />
              <p
                data-testid="storeys-caption"
                className="mt-1 flex items-start gap-1.5 text-[11px] text-[var(--text-3)] leading-snug"
              >
                <Icon name="layers" size={12} className="mt-[1px] shrink-0 text-[var(--text-3)]" />
                <span className="min-w-0">
                  {request.floors <= 1
                    ? `Single level - isolated footings; ${typologyConfig.shortCode} capped at ${maxAllowedStoreys}`
                    : `${request.floors} levels - core stacks vertically; ${typologyConfig.shortCode} capped at ${maxAllowedStoreys}`}
                </span>
              </p>
            </div>
          </div>

          <SliderField
            id="coverage-input"
            label="Ground Coverage Ratio"
            valueText={`${Math.round(currentCoverage * 100)}%`}
            secondaryText={coverageSecondary}
            ariaValueText={`${Math.round(currentCoverage * 100)} percent of the plot area`}
            help={coverageInfo}
            min={COV_MIN}
            max={COV_MAX}
            step={0.01}
            value={currentCoverage}
            pct={covPct}
            ticks={covTicks}
            scaleLabels={['40% (Spacious)', '60% (Default)', '75% (Dense Urban)']}
            dragging={dragSlider === 'coverage'}
            bubbleText={`${Math.round(currentCoverage * 100)}%`}
            onDragChange={(d) => setDragSlider(d ? 'coverage' : null)}
            onValueChange={(v) =>
              onChange({ ground_coverage_ratio: snapTo(v, COV_PRESETS, COV_SNAP_TOLERANCE) })
            }
          />
        </div>
      </CollapsibleSection>

      {/* ---------------- Client Brief ---------------- */}
      <CollapsibleSection
        sectionId="side.brief"
        title="Client Requirements"
        icon="file-text"
        meta={
          <span className="text-[11px] font-medium">Optional</span>
        }
      >
        <div className="space-y-1.5 pt-1 min-w-0">
          <div className="flex justify-between items-baseline gap-2 min-w-0">
            <span className="flex items-center gap-1.5">
              <label
                htmlFor="client-requirements-input"
                className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--text-3)]"
              >
                Design Brief
              </label>
              {briefInfo}
            </span>
            <span
              data-testid="brief-counter"
              className={`text-[10px] tabular-nums shrink-0 ${
                briefLength >= 220 ? 'text-[var(--semantic-amber-ink)] font-semibold' : 'text-[var(--text-3)]'
              }`}
            >
              {briefLength}/240
            </span>
          </div>
          <textarea
            id="client-requirements-input"
            rows={3}
            maxLength={240}
            value={request.client_requirements || ''}
            onChange={(e) => onChange({ client_requirements: e.target.value })}
            placeholder="e.g. home office, 2 baths, north-facing study, open kitchen"
            className="w-full bg-[var(--fill)] border border-[var(--separator)] rounded-[10px] p-2.5 text-[13px] text-[var(--text-1)] placeholder-[var(--text-3)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)] resize-none transition-colors duration-150"
          />

          {/* Click-to-insert examples */}
          <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
            <span className="text-[10px] uppercase tracking-[0.08em] text-[var(--text-3)] font-semibold">
              Add
            </span>
            {BRIEF_EXAMPLES.map((ex) => (
              <button
                key={ex}
                type="button"
                data-testid={`brief-example-${ex.replace(/\s+/g, '-')}`}
                onClick={() => insertExample(ex)}
                title={`Insert "${ex}" into the brief`}
                className="px-2 py-0.5 rounded-[6px] bg-[var(--fill)] hover:bg-[var(--fill-hover)] text-[11px] font-medium text-[var(--text-2)] hover:text-[var(--text-1)] border border-dashed border-[var(--separator)] transition-colors duration-150 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/40"
              >
                + {ex}
              </button>
            ))}
          </div>

          {/* Parse preview indicator */}
          {(isParsingConstraints || parseSummary) && (
            <div
              data-testid="brief-parse-preview"
              aria-live="polite"
              className="flex items-center gap-2 text-[11px] text-[var(--text-2)] min-w-0"
            >
              {isParsingConstraints ? (
                <>
                  <span className="ios-spinner-16 shrink-0" aria-hidden="true" />
                  <span className="truncate">Parsing the brief into constraints…</span>
                </>
              ) : (
                <>
                  <Icon name="check" size={12} className="shrink-0 text-[var(--accent-ink)]" />
                  <span className="truncate tabular-nums">
                    Parsed: {parseSummary}
                    {constraints?.extraction_source === 'groq_llm' || constraints?.extraction_source === 'gemini_llm'
                      ? ' · AI extracted'
                      : ' · rule parsed'}
                  </span>
                </>
              )}
            </div>
          )}

          {/* Interactive Constraint Chips */}
          {request.extracted_constraints && (
            <div className="pt-1">
              <ConstraintChips
                constraints={request.extracted_constraints}
                onChange={(updated) => onChange({ extracted_constraints: updated })}
                isLoading={isParsingConstraints}
              />
            </div>
          )}
        </div>
      </CollapsibleSection>

      {/* ---------------- Report Narrative Engine ---------------- */}
      <CollapsibleSection
        sectionId="side.narrative"
        title="Report Narrative Engine"
        icon="sparkles"
        meta={
          <span className="flex items-center gap-1.5 text-[11px] text-[var(--text-3)]">
            <span
              data-testid="provider-status-dot"
              data-provider-state={badgeState}
              title={providerStateCaption[badgeState]}
              aria-hidden="true"
              className="w-2 h-2 rounded-full"
              style={{
                background:
                  badgeState === 'live'
                    ? 'var(--semantic-green)'
                    : badgeState === 'offline'
                    ? 'var(--semantic-red)'
                    : 'var(--semantic-amber)',
              }}
            />
            <span
              className="font-medium"
              data-testid="provider-state-label"
              data-provider-state={badgeState}
            >
              {PROVIDER_STATE_LABEL[badgeState]}
            </span>
          </span>
        }
      >
        <div className="min-w-0 pt-1">
          <span className="flex items-center gap-1.5">
            <label
              htmlFor="ai-provider-select"
              className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--text-3)]"
            >
              Commentary author
            </label>
            {narrativeInfo}
          </span>
          <Select
            id="ai-provider-select"
            value={request.ai_provider}
            onChange={(val) => onChange({ ai_provider: val })}
            options={aiProviders}
            ariaLabel="Report narrative engine"
            className="mt-1"
          />
          <p
            data-testid="provider-caption"
            className="mt-1 flex items-start gap-1.5 text-[11px] text-[var(--text-3)] leading-snug"
          >
            <Icon
              name={badgeState === 'live' || badgeState === 'deterministic' ? 'badge-check' : 'alert-triangle'}
              size={12}
              className={`mt-[1px] shrink-0 ${
                badgeState === 'live'
                  ? 'text-[var(--semantic-green-ink)]'
                  : badgeState === 'offline'
                  ? 'text-[var(--semantic-red-ink)]'
                  : 'text-[var(--semantic-amber-ink)]'
              }`}
            />
            <span className="min-w-0">{providerStateCaption[badgeState]}</span>
          </p>
        </div>
      </CollapsibleSection>

      {/* ---------------- Primary CTA ---------------- */}
      <div className="pt-1 min-w-0">
        {ctaDisabledReason ? (
          <Tooltip label={ctaDisabledReason} placeAbove>
            <span className="block w-full">
              <CtaButton
                isLoading={isLoading}
                enabled={false}
                hasCoordinates={hasCoordinates}
                onClick={handleCta}
              />
            </span>
          </Tooltip>
        ) : (
          <CtaButton
            isLoading={isLoading}
            enabled={ctaEnabled}
            hasCoordinates={hasCoordinates}
            onClick={handleCta}
          />
        )}
        {isLoading && (
          <p
            data-testid="run-microcopy"
            aria-live="polite"
            className="mt-2 text-[11px] text-[var(--text-3)] text-center"
          >
            Running the deterministic pipeline - the report opens automatically when it completes.
          </p>
        )}
      </div>
    </div>
  );
};

/** Flat --accent CTA: white label, radius 12, height 44, full width. */
const CtaButton: React.FC<{
  isLoading: boolean;
  enabled: boolean;
  hasCoordinates: boolean;
  onClick: () => void;
}> = ({ isLoading, enabled, hasCoordinates, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    disabled={!enabled || isLoading}
    className={`w-full h-11 px-4 rounded-[12px] font-semibold text-[13px] sm:text-[14px] flex items-center justify-center gap-2 transition-colors duration-150 select-none shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/40 ${
      isLoading
        ? 'bg-[var(--fill)] text-[var(--text-3)] cursor-not-allowed opacity-90'
        : enabled
        ? 'bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] active:bg-[var(--accent-press)] cursor-pointer'
        : 'bg-[var(--fill)] text-[var(--text-3)] cursor-not-allowed'
    }`}
  >
    {isLoading ? (
      <>
        <div className="ios-spinner-16 shrink-0" aria-hidden="true" />
        <span>Analyzing...</span>
      </>
    ) : (
      <>
        <Icon name="crosshair" size={16} className="shrink-0" />
        <span>{hasCoordinates ? 'Run Site Feasibility Analysis' : 'Select Location on Map to Begin'}</span>
      </>
    )}
  </button>
);
