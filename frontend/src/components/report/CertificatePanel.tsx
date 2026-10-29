import React from 'react';
import type { FloorPlanQA } from '../../services/types';
import { Icon } from '../Icon';
import { Tooltip } from '../../design/primitives';
import { groupGateLayers, qaRowText, type GateLayer } from '../../services/validationGateUI';
import { CERTIFIED_DEFINITION } from './statusTaxonomy';

/**
 * SINGLE GATE RENDERER.
 * ---------------------------------------------------------------------------
 * Every QA/gate surface — the report sheet and the generator card — renders
 * through this component. Content rules live in validationGateUI so the rows,
 * N/A reasons, warn chips and incomplete-gate flag cannot drift between
 * surfaces:
 *   - every layer renders a row; N/A rows carry their explicit reason,
 *   - WARN layers surface as chips (never a bare "Passed (0 violations)"),
 *   - a gate missing canonical layers is itself flagged,
 * - no certificate value is printed without a derived source: the
 *     relaxation claim only renders when the caller passes the real count.
 */
interface CertificatePanelProps {
  qa?: FloorPlanQA;
  /**
   * Presentation only - content is identical in both variants. `card` is the
   * generator/QA panel; `sheet` is the compact report-print treatment and
   * omits the per-row tooltips.
   */
  variant?: 'card' | 'sheet';
  /**
   * Real relaxation count derived from the plan (room-level `relaxations`).
   * Omitted => nothing is claimed. Never infer this from the gate status.
   */
  relaxationsCount?: number;
  /**
   * The server-computed plan verdict. Rendered verbatim so this panel, the
   * plan card and the exported PDF can never state different verdicts
   *. Omitted => the row is not claimed.
   */
  planVerdict?: string | null;
}

type GateStatus = 'PASS' | 'WARN' | 'FAIL' | 'N/A';

const CHIP_STYLES: Record<GateStatus, string> = {
  PASS: 'bg-[var(--semantic-green)]/10 text-[var(--semantic-green-ink)] border border-[var(--semantic-green)]/30',
  WARN: 'bg-[var(--semantic-amber)]/10 text-[var(--semantic-amber-ink)] border border-[var(--semantic-amber)]/30',
  FAIL: 'bg-[var(--semantic-red)]/10 text-[var(--semantic-red-ink)] border border-[var(--semantic-red)]/30',
  'N/A': 'bg-[var(--fill)] text-[var(--text-2)] border border-dashed border-[var(--hairline)]',
};

export const CertificatePanel: React.FC<CertificatePanelProps> = ({
  qa,
  variant = 'card',
  relaxationsCount,
  planVerdict,
}) => {
  const gate = qa?.validation_gate as
    | {
        layers?: GateLayer[];
        overall_status?: string;
        certificate_id?: string;
      }
    | undefined;
  if (!gate?.layers || gate.layers.length === 0) return null;

  const isSheet = variant === 'sheet';
  const { overall, warnChips, incompleteIds } = groupGateLayers(gate);
  const counts = gate.layers.reduce<Record<string, number>>((acc, l) => {
    acc[l.status] = (acc[l.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <section
      data-testid="certificate-panel"
      aria-label="Universal validation gate certificate"
      className={
        isSheet
          ? 'w-full min-w-0 space-y-2'
          : 'bw-card rounded-[14px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)] p-4 space-y-3 w-full min-w-0'
      }
    >
      <div className="flex items-center justify-between border-b border-[var(--hairline)] pb-2 min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <Icon name="shield-check" size={isSheet ? 13 : 15} className="text-[var(--text-2)] shrink-0" />
          <h3
            className={
              isSheet
                ? 'text-xs font-semibold uppercase tracking-wider text-[var(--text-2)]'
                : 'text-[14px] font-semibold text-[var(--text-1)] tracking-tight'
            }
          >
            Validation Gate Certificate
          </h3>
        </div>
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-bold ${
            overall === 'PASS'
              ? 'bg-[var(--semantic-green)]/10 text-[var(--semantic-green-ink)]'
              : overall === 'WARN'
              ? 'bg-[var(--semantic-amber)]/10 text-[var(--semantic-amber-ink)]'
              : 'bg-[var(--semantic-red)]/10 text-[var(--semantic-red-ink)]'
          }`}
        >
          {overall}
        </span>
      </div>

      {planVerdict && (
        <div
          data-testid="certificate-plan-verdict"
          className={`flex items-center gap-1.5 text-[11px] font-semibold ${
            planVerdict === 'NOT-CERTIFIED-FAIL-STAMP'
              ? 'text-[var(--semantic-red-ink)]'
              : planVerdict === 'ADVISORY'
              ? 'text-[var(--semantic-amber-ink)]'
              : 'text-[var(--semantic-green-ink)]'
          }`}
        >
          <span>Plan verdict:</span>
          <span className="font-mono">{planVerdict}</span>
        </div>
      )}

      <p
        data-testid="certified-definition"
        className="text-[10px] leading-snug text-[var(--text-3)]"
      >
        {CERTIFIED_DEFINITION}
      </p>

      <div className="divide-y divide-[var(--hairline)]" data-testid="validation-gate-layer-table">
        {gate.layers.map((layer) => (
          <div key={layer.layer_id} className="py-2 flex items-start justify-between gap-2 min-w-0">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 min-w-0">
                <span className="font-mono text-[11px] text-[var(--text-3)] shrink-0">{layer.layer_id}</span>
                <span className="text-[12px] font-semibold text-[var(--text-1)] truncate">{layer.title}</span>
              </div>
              <p className="text-[11px] text-[var(--text-3)] leading-snug mt-0.5 line-clamp-2 pl-[calc(3rem+0.5rem)]">
                {qaRowText(layer)}
              </p>
            </div>
            <div className="flex items-center gap-1.5 shrink-0">
              <span className={`inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-bold tabular-nums ${CHIP_STYLES[layer.status]}`}>
                {layer.status}
              </span>
              {!isSheet && (
                <Tooltip label={`What does ${layer.layer_id} check? ${layer.summary || layer.reason || 'See citation.'}`}>
                  <button
                    type="button"
                    aria-label={`What does ${layer.layer_id} check?`}
                    className="w-5 h-5 rounded-full bg-[var(--fill)] hover:bg-[var(--fill-hover)] text-[var(--text-3)] flex items-center justify-center cursor-pointer transition-colors"
                  >
                    <Icon name="info" size={10} />
                  </button>
                </Tooltip>
              )}
            </div>
          </div>
        ))}
      </div>

      {incompleteIds.length > 0 && (
        <div
          className="text-[10px] font-semibold text-rose-700 dark:text-rose-300"
          data-testid="validation-gate-incomplete"
        >
          Gate incomplete: missing {incompleteIds.join(', ')}
        </div>
      )}

      {warnChips.length > 0 && (
        <div className="flex flex-wrap gap-1 pt-1" data-testid="validation-gate-warn-chips">
          {warnChips.map((ld) => (
            <span
              key={ld.layer_id}
              className="px-1.5 py-0.5 rounded-full bg-amber-500/15 text-amber-800 dark:text-amber-200 text-[10px] font-semibold inline-flex items-center gap-1"
            >
              <Icon name="alert-triangle" size={10} className="shrink-0" />
              {ld.layer_id} {ld.title}
            </span>
          ))}
        </div>
      )}

      {(() => {
        // PROPORTION layer evidence (Disclosure): the layer row alone is a
        // verdict; the reader must be able to see WHICH room is over its band,
        // by how much, whether it is a listed relaxation, and where surplus went.
        const l16 = gate.layers?.find((l) => l.layer_id === 'L16');
        const d = (l16?.details ?? {}) as Record<string, any>;
        const rooms: Array<Record<string, any>> = Array.isArray(d.rooms) ? d.rooms : [];
        if (!rooms.length) return null;
        const over = rooms.filter((r) => r.inside_band === false);
        const surplus = d.surplus ?? {};
        return (
          <details
            className="rounded-[8px] border border-[var(--hairline)] bg-[var(--fill)]/40 px-2.5 py-2"
            data-testid="proportion-layer"
            open={isSheet ? undefined : false}
          >
            <summary className="text-[11px] font-semibold text-[var(--text-2)] cursor-pointer select-none">
              L16 Proportion &amp; Surplus — {rooms.length - over.length}/{rooms.length} rooms inside band
            </summary>
            <div className="mt-2 space-y-2 min-w-0">
              <div className="flex flex-wrap gap-1.5 text-[10px] tabular-nums">
                <span className="px-1.5 py-0.5 rounded bg-[var(--fill)] text-[var(--text-2)]">
                  {d.relaxations?.length ?? 0} listed relaxation(s)
                </span>
                <span className={`px-1.5 py-0.5 rounded ${(d.beyond_cap?.length ?? 0) > 0 ? 'bg-rose-500/15 text-rose-700 dark:text-rose-300' : 'bg-[var(--fill)] text-[var(--text-2)]'}`}>
                  {d.beyond_cap?.length ?? 0} beyond {String(d.relaxation_cap ?? 1.4)}x cap
                </span>
                <span className="px-1.5 py-0.5 rounded bg-[var(--fill)] text-[var(--text-2)]">
                  {d.ceiling_overages?.length ?? 0} ceiling overage(s)
                </span>
                <span className="px-1.5 py-0.5 rounded bg-[var(--fill)] text-[var(--text-2)]">
                  void {Number(surplus.void_ratio_pct ?? 0).toFixed(1)}%
                </span>
              </div>
              {rooms.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full text-[10px] tabular-nums" data-testid="proportion-rooms">
                    <thead>
                      <tr className="text-[var(--text-3)] text-left">
                        <th className="font-medium py-0.5 pr-2">Room</th>
                        <th className="font-medium py-0.5 pr-2">F</th>
                        <th className="font-medium py-0.5 pr-2">Measured</th>
                        <th className="font-medium py-0.5 pr-2">Band</th>
                        <th className="font-medium py-0.5 pr-2">Band %</th>
                        <th className="font-medium py-0.5 pr-2">Status</th>
                        <th className="font-medium py-0.5">Relaxation</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rooms.slice(0, 40).map((r, i) => (
                        <tr key={`${i}:${r.room_id}`} className="border-t border-[var(--hairline)]">
                          <td className="py-0.5 pr-2 text-[var(--text-1)] truncate max-w-[9rem]" title={r.room_id}>{r.room_id}</td>
                          <td className="py-0.5 pr-2 text-[var(--text-3)]">{r.floor}</td>
                          <td className="py-0.5 pr-2">1:{Number(r.measured_aspect).toFixed(2)}</td>
                          <td className="py-0.5 pr-2">1:{Number(r.band).toFixed(2)}</td>
                          <td className={`py-0.5 pr-2 font-semibold ${Number(r.band_pct) > 140 ? 'text-[var(--semantic-red-ink)]' : Number(r.band_pct) > 100 ? 'text-[var(--semantic-amber-ink)]' : 'text-[var(--text-2)]'}`}>
                            {Number(r.band_pct).toFixed(0)}%
                          </td>
                          <td className="py-0.5 pr-2">
                            {r.inside_band
                              ? 'inside'
                              : r.beyond_cap_justification
                                ? 'justified'
                                : 'outside'}
                          </td>
                          <td className="py-0.5 text-[var(--text-3)]">
                            {r.relaxation_rule
                              ? `${r.relaxation_rule} @ ${Number(r.relaxation_factor).toFixed(2)}x`
                              : r.beyond_cap_justification
                                ? 'PROP-PLATE-CAP (justified)'
                                : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {(d.ceiling_overages?.length ?? 0) > 0 && (
                <ul className="text-[10px] text-[var(--text-3)] leading-snug space-y-0.5" data-testid="proportion-ceilings">
                  {d.ceiling_overages.slice(0, 8).map((c: Record<string, any>, i: number) => (
                    <li key={`${i}:${c.room}`}>
                      Ceiling overage: <span className="text-[var(--text-2)]">{c.room}</span> is{' '}
                      {Number(c.area_sqm).toFixed(1)} m² against a {Number(c.ceiling_sqm).toFixed(1)} m²
                      planning ceiling (+{Number(c.overage_sqm).toFixed(1)} m², disclosed not stretched)
                    </li>
                  ))}
                </ul>
              )}
              <p className="text-[10px] text-[var(--text-3)] leading-snug">
                Surplus routing:{' '}
                {[
                  Number(surplus.outdoor_sqm ?? 0) > 0 ? `outdoor ${Number(surplus.outdoor_sqm).toFixed(1)} m²` : null,
                  Number(surplus.anonymous_outdoor_sqm ?? 0) > 0
                    ? `${Number(surplus.anonymous_outdoor_sqm).toFixed(1)} m² unlabelled`
                    : null,
                  Number(surplus.dead_corner_sqm ?? 0) > 0
                    ? `dead corner ${Number(surplus.dead_corner_sqm).toFixed(1)} m²`
                    : null,
                  Number(surplus.residual_slivers ?? 0) > 0
                    ? `${surplus.residual_slivers} residual sliver(s), ${Number(surplus.absorbed_slivers ?? 0)} absorbed`
                    : null,
                ].filter(Boolean).join(' · ') || 'no residual surplus'}
                {(surplus.sliver_labels?.length ?? 0) > 0
                  ? ` — ${surplus.sliver_labels.slice(0, 6).join(' · ')}`
                  : ''}
              </p>
            </div>
          </details>
        );
      })()}

      <div className="pt-1 border-t border-[var(--hairline)] text-[11px] text-[var(--text-3)] flex items-center justify-between gap-2 min-w-0">
        <span className="tabular-nums">
          {counts.PASS ?? 0} pass · {counts.WARN ?? 0} warn · {counts.FAIL ?? 0} fail · {counts['N/A'] ?? 0} n/a
        </span>
        {typeof relaxationsCount === 'number' && (
          <span
            title={
              relaxationsCount === 0
                ? 'No solver relaxation or dimensional exception was used anywhere in this layout'
                : 'Bounded rule relaxations the solver applied, each with a rationale tag'
            }
            className={`font-medium truncate ${
              relaxationsCount === 0
                ? 'text-[var(--semantic-green-ink)]'
                : 'text-[var(--semantic-amber-ink)]'
            }`}
          >
            {relaxationsCount === 0
              ? 'Zero relaxations applied'
              : `${relaxationsCount} relaxation${relaxationsCount === 1 ? '' : 's'} applied`}
          </span>
        )}
      </div>

      {gate.certificate_id && (
        <p className="text-[10px] font-mono text-[var(--text-3)] truncate" title={gate.certificate_id}>
          {gate.certificate_id}
        </p>
      )}
    </section>
  );
};
