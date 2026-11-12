import React, { useState } from 'react';
import type { VastuAdvisory, RoomGridZone } from '../services/types';
import { Icon } from './Icon';

interface VastuAdvisoryCardProps {
  advisory: VastuAdvisory;
}

export const VastuAdvisoryCard: React.FC<VastuAdvisoryCardProps> = ({ advisory }) => {
  const { ranked_entrances, room_grid, slope_reading, reconciliation_notes, road_approach } = advisory;
  const [selectedZone, setSelectedZone] = useState<RoomGridZone | null>(null);
  // Backend ranks up to four portals; show the top three by default and let the
  // user expand — the fourth is never silently dropped.
  const [showAllEntrances, setShowAllEntrances] = useState(false);
  const allEntrances = ranked_entrances || [];
  const visibleEntrances = showAllEntrances ? allEntrances : allEntrances.slice(0, 3);

  // 3x3 layout in standard Vastu orientation:
  // Top: NW, N, NE | Middle: W, Center, E | Bottom: SW, S, SE
  const quadrantOrder = ['NW', 'N', 'NE', 'W', 'Center', 'E', 'SW', 'S', 'SE'];
  const gridMap = new Map((room_grid || []).map((z) => [z.zone, z]));

  return (
    <div className="rounded-[14px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)] p-4 sm:p-[18px] space-y-3 w-full min-w-0">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--hairline)] pb-2 min-w-0 sticky top-0 bg-[var(--card-bg-subtle)] z-10">
        <div className="flex items-center gap-2 min-w-0">
          <Icon name="layout-grid" size={15} className="text-[var(--text-2)] shrink-0" />
          <h3 className="text-[14px] font-semibold text-[var(--text-1)] tracking-tight">
            Vastu & Spatial Planning Advisory
          </h3>
        </div>
        <div className="flex items-center gap-1.5 text-[12px] text-[var(--text-3)] shrink-0">
          {road_approach.is_fallback ? (
            <span className="px-2.5 py-0.5 rounded-full bg-[var(--fill)] text-[var(--text-2)]">
              Approach road: Auto
            </span>
          ) : (
            <span className="px-2.5 py-0.5 rounded-full bg-[var(--fill)] text-[var(--text-2)]">
              Approach: {road_approach.approach_side}
            </span>
          )}
        </div>
      </div>

      {/* Card Body: natural flow within ReportSheet drawer */}
      <div className="space-y-3.5">
        {/* Ranked Entrances */}
      <div className="space-y-2">
        <span className="text-[12px] font-normal text-[var(--text-3)] block">
          Ranked entrance portals
        </span>
        <div className="divide-y divide-[var(--hairline)] border-y border-[var(--hairline)]">
          {visibleEntrances.map((ent, idx) => (
            <div key={ent.direction} className="py-2 space-y-1 min-w-0 first:pt-1 last:pb-1">
              <div className="flex items-center justify-between gap-2 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="w-5 h-5 rounded-full bg-[var(--fill)] text-[var(--text-1)] text-[11px] flex items-center justify-center font-bold">
                    {idx + 1}
                  </span>
                  <span className="text-[13px] font-semibold text-[var(--text-1)]">
                    {ent.direction.endsWith('Facing') ? ent.direction : `${ent.direction} Facing`}
                  </span>
                  {ent.is_approach_side && (
                    <span className="text-[11px] font-medium bg-[var(--accent-tint)] text-[var(--accent-ink)] px-2 py-0.5 rounded-full">
                      Road facade
                    </span>
                  )}
                </div>
                <span className="text-[12px] font-semibold text-[var(--text-1)] tabular-nums">
                  Score {ent.score.toFixed(0)}
                </span>
              </div>
              <p className="text-[12px] text-[var(--text-2)] leading-normal pl-7">
                {ent.vastu_rationale}
              </p>
            </div>
          ))}
        </div>
        {allEntrances.length > 3 && (
          <button
            type="button"
            onClick={() => setShowAllEntrances((prev) => !prev)}
            className="text-[11px] font-medium text-[var(--accent-ink)] hover:underline cursor-pointer select-none"
          >
            {showAllEntrances ? 'Show top 3' : `Show all ${allEntrances.length} ranked portals`}
          </button>
        )}
      </div>

      {/* 3x3 Mandala Grid */}
      <div className="space-y-2 pt-1">
        <div className="flex justify-between items-center text-[12px] text-[var(--text-3)]">
          <span className="font-normal">
            3x3 spatial placement grid
          </span>
          <span className="text-[11px]">Click cell for details</span>
        </div>

        <div className="grid grid-cols-3 gap-1.5 bg-[var(--fill)] p-1.5 rounded-[12px]">
          {quadrantOrder.map((quad) => {
            const zone = gridMap.get(quad);
            const isSelected = selectedZone?.zone === quad;

            return (
              <button
                key={quad}
                type="button"
                onClick={() => zone && setSelectedZone(zone)}
                className={`p-2 rounded-[8px] text-left transition-ui min-h-[60px] flex flex-col justify-between select-none cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] ${
                  isSelected
                    ? 'bg-[var(--accent)] text-white shadow-sm'
                    : 'bg-[var(--card-bg-subtle)] hover:bg-[var(--fill)] border border-[var(--hairline)] text-[var(--text-1)]'
                }`}
              >
                <div className="flex justify-between items-center w-full min-w-0">
                  <span className="font-bold text-[11px] opacity-80 shrink-0">{quad}</span>
                  {zone?.zone_name && (
                    <span className="text-[10px] capitalize opacity-70 break-words leading-none text-right">
                      {zone.zone === 'Center' ? 'Brahma' : zone.zone_name}
                    </span>
                  )}
                </div>
                <span className="text-[11px] font-medium leading-[1.25] break-words mt-1 block">
                  {zone?.primary_room ?? quad}
                </span>
              </button>
            );
          })}
        </div>

        {/* Selected Zone Details */}
        {selectedZone && (
          <div className="p-3 bg-[var(--fill)] rounded-[10px] space-y-1 text-[12px] text-[var(--text-1)]">
            <div className="flex justify-between items-center font-semibold text-[13px]">
              <span>{selectedZone.zone} ({selectedZone.zone_name})</span>
              <button
                type="button"
                onClick={() => setSelectedZone(null)}
                className="text-[var(--text-3)] hover:text-[var(--text-1)] p-0.5 cursor-pointer"
                aria-label="Close zone details"
              >
                <Icon name="x" size={13} />
              </button>
            </div>
            <p className="text-[12px] text-[var(--text-2)]">
              <strong className="text-[var(--text-1)]">Primary:</strong> {selectedZone.primary_room}
              {selectedZone.alternative_room && (
                <span> • <strong className="text-[var(--text-1)]">Alt:</strong> {selectedZone.alternative_room}</span>
              )}
            </p>
            {selectedZone.prohibited && selectedZone.prohibited.length > 0 && (
              <p className="text-[12px] text-[var(--text-2)]">
                <strong className="text-[var(--semantic-red-ink)]">Avoid:</strong> {selectedZone.prohibited.join(', ')}
              </p>
            )}
            <p className="text-[11px] text-[var(--text-3)] leading-relaxed pt-0.5">
              {selectedZone.civil_engineering_rationale || selectedZone.vastu_rationale}
            </p>
          </div>
        )}
      </div>

      {/* Slope Drainage Aspect */}
      <div className="p-3 bg-[var(--fill)] rounded-[10px] text-[12px] text-[var(--text-2)] space-y-1">
        <div className="flex items-center justify-between text-[12px]">
          <span className="font-normal text-[var(--text-3)]">
            Drainage aspect
          </span>
          <span className="font-semibold text-[var(--text-1)]">
            {slope_reading.drainage_direction} ({slope_reading.auspiciousness})
          </span>
        </div>
        <p className="text-[12px] leading-relaxed">{slope_reading.rationale}</p>
        {slope_reading.remedy_notes && (
          <details className="pt-0.5">
            <summary className="cursor-pointer text-[11px] font-medium text-[var(--accent-ink)] hover:underline select-none inline-flex items-center gap-1">
              <Icon name="info" size={11} className="shrink-0" />
              Remediation notes
            </summary>
            <p className="text-[11px] text-[var(--text-2)] leading-relaxed mt-1">
              {slope_reading.remedy_notes}
            </p>
          </details>
        )}
      </div>

      {/* Reconciliation Notes */}
      {reconciliation_notes && reconciliation_notes.length > 0 && (
        <div className="space-y-2 pt-1">
          <span className="text-[12px] font-normal text-[var(--text-3)] block">
            Vastu & building physics reconciliation
          </span>
          <div className="space-y-1.5">
            {reconciliation_notes.map((item, idx) => (
              <div key={idx} className="p-2.5 bg-[var(--fill)] rounded-[8px] space-y-1 text-[12px]">
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-[var(--text-1)] text-[12px]">{item.topic}</span>
                  <span
                    className={`text-[11px] font-semibold px-2 py-0.5 rounded-full capitalize ${
                      item.status === 'concordant'
                        ? 'bg-[var(--semantic-green)]/12 text-[var(--semantic-green-ink)]'
                        : 'bg-[var(--semantic-amber)]/12 text-[var(--semantic-amber-ink)]'
                    }`}
                  >
                    {item.status}
                  </span>
                </div>
                <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-[var(--accent-tint)] text-[var(--accent-ink)] font-medium">
                    Vastu: {item.vastu_position}
                  </span>
                  <span className="text-[var(--text-3)]" aria-hidden="true">/</span>
                  {/* Opaque pill: this chip sits INSIDE a --fill row, and a
                      second translucent --fill composites to a mid gray, where
                      even the darkened secondary ink only reaches 4.12:1. */}
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-[var(--card-bg-subtle)] text-[var(--text-2)] font-medium">
                    Science: {item.scientific_passive_position}
                  </span>
                  <span className="text-[var(--text-3)]" aria-hidden="true">→</span>
                  <span className="font-semibold text-[var(--text-1)]">compromise</span>
                </div>
                <p className="text-[11px] text-[var(--text-2)] leading-relaxed">
                  {item.recommended_synthesis}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
      </div>
    </div>
  );
};
