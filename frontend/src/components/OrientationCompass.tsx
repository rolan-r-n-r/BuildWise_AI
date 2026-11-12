import React from 'react';
import type { OrientationData } from '../services/types';
import { Icon } from './Icon';
import { BIOCLIMATIC_AXIS_DISCLOSURE } from './report/termDisclosures';

interface OrientationCompassProps {
  orientation: OrientationData;
}

const CARDINALS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];

function getCardinal(deg: number): string {
  const normalized = ((deg % 360) + 360) % 360;
  const idx = Math.round(normalized / 22.5) % 16;
  return CARDINALS[idx];
}

function getVentilationStatus(rating: string = 'Good') {
  const lower = rating.toLowerCase();
  if (lower.includes('excel')) {
    return {
      tone: 'green' as const,
      badgeClass: 'bg-[var(--semantic-green)]/15 text-[var(--semantic-green-ink)] border border-[var(--semantic-green)]/30',
      summary: 'Perpendicular flow',
      guidance:
        'Prevailing wind strikes broad facades at near-perpendicular angles, creating strong pressure differentials that naturally drive continuous cross-ventilation.',
    };
  }
  if (lower.includes('good')) {
    return {
      tone: 'green' as const,
      badgeClass: 'bg-[var(--semantic-green)]/15 text-[var(--semantic-green-ink)] border border-[var(--semantic-green)]/30',
      summary: 'Effective breeze',
      guidance:
        'Prevailing wind arrives at an effective oblique angle. Casement windows or architectural wing walls will efficiently deflect breezes into living areas.',
    };
  }
  if (lower.includes('mod')) {
    return {
      tone: 'amber' as const,
      badgeClass: 'bg-[var(--semantic-amber)]/15 text-[var(--semantic-amber-ink)] border border-[var(--semantic-amber)]/30',
      summary: 'Parallel airflow',
      guidance:
        'Prevailing wind travels largely parallel to the main walls. Staggered facade articulation, courtyards, or clerestory vents will enhance indoor circulation.',
    };
  }
  return {
    tone: 'red' as const,
    badgeClass: 'bg-[var(--semantic-red)]/15 text-[var(--semantic-red-ink)] border border-[var(--semantic-red)]/30',
    summary: 'Low wind capture',
    guidance:
      'Wind alignment offers low natural pressure against living facades. Consider wind catchers, induced stack-effect ventilation, or mechanical assistance.',
  };
}

export const OrientationCompass: React.FC<OrientationCompassProps> = ({ orientation }) => {
  const {
    optimal_axis_degrees = 90.0,
    axis_label = 'East-West (Pure 90 deg)',
    prevailing_wind_direction_degrees = 0,
    cross_ventilation_rating = 'Good',
    passive_design_rationale = '',
    solar_exposure_summary = '',
  } = orientation || {};

  // Geometry for balanced SVG compass (viewBox 0 0 280 236, center at 140, 123)
  const cx = 140;
  const cy = 123;
  const dialRadius = 88;

  // Wind vector calculations
  const windRad = (prevailing_wind_direction_degrees * Math.PI) / 180.0;
  const windTailRadius = dialRadius + 15;
  const windHeadRadius = 48;
  const windTailX = cx + windTailRadius * Math.sin(windRad);
  const windTailY = cy - windTailRadius * Math.cos(windRad);
  const windHeadX = cx + windHeadRadius * Math.sin(windRad);
  const windHeadY = cy - windHeadRadius * Math.cos(windRad);

  // Direction vector from tail to head
  const windDx = windHeadX - windTailX;
  const windDy = windHeadY - windTailY;
  const windDist = Math.hypot(windDx, windDy) || 1;
  const windUx = windDx / windDist;
  const windUy = windDy / windDist;
  const windNx = -windUy;
  const windNy = windUx;

  // Arrowhead geometry
  const arrowHeadLen = 10.5;
  const arrowHeadWidth = 5;
  const barbLeftX = windHeadX - arrowHeadLen * windUx + arrowHeadWidth * windNx;
  const barbLeftY = windHeadY - arrowHeadLen * windUy + arrowHeadWidth * windNy;
  const barbRightX = windHeadX - arrowHeadLen * windUx - arrowHeadWidth * windNx;
  const barbRightY = windHeadY - arrowHeadLen * windUy - arrowHeadWidth * windNy;
  const notchX = windHeadX - (arrowHeadLen - 2) * windUx;
  const notchY = windHeadY - (arrowHeadLen - 2) * windUy;

  const windCardinal = getCardinal(prevailing_wind_direction_degrees);
  const ventStatus = getVentilationStatus(cross_ventilation_rating);

  // Short label for the principal axis (strip parentheses for compact hero display)
  const axisShortName = axis_label.includes('(')
    ? axis_label.split('(')[0].trim()
    : axis_label;

  // Dial degree ticks
  const dialTicks = [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330];
  const minorTicks = [15, 45, 75, 105, 135, 165, 195, 225, 255, 285, 315, 345];

  return (
    <div
      className="rounded-[16px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)] p-4 sm:p-[18px] space-y-3 w-full min-w-0"
      data-testid="orientation-compass-card"
    >
      {/* 1. Section Header */}
      <div className="flex items-center justify-between border-b border-[var(--hairline)] pb-2.5 min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <Icon name="compass" size={16} className="text-[var(--text-2)] shrink-0" />
          <h3 className="text-[14px] font-semibold text-[var(--text-1)] tracking-tight">
            Passive Solar &amp; Wind Orientation
          </h3>
        </div>
        <span className="inline-flex items-center gap-1 text-[12px] font-normal text-[var(--text-3)] shrink-0">
          <span className="hidden sm:inline">Bioclimatic layout</span>
          {BIOCLIMATIC_AXIS_DISCLOSURE}
        </span>
      </div>

      <p className="text-[12px] text-[var(--text-2)] -mt-0.5 leading-normal">
        Bioclimatic alignment balancing solar heat protection with natural cross-ventilation.
      </p>

      {/* 2. Prominent Building Orientation Visualisation (Area A) */}
      <div className="flex flex-col items-center justify-center p-2.5 sm:p-3 bg-[var(--fill)] rounded-[12px] border border-[var(--hairline)] min-w-0">
        <svg
          viewBox="0 0 280 236"
          className="w-full max-w-[265px] sm:max-w-[280px] h-auto select-none block"
          width="280"
          height="236"
          role="img"
          aria-label={`Bioclimatic compass: Long axis oriented along ${optimal_axis_degrees.toFixed(1)} degrees, prevailing wind from ${prevailing_wind_direction_degrees.toFixed(0)} degrees (${windCardinal})`}
        >
          {/* Outer Dial Rings */}
          <circle cx={cx} cy={cy} r={dialRadius + 7} fill="none" stroke="var(--hairline)" strokeWidth="1" />
          <circle cx={cx} cy={cy} r={dialRadius} fill="none" stroke="var(--hairline)" strokeWidth="1.5" />
          <circle cx={cx} cy={cy} r={dialRadius - 9} fill="none" stroke="var(--hairline)" strokeWidth="0.75" strokeDasharray="3 3" />

          {/* Minor Intermediate Ticks (every 15°) */}
          {minorTicks.map((deg) => {
            const rad = (deg * Math.PI) / 180;
            return (
              <line
                key={`m-${deg}`}
                x1={cx + (dialRadius - 3.5) * Math.sin(rad)}
                y1={cy - (dialRadius - 3.5) * Math.cos(rad)}
                x2={cx + dialRadius * Math.sin(rad)}
                y2={cy - dialRadius * Math.cos(rad)}
                stroke="var(--hairline)"
                strokeWidth={0.75}
                opacity={0.6}
              />
            );
          })}

          {/* Compass Dial Degree Ticks (every 30°) */}
          {dialTicks.map((deg) => {
            const rad = (deg * Math.PI) / 180;
            const isCardinal = deg % 90 === 0;
            const rInner = isCardinal ? dialRadius - 7.5 : dialRadius - 4.5;
            const rOuter = dialRadius;
            return (
              <line
                key={deg}
                x1={cx + rInner * Math.sin(rad)}
                y1={cy - rInner * Math.cos(rad)}
                x2={cx + rOuter * Math.sin(rad)}
                y2={cy - rOuter * Math.cos(rad)}
                stroke={isCardinal ? 'var(--text-2)' : 'var(--hairline)'}
                strokeWidth={isCardinal ? 1.75 : 1.25}
              />
            );
          })}

          {/* Cardinal Direction Marks */}
          {/* North with architectural chevron */}
          <polygon
            points={`${cx},9 ${cx + 4.5},19 ${cx - 4.5},19`}
            fill="var(--text-1)"
          />
          <text
            x={cx}
            y={32}
            textAnchor="middle"
            className="text-[12px] font-bold fill-[var(--text-1)] select-none"
          >
            N
          </text>

          {/* South */}
          <text
            x={cx}
            y={cy + dialRadius + 16}
            textAnchor="middle"
            className="text-[11px] font-semibold fill-[var(--text-2)] select-none"
          >
            S
          </text>

          {/* East */}
          <text
            x={cx + dialRadius + 16}
            y={cy + 4}
            textAnchor="middle"
            className="text-[11px] font-semibold fill-[var(--text-2)] select-none"
          >
            E
          </text>

          {/* West */}
          <text
            x={cx - dialRadius - 16}
            y={cy + 4}
            textAnchor="middle"
            className="text-[11px] font-semibold fill-[var(--text-2)] select-none"
          >
            W
          </text>

          {/* Sun Trajectory Arc (Southern Sky) */}
          <path
            d={`M ${cx + 68} ${cy} A 68 68 0 0 1 ${cx - 68} ${cy}`}
            fill="none"
            stroke="var(--semantic-amber)"
            strokeWidth="1.5"
            strokeDasharray="4 3"
            opacity="0.55"
          />
          {/* Midday Sun indicator */}
          <circle cx={cx} cy={cy + 68} r="3.5" fill="var(--semantic-amber)" />
          <circle cx={cx} cy={cy + 68} r="6.5" fill="none" stroke="var(--semantic-amber)" strokeWidth="0.85" opacity="0.4" />
          <text
            x={cx}
            y={cy + 58}
            textAnchor="middle"
            className="text-[10px] font-semibold fill-[var(--semantic-amber-ink)] select-none"
          >
            Sun Arc
          </text>

          {/* Recommended Building Architectural Footprint & Longitudinal Axis */}
          <g transform={`rotate(${optimal_axis_degrees - 90}, ${cx}, ${cy})`}>
            {/* Axis projection guidelines */}
            <line
              x1={cx - 74}
              y1={cy}
              x2={cx + 74}
              y2={cy}
              stroke="var(--accent)"
              strokeWidth="1.5"
              strokeDasharray="4 3"
            />
            <circle cx={cx - 74} cy={cy} r="2.5" fill="var(--accent)" />
            <circle cx={cx + 74} cy={cy} r="2.5" fill="var(--accent)" />

            {/* Architectural Building Footprint (Rectangle with rounded corners) */}
            <rect
              x={cx - 55}
              y={cy - 18}
              width={110}
              height={36}
              rx={4}
              fill="var(--card-bg-subtle)"
              stroke="var(--accent)"
              strokeWidth="1.75"
            />

            {/* Architectural Glazing Apertures (emphasized window lines on broad facades) */}
            <line x1={cx - 45} y1={cy - 18} x2={cx - 30} y2={cy - 18} stroke="var(--accent)" strokeWidth="2.5" />
            <line x1={cx - 16} y1={cy - 18} x2={cx + 16} y2={cy - 18} stroke="var(--accent)" strokeWidth="2.5" />
            <line x1={cx + 30} y1={cy - 18} x2={cx + 45} y2={cy - 18} stroke="var(--accent)" strokeWidth="2.5" />

            <line x1={cx - 45} y1={cy + 18} x2={cx - 30} y2={cy + 18} stroke="var(--accent)" strokeWidth="2.5" />
            <line x1={cx - 16} y1={cy + 18} x2={cx + 16} y2={cy + 18} stroke="var(--accent)" strokeWidth="2.5" />
            <line x1={cx + 30} y1={cy + 18} x2={cx + 45} y2={cy + 18} stroke="var(--accent)" strokeWidth="2.5" />

            {/* Structural partition bays */}
            <line
              x1={cx - 30}
              y1={cy - 18}
              x2={cx - 30}
              y2={cy + 18}
              stroke="var(--hairline)"
              strokeWidth="1"
              strokeDasharray="2 2"
            />
            <line
              x1={cx + 30}
              y1={cy - 18}
              x2={cx + 30}
              y2={cy + 18}
              stroke="var(--hairline)"
              strokeWidth="1"
              strokeDasharray="2 2"
            />

            {/* Label inside the building footprint */}
            <text
              x={cx}
              y={cy + 3.5}
              textAnchor="middle"
              className="text-[10px] font-bold tracking-[0.10em] fill-[var(--text-1)] select-none pointer-events-none"
            >
              BUILDING AXIS
            </text>

            {/* Facade Daylighting Identifiers */}
            <text
              x={cx}
              y={cy - 22.5}
              textAnchor="middle"
              className="text-[10px] font-semibold tracking-wider fill-[var(--accent-ink)] select-none"
            >
              NORTH (DAYLIGHT)
            </text>
            <text
              x={cx}
              y={cy + 29.5}
              textAnchor="middle"
              className="text-[10px] font-semibold tracking-wider fill-[var(--text-2)] select-none"
            >
              SOUTH (SOLAR GAIN)
            </text>
          </g>

          {/* Center Pivot Pin */}
          <circle cx={cx} cy={cy} r="2.5" fill="var(--text-1)" />

          {/* Prevailing Wind Vector with Aerodynamic Streamlines */}
          {/* Streamline left */}
          <line
            x1={windTailX + 6 * windNx + 6 * windUx}
            y1={windTailY + 6 * windNy + 6 * windUy}
            x2={windHeadX + 6 * windNx - 6 * windUx}
            y2={windHeadY + 6 * windNy - 6 * windUy}
            stroke="var(--semantic-green)"
            strokeWidth="1.2"
            strokeDasharray="4 3"
            opacity="0.6"
            strokeLinecap="round"
          />
          {/* Streamline right */}
          <line
            x1={windTailX - 6 * windNx + 6 * windUx}
            y1={windTailY - 6 * windNy + 6 * windUy}
            x2={windHeadX - 6 * windNx - 6 * windUx}
            y2={windHeadY - 6 * windNy - 6 * windUy}
            stroke="var(--semantic-green)"
            strokeWidth="1.2"
            strokeDasharray="4 3"
            opacity="0.6"
            strokeLinecap="round"
          />

          {/* Main Wind Arrow Shaft */}
          <line
            x1={windTailX}
            y1={windTailY}
            x2={windHeadX}
            y2={windHeadY}
            stroke="var(--semantic-green)"
            strokeWidth="2.8"
            strokeLinecap="round"
          />

          {/* Main Wind Arrowhead */}
          <polygon
            points={`${windHeadX},${windHeadY} ${barbLeftX},${barbLeftY} ${notchX},${notchY} ${barbRightX},${barbRightY}`}
            fill="var(--semantic-green)"
          />

          {/* Origin Dot at wind source */}
          <circle cx={windTailX} cy={windTailY} r="3.5" fill="var(--semantic-green)" />
        </svg>

        {/* Legend */}
        <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1.5 text-[11px] text-[var(--text-2)] mt-1.5 pt-1.5 border-t border-[var(--hairline)] w-full">
          <div className="flex items-center gap-1.5">
            <span className="w-3.5 h-2 rounded-[2px] bg-[var(--card-bg-subtle)] border border-[var(--accent)] shrink-0 inline-block" />
            <span className="font-medium text-[var(--text-1)]">Building Axis</span>
            <span className="tabular-nums text-[var(--text-3)]">({optimal_axis_degrees.toFixed(1)}°)</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-[var(--semantic-green)] shrink-0 inline-block" />
            <span className="font-medium text-[var(--text-1)]">Wind</span>
            <span className="tabular-nums text-[var(--text-3)]">({prevailing_wind_direction_degrees.toFixed(0)}° {windCardinal})</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-3.5 border-t-2 border-dashed border-[var(--semantic-amber)] shrink-0 inline-block" />
            <span className="font-medium text-[var(--text-1)]">Sun Arc</span>
          </div>
        </div>
      </div>

      {/* 3. Key Performance Insights (Area B) */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 min-w-0">
        {/* Metric 1: Building Axis */}
        <div className="bg-[var(--fill)] rounded-[8px] p-2 border border-[var(--hairline)] flex flex-col justify-between min-w-0">
          <div className="flex items-center justify-between gap-1 mb-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-3)] truncate">
              Axis
            </span>
            <Icon name="compass" size={12} className="text-[var(--accent)] shrink-0" />
          </div>
          <div className="space-y-0.5 min-w-0">
            <div className="text-[13px] font-bold text-[var(--text-1)] truncate" title={axis_label}>
              {axisShortName}
            </div>
            <div className="text-[11px] font-semibold text-[var(--text-2)] tabular-nums truncate">
              {optimal_axis_degrees.toFixed(1)}° True N
            </div>
          </div>
          <div className="mt-1 pt-1 border-t border-[var(--hairline)] text-[10px] text-[var(--text-3)] leading-tight truncate">
            Blocks low sun
          </div>
        </div>

        {/* Metric 2: Natural Ventilation */}
        <div className="bg-[var(--fill)] rounded-[8px] p-2 border border-[var(--hairline)] flex flex-col justify-between min-w-0">
          <div className="flex items-center justify-between gap-1 mb-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-3)] truncate">
              Airflow
            </span>
            <Icon name="wind" size={12} className="text-[var(--semantic-green)] shrink-0" />
          </div>
          <div className="space-y-0.5 min-w-0">
            <div>
              <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full inline-flex items-center gap-1 ${ventStatus.badgeClass}`}>
                <span className="w-1.5 h-1.5 rounded-full bg-current" />
                {cross_ventilation_rating}
              </span>
            </div>
            <div className="text-[11px] font-semibold text-[var(--text-2)] tabular-nums truncate">
              {prevailing_wind_direction_degrees.toFixed(0)}° {windCardinal}
            </div>
          </div>
          <div className="mt-1 pt-1 border-t border-[var(--hairline)] text-[10px] text-[var(--text-3)] leading-tight truncate" title={ventStatus.summary}>
            {ventStatus.summary}
          </div>
        </div>

        {/* Metric 3: Solar Exposure */}
        <div className="bg-[var(--fill)] rounded-[8px] p-2 border border-[var(--hairline)] flex flex-col justify-between min-w-0">
          <div className="flex items-center justify-between gap-1 mb-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-3)] truncate">
              Solar
            </span>
            <Icon name="sun" size={12} className="text-[var(--semantic-amber)] shrink-0" />
          </div>
          <div className="space-y-0.5 min-w-0">
            <div className="text-[13px] font-bold text-[var(--text-1)] truncate">
              Balanced
            </div>
            <div className="text-[11px] font-semibold text-[var(--text-2)] truncate">
              N–S Glazing
            </div>
          </div>
          <div className="mt-1 pt-1 border-t border-[var(--hairline)] text-[10px] text-[var(--text-3)] leading-tight truncate">
            Solar control
          </div>
        </div>
      </div>

      {/* 4. Streamlined Architectural Insights (Area C) */}
      <div className="space-y-1.5 min-w-0">
        <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--text-3)] block">
          Architectural Insights
        </span>

        <div className="rounded-[8px] bg-[var(--fill)] border border-[var(--hairline)] divide-y divide-[var(--hairline)] overflow-hidden">
          {/* Insight 1: Daylight */}
          <div className="px-2.5 py-1.5 sm:py-2 flex items-start gap-2 min-w-0">
            <Icon name="sun" size={13} className="text-[var(--semantic-amber)] shrink-0 mt-0.5" />
            <p className="text-[11px] text-[var(--text-2)] leading-snug">
              <strong className="text-[var(--text-1)] font-semibold">Daylight:</strong> Broad North facade captures uniform, glare-free indirect sunlight throughout the day.
            </p>
          </div>

          {/* Insight 2: Solar Heat Gain */}
          <div className="px-2.5 py-1.5 sm:py-2 flex items-start gap-2 min-w-0">
            <Icon name="shield" size={13} className="text-[var(--accent)] shrink-0 mt-0.5" />
            <p className="text-[11px] text-[var(--text-2)] leading-snug">
              <strong className="text-[var(--text-1)] font-semibold">Thermal:</strong> Short East/West walls minimize low-sun overheating; South overhangs shade high summer sun.
            </p>
          </div>

          {/* Insight 3: Natural Ventilation */}
          <div className="px-2.5 py-1.5 sm:py-2 flex items-start gap-2 min-w-0">
            <Icon name="wind" size={13} className="text-[var(--semantic-green)] shrink-0 mt-0.5" />
            <p className="text-[11px] text-[var(--text-2)] leading-snug">
              <strong className="text-[var(--text-1)] font-semibold">Airflow:</strong> {ventStatus.guidance}
            </p>
          </div>
        </div>

        {/* Technical Engineering Rationale (Collapsible) */}
        {(passive_design_rationale || solar_exposure_summary) && (
          <details className="pt-0.5">
            <summary className="cursor-pointer text-[11px] font-medium text-[var(--accent-ink)] hover:underline inline-flex items-center gap-1 select-none">
              <Icon name="info" size={11} className="shrink-0" />
              <span>Bioclimatic engineering reference</span>
            </summary>
            <div className="text-[11px] text-[var(--text-2)] leading-relaxed mt-1.5 pl-2.5 border-l-2 border-[var(--hairline)] space-y-1 bg-[var(--fill)] p-2 rounded-[6px]">
              {solar_exposure_summary && (
                <p>
                  <strong className="text-[var(--text-1)]">Solar exposure:</strong> {solar_exposure_summary}
                </p>
              )}
              {passive_design_rationale && (
                <p>
                  <strong className="text-[var(--text-1)]">Solver rationale:</strong> {passive_design_rationale}
                </p>
              )}
            </div>
          </details>
        )}
      </div>
    </div>
  );
};
