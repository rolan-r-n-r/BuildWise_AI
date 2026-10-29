import React, { useMemo, useState } from 'react';
import { Icon } from '../Icon';
import {
  buildWarningReport,
  warningSummary,
  type ListedDeviationRow,
  type RelaxationGroup,
  type RelaxationInput,
  type TruthLabelInput,
  type WarningEntry,
  type WarningReport,
} from '../../services/warningReport';

interface WarningReportViewProps {
  warnings: readonly (string | null | undefined)[];
  relaxations?: readonly RelaxationInput[];
  /** The SERVER verdict; never re-derived here. */
  planVerdict?: string | null;
  /** Certificate failure rows, verbatim: the ONLY source of group A rows. */
  certificateFailures?: readonly (string | null | undefined)[] | null;
  /** Print/debug: every tier and row starts open (never hides a line on paper). */
  expandAll?: boolean;
  /**
   * One prebuilt report, shared with the advisor so both surfaces read the same
   * counts. Omitted: this component builds its own from warnings + relaxations.
   */
  prebuiltReport?: WarningReport;
}

const chip =
  'inline-flex max-w-full min-w-0 items-center rounded-[5px] px-1.5 py-0.5 text-[10px] font-mono font-semibold leading-tight';
const tierTone: Record<string, string> = {
  T1: 'bg-[var(--semantic-red)]/12 text-[var(--semantic-red-ink)]',
  T2: 'bg-[var(--semantic-amber)]/15 text-[var(--semantic-amber-ink)]',
  T3: 'bg-[var(--semantic-amber)]/15 text-[var(--semantic-amber-ink)]',
  T4: 'bg-[var(--fill)] text-[var(--text-3)]',
};

function MoreButton({ open, onClick }: { open: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-expanded={open}
      className="mt-0.5 inline-flex shrink-0 items-center gap-0.5 rounded-[5px] text-[10.5px] font-semibold text-[var(--accent-ink)] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/40"
    >
      {open ? 'Less' : 'More'}
    </button>
  );
}

function GroupHeading({
  heading,
  count,
  tone,
  sub,
  testId,
  dataAttributes = {},
}: {
  /** The canonical heading string, printed verbatim (it carries the count). */
  heading: string;
  count: number;
  tone: 'red' | 'amber' | 'neutral';
  sub?: React.ReactNode;
  testId: string;
  dataAttributes?: Record<string, string | number>;
}) {
  const titleTone =
    tone === 'red'
      ? 'text-[var(--semantic-red-ink)]'
      : tone === 'amber'
      ? 'text-[var(--semantic-amber-ink)]'
      : 'text-[var(--text-1)]';
  return (
    <div
      data-testid={testId}
      data-count={count}
      {...dataAttributes}
      className="flex min-w-0 flex-wrap items-center gap-1.5"
    >
      <span className={`text-[11px] font-bold tracking-[0.06em] ${titleTone}`}>{heading}</span>
      {sub}
    </div>
  );
}

function EntryRow({
  entry,
  open,
  onToggle,
}: {
  entry: WarningEntry;
  open: boolean;
  onToggle: () => void;
}) {
  const long = entry.display.length > 120;
  return (
    <li
      data-testid="warning-row"
      data-tier={entry.tier}
      data-code={entry.code}
      data-messages={entry.occurrences}
      className="min-w-0 rounded-[8px] border border-[var(--hairline)] bg-[var(--card-bg-subtle)] px-2.5 py-2"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
        <span className={`${chip} ${tierTone[entry.tier]}`}>{entry.code}</span>
        {entry.roomId && (
          <span className={`${chip} bg-[var(--fill)] text-[var(--text-2)]`}>{entry.roomId}</span>
        )}
        {entry.floorIndex !== null && (
          <span className={`${chip} bg-[var(--fill)] text-[var(--text-3)]`}>
            F{entry.floorIndex}
          </span>
        )}
        {entry.occurrences > 1 && (
          <span
            className={`${chip} bg-[var(--fill)] text-[var(--text-3)]`}
            title={`${entry.occurrences} identical raw lines`}
          >
            ×{entry.occurrences}
          </span>
        )}
      </div>
      <div className="mt-1 flex min-w-0 items-start gap-2">
        <p
          className={`min-w-0 flex-1 break-words text-[11.5px] leading-snug text-[var(--text-2)] ${
            open ? '' : 'line-clamp-2'
          }`}
        >
          {entry.display}
        </p>
        {long && <MoreButton open={open} onClick={onToggle} />}
      </div>
    </li>
  );
}

/**
 * One LISTED DEVIATION row.  The row text is the verbatim page-1 disclosure
 * line when one exists; a structured relaxation with no page-1 row of its own
 * prints its room, rule and reason instead.  The structured records for the
 * room stay reachable behind "records" — never dropped, never double-counted.
 */
function DeviationRow({
  row,
  groups,
  open,
  onToggle,
  recordsOpen,
  onToggleRecords,
  showRecords = true,
}: {
  row: ListedDeviationRow;
  groups: RelaxationGroup[];
  open: boolean;
  onToggle: () => void;
  recordsOpen: boolean;
  onToggleRecords: () => void;
  /** False when this room's records are already shown on an earlier row. */
  showRecords?: boolean;
}) {
  const structured = showRecords && row.roomId ? groups.filter((g) => g.roomId === row.roomId) : [];
  const long = row.reason.length > 120;
  return (
    <li
      data-testid="listed-deviation-row"
      data-room={row.roomId}
      data-rule={row.ruleId}
      data-source={row.source}
      className="min-w-0 rounded-[8px] border border-[var(--semantic-amber)]/25 bg-[var(--semantic-amber)]/[0.06] px-2.5 py-2"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
        <span className={`${chip} bg-[var(--semantic-amber)]/15 text-[var(--semantic-amber-ink)]`}>
          {row.ruleId}
        </span>
        {row.roomId && (
          <span className={`${chip} bg-[var(--fill)] text-[var(--text-2)]`}>{row.roomId}</span>
        )}
        {structured.length > 0 && (
          <button
            type="button"
            onClick={onToggleRecords}
            aria-expanded={recordsOpen}
            data-testid="deviation-records-toggle"
            data-room={row.roomId}
            className="inline-flex items-center gap-0.5 rounded-[5px] bg-[var(--fill)] px-1.5 py-0.5 text-[10px] font-semibold text-[var(--text-2)] hover:text-[var(--text-1)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/40"
          >
            {recordsOpen ? 'Hide' : 'Records'} ({structured.reduce((n, g) => n + g.items.length, 0)})
          </button>
        )}
      </div>
      <div className="mt-1 flex min-w-0 items-start gap-2">
        <p
          className={`min-w-0 flex-1 break-words text-[11.5px] leading-snug text-[var(--text-2)] ${
            open ? '' : 'line-clamp-2'
          }`}
        >
          {row.reason}
        </p>
        {long && <MoreButton open={open} onClick={onToggle} />}
      </div>
      {recordsOpen &&
        structured.map((group) => (
          <ul
            key={group.roomId}
            data-testid="relaxation-records"
            data-room={group.roomId}
            className="mt-1.5 min-w-0 space-y-1 border-t border-[var(--semantic-amber)]/20 pt-1.5"
          >
            {group.items.map((item, idx) => (
              <li
                key={`${group.roomId}:${item.ruleId}:${idx}`}
                data-testid="relaxation-item"
                data-rule={item.ruleId}
                className="min-w-0"
              >
                <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                  <span className={`${chip} bg-[var(--semantic-amber)]/15 text-[var(--semantic-amber-ink)]`}>
                    {item.ruleId}
                  </span>
                  <span className="inline-flex max-w-full min-w-0 items-center rounded-[5px] bg-[var(--fill)] px-1.5 py-0.5 text-[10px] font-medium leading-tight text-[var(--text-2)]">
                    <span className="min-w-0 break-words">{item.chip}</span>
                  </span>
                  {item.factor !== null &&
                    Number.isFinite(item.factor) &&
                    !item.chip.includes(`${item.factor}x`) && (
                    <span className={`${chip} bg-[var(--fill)] text-[var(--text-3)]`}>
                      @ {item.factor}x
                    </span>
                  )}
                </div>
                <p className="mt-0.5 min-w-0 break-words text-[11px] leading-snug text-[var(--text-2)]">
                  {item.reason}
                </p>
              </li>
            ))}
          </ul>
        ))}
    </li>
  );
}

/**
 * The warning wall, replaced by an ordered truth report:
 *   verdict → CERTIFICATE FAILURES (n) → LISTED DEVIATIONS (m) →
 *   UNRESOLVED BREACHES (k) → advisories → engine log.
 *
 * Group A is read from the CERTIFICATE's own failure rows and from nothing
 * else; listed, within-cap deviations are never counted as failures.  Nothing
 * is permanently hidden: every group carries its own count, the full verbatim
 * list is one click away, and no count is inferred from a warning total.
 */
export const WarningReportView: React.FC<WarningReportViewProps> = ({
  warnings,
  relaxations = [],
  planVerdict = null,
  certificateFailures = [],
  expandAll = false,
  prebuiltReport,
}) => {
  const truthInput = useMemo<TruthLabelInput>(
    () => ({
      certificateFailures,
      listedRooms: relaxations.map((r) => r.room),
    }),
    [certificateFailures, relaxations],
  );
  const report = useMemo(
    () => prebuiltReport ?? buildWarningReport(warnings, relaxations, truthInput),
    [prebuiltReport, warnings, relaxations, truthInput],
  );
  const summary = warningSummary(report);

  const [advisoriesOpen, setAdvisoriesOpen] = useState(expandAll);
  const [operationsOpen, setOperationsOpen] = useState(expandAll);
  const [fullOpen, setFullOpen] = useState(expandAll);
  const [policyOpen, setPolicyOpen] = useState(false);
  const [openRows, setOpenRows] = useState<Record<string, boolean>>({});
  const [openRecords, setOpenRecords] = useState<Record<string, boolean>>({});
  const [deviationsOpen, setDeviationsOpen] = useState(true);
  const [breachesOpen, setBreachesOpen] = useState(true);

  const critical = planVerdict === 'NOT-CERTIFIED-FAIL-STAMP';
  const verdictText =
    planVerdict === 'NOT-CERTIFIED-FAIL-STAMP'
      ? 'Plan not certified — drawn and exported with a FAIL stamp.'
      : planVerdict === 'ADVISORY'
      ? 'Plan certified with advisories.'
      : planVerdict === 'CERTIFIED'
      ? 'Plan verified and certified.'
      : 'Plan verdict not reported.';
  const badge = critical
    ? { text: 'PLAN NOT CERTIFIED', cls: 'bg-rose-600 text-white' }
    : planVerdict === 'ADVISORY'
    ? { text: 'CERTIFIED · ADVISORIES', cls: 'bg-amber-500 text-white' }
    : { text: 'VERIFIED & CERTIFIED', cls: 'bg-emerald-600 text-white' };

  const rowOpen = (key: string) => expandAll || Boolean(openRows[key]);
  const toggleRow = (key: string) =>
    setOpenRows((prev) => ({ ...prev, [key]: !prev[key] }));
  const recordsOpen = (key: string) => expandAll || Boolean(openRecords[key]);
  const toggleRecords = (key: string) =>
    setOpenRecords((prev) => ({ ...prev, [key]: !prev[key] }));

  const truth = report.truth;

  return (
    <section
      data-testid="plan-warnings-banner"
      data-critical={critical ? 'true' : 'false'}
      data-total-messages={report.totalMessages}
      data-certificate-failure-count={truth.counts.certificateFailures}
      data-listed-deviation-count={truth.counts.listedDeviations}
      data-unresolved-breach-count={truth.counts.unresolvedBreaches}
      data-t1-count={report.tiers.T1.messages}
      data-t2-count={report.tiers.T2.messages}
      data-t3-count={report.tiers.T3.messages}
      data-t4-count={report.tiers.T4.messages}
      data-relaxation-count={report.relaxations.total}
      data-relaxation-rooms={report.relaxations.rooms}
      aria-label="Plan warning report"
      className={`mt-2.5 min-w-0 max-w-full overflow-x-clip rounded-[12px] border p-3 space-y-2.5 ${
        critical
          ? 'bg-rose-500/10 border-rose-500/30'
          : 'bg-amber-500/10 border-amber-500/25'
      }`}
    >
      {/* Verdict chip + one-line verdict */}
      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
        <Icon
          name={critical ? 'alert-triangle' : 'shield-check'}
          size={14}
          className={`shrink-0 ${
            critical
              ? 'text-[var(--semantic-red-ink)]'
              : planVerdict === 'ADVISORY'
              ? 'text-[var(--semantic-amber-ink)]'
              : 'text-[var(--semantic-green-ink)]'
          }`}
        />
        <span
          data-testid="plan-verdict"
          data-verdict={planVerdict ?? 'UNKNOWN'}
          className={`inline-flex items-center rounded-full px-2 py-0.5 text-[9.5px] font-bold uppercase tracking-wider ${badge.cls}`}
        >
          {badge.text}
        </span>
        <p className="min-w-0 flex-1 basis-[12rem] break-words text-[11.5px] font-medium leading-snug text-[var(--text-1)]">
          {verdictText}
        </p>
      </div>

      {/* Summary == the groups below (counts come from one report). */}
      <p
        data-testid="warning-summary"
        data-total={report.totalMessages}
        data-certificate-failures={truth.counts.certificateFailures}
        data-listed-deviations={truth.counts.listedDeviations}
        data-unresolved-breaches={truth.counts.unresolvedBreaches}
        data-t1={report.tiers.T1.messages}
        data-t2={report.tiers.T2.messages}
        data-t3={report.tiers.T3.messages}
        data-t4={report.tiers.T4.messages}
        className="min-w-0 break-words text-[10.5px] font-medium leading-snug text-[var(--text-3)]"
      >
        {summary.truthLine}
      </p>
      <p
        data-testid="warning-summary-detail"
        className="min-w-0 break-words text-[10px] leading-snug text-[var(--text-3)]"
      >
        {summary.totalLine}
      </p>

      {/* GROUP A — CERTIFICATE FAILURES (n): the certificate's own rows, only. */}
      <div data-testid="certificate-failures-group" className="min-w-0 space-y-1.5">
        <GroupHeading
          heading={truth.headings.certificateFailures}
          count={truth.counts.certificateFailures}
          tone={truth.counts.certificateFailures > 0 ? 'red' : 'neutral'}
          testId="certificate-failures-heading"
          sub={
            <span className="text-[10px] text-[var(--text-3)]">
              from the certificate — rows this project failed, never a warning total
            </span>
          }
        />
        <ul
          data-testid="certificate-failures-list"
          data-count={truth.counts.certificateFailures}
          className="min-w-0 space-y-1.5 pl-0"
        >
          {truth.certificateFailures.map((failure, idx) => (
            <li
              key={`${idx}:${failure}`}
              data-testid="certificate-failure-row"
              className="min-w-0 rounded-[8px] border border-[var(--semantic-red)]/25 bg-[var(--semantic-red)]/[0.06] px-2.5 py-2"
            >
              <p className="min-w-0 break-words text-[11.5px] leading-snug text-[var(--text-2)]">
                {failure}
              </p>
            </li>
          ))}
          {truth.certificateFailures.length === 0 && (
            <li
              data-testid="certificate-failures-empty"
              className="rounded-[8px] border border-[var(--hairline)] px-2.5 py-2 text-[11.5px] text-[var(--text-2)]"
            >
              None — the certificate records no failing invariant for this plan.
            </li>
          )}
        </ul>
      </div>

      {/* GROUP B — LISTED DEVIATIONS (m): listed, within-cap relaxations. */}
      <div
        data-testid="listed-deviations-group"
        className="min-w-0 border-t border-[var(--hairline)] pt-2 space-y-1.5"
      >
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => setDeviationsOpen((v) => !v)}
            aria-expanded={deviationsOpen}
            data-testid="deviations-toggle"
            className="inline-flex min-w-0 items-center gap-1.5 rounded-[6px] text-[11px] font-bold uppercase tracking-[0.06em] text-[var(--semantic-amber-ink)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/40"
          >
            <Icon
              name="chevron-down"
              size={12}
              className={`shrink-0 transition-transform ${deviationsOpen ? 'rotate-180' : ''}`}
            />
            <span className="min-w-0 break-words">{truth.headings.listedDeviations}</span>
          </button>
          <span className="text-[10px] text-[var(--text-3)]">
            {truth.structuredRelaxations} structured relaxation
            {truth.structuredRelaxations === 1 ? '' : 's'} · {truth.listedDeviationRooms} room
            {truth.listedDeviationRooms === 1 ? '' : 's'}
          </span>
          {/* The 200-char policy is explained ONCE, outside every row. */}
          <div className="relative min-w-0">
            <button
              type="button"
              data-testid="relaxation-policy-toggle"
              aria-expanded={policyOpen}
              onClick={() => setPolicyOpen((v) => !v)}
              className="inline-flex items-center gap-1 rounded-full bg-[var(--fill)] px-2 py-0.5 text-[10px] font-semibold text-[var(--text-2)] hover:text-[var(--text-1)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/40"
            >
              <Icon name="info" size={11} />
              Policy
            </button>
            {policyOpen && (
              <div
                role="note"
                data-testid="relaxation-policy"
                className="absolute left-0 top-full z-20 mt-1 w-[min(22rem,100%)] max-w-full break-words rounded-[10px] border border-[var(--panel-border-color)] bg-[var(--surface)] p-2.5 text-[10.5px] leading-snug text-[var(--text-2)] shadow-xl"
              >
                <p className="font-semibold text-[var(--text-1)]">Relaxation policy</p>
                <p className="mt-1">{report.relaxations.policy}</p>
                {report.relaxations.policyFromEngine && (
                  <p className="mt-1 text-[10px] text-[var(--text-3)]">
                    The repeated tail above was removed from every row and is shown here once.
                  </p>
                )}
              </div>
            )}
          </div>
        </div>

        {deviationsOpen && (
          <ul
            data-testid="listed-deviations-list"
            data-count={truth.counts.listedDeviations}
            className="min-w-0 space-y-1.5"
          >
            {truth.listedDeviations.map((row, idx) => {
              const key = `${row.roomId}:${row.ruleId}:${row.page1Row ?? idx}`;
              // The structured records for a room are shown once, on the
              // first row that names it — never repeated per disclosure line.
              const firstForRoom =
                !row.roomId ||
                truth.listedDeviations.findIndex((d) => d.roomId === row.roomId) === idx;
              return (
                <DeviationRow
                  key={key}
                  row={row}
                  groups={report.relaxations.groups}
                  open={rowOpen(key)}
                  onToggle={() => toggleRow(key)}
                  recordsOpen={recordsOpen(key)}
                  onToggleRecords={() => toggleRecords(key)}
                  showRecords={firstForRoom}
                />
              );
            })}
            {truth.listedDeviations.length === 0 && (
              <li className="text-[11.5px] text-[var(--text-2)]">
                No listed deviation: this plan uses no bounded relaxation.
              </li>
            )}
          </ul>
        )}
      </div>

      {/* GROUP C — UNRESOLVED BREACHES (k): the rows a FAIL stamp rests on. */}
      <div
        data-testid="unresolved-breaches-group"
        className="min-w-0 border-t border-[var(--hairline)] pt-2 space-y-1.5"
      >
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => setBreachesOpen((v) => !v)}
            aria-expanded={breachesOpen}
            data-testid="breaches-toggle"
            className="inline-flex min-w-0 items-center gap-1.5 rounded-[6px] text-[11px] font-bold uppercase tracking-[0.06em] text-[var(--semantic-red-ink)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/40"
          >
            <Icon
              name="chevron-down"
              size={12}
              className={`shrink-0 transition-transform ${breachesOpen ? 'rotate-180' : ''}`}
            />
            <span className="min-w-0 break-words">{truth.headings.unresolvedBreaches}</span>
          </button>
          <span className="text-[10px] text-[var(--text-3)]">
            {report.tiers.T1.entries} distinct line{report.tiers.T1.entries === 1 ? '' : 's'}
          </span>
        </div>
        {breachesOpen && (
          <ul
            data-testid="unresolved-breaches-list"
            data-count={truth.counts.unresolvedBreaches}
            className="min-w-0 space-y-1.5 pl-0"
          >
            {report.failures.map((entry) => (
              <EntryRow
                key={entry.key}
                entry={entry}
                open={rowOpen(entry.key)}
                onToggle={() => toggleRow(entry.key)}
              />
            ))}
            {report.failures.length === 0 && (
              <li
                data-testid="unresolved-breaches-empty"
                className="rounded-[8px] border border-[var(--hairline)] px-2.5 py-2 text-[11.5px] text-[var(--text-2)]"
              >
                None — every plan row is either listed or disclosed as an advisory.
              </li>
            )}
          </ul>
        )}
      </div>

      {/* T3 — advisories, collapsed with a count */}
      <div
        data-testid="warning-advisories"
        data-count={report.tiers.T3.messages}
        className="min-w-0 border-t border-[var(--hairline)] pt-2"
      >
        <button
          type="button"
          data-testid="advisories-toggle"
          aria-expanded={advisoriesOpen}
          onClick={() => setAdvisoriesOpen((v) => !v)}
          className="inline-flex w-full min-w-0 flex-wrap items-center gap-1.5 rounded-[6px] text-left text-[11.5px] font-semibold text-[var(--text-1)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/40"
        >
          <Icon
            name="chevron-down"
            size={12}
            className={`shrink-0 text-[var(--text-3)] transition-transform ${
              advisoriesOpen ? 'rotate-180' : ''
            }`}
          />
          <span>{report.tiers.T3.messages} advisor{report.tiers.T3.messages === 1 ? 'y' : 'ies'}</span>
          <span className="font-normal text-[var(--text-3)]">· waste, rotation, rule and ideal-band notices</span>
        </button>
        {advisoriesOpen && (
          <ul className="mt-1.5 min-w-0 space-y-1.5">
            {report.advisories.map((entry) => (
              <EntryRow
                key={entry.key}
                entry={entry}
                open={rowOpen(entry.key)}
                onToggle={() => toggleRow(entry.key)}
              />
            ))}
          </ul>
        )}
      </div>

      {/* T4 — engine operations, collapsed and excluded from warning counts */}
      <div
        data-testid="warning-operations"
        data-count={report.tiers.T4.messages}
        className="min-w-0 border-t border-[var(--hairline)] pt-2"
      >
        <button
          type="button"
          data-testid="operations-toggle"
          aria-expanded={operationsOpen}
          onClick={() => setOperationsOpen((v) => !v)}
          className="inline-flex w-full min-w-0 flex-wrap items-center gap-1.5 rounded-[6px] text-left text-[11.5px] font-semibold text-[var(--text-1)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/40"
        >
          <Icon
            name="chevron-down"
            size={12}
            className={`shrink-0 text-[var(--text-3)] transition-transform ${
              operationsOpen ? 'rotate-180' : ''
            }`}
          />
          <span>
            Engine operations log ({report.tiers.T4.messages})
          </span>
          <span className="font-normal text-[var(--text-3)]">
            · swing resolutions, wet stacks, buffers — not warnings
          </span>
        </button>
        {operationsOpen && (
          <ul data-testid="operations-list" className="mt-1.5 min-w-0 space-y-1.5">
            {report.operations.map((entry) => (
              <EntryRow
                key={entry.key}
                entry={entry}
                open={rowOpen(entry.key)}
                onToggle={() => toggleRow(entry.key)}
              />
            ))}
          </ul>
        )}
      </div>

      {/* Full verbatim disclosure — one click, never removed */}
      <div className="min-w-0 border-t border-[var(--hairline)] pt-2">
        <button
          type="button"
          data-testid="full-list-toggle"
          aria-expanded={fullOpen}
          onClick={() => setFullOpen((v) => !v)}
          className="inline-flex min-w-0 flex-wrap items-center gap-1.5 rounded-[6px] text-left text-[11px] font-semibold text-[var(--accent-ink)] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)]/40"
        >
          <Icon name="file-text" size={12} className="shrink-0" />
          {fullOpen ? 'Hide the full message list' : `View all ${report.totalMessages} messages`}
        </button>
        {fullOpen && (
          <ol
            data-testid="full-message-list"
            data-count={report.totalMessages}
            className="mt-1.5 min-w-0 space-y-1"
          >
            {report.fullList.map((m) => (
              <li
                key={m.index}
                data-testid="full-message"
                data-tier={m.tier}
                className="flex min-w-0 items-start gap-1.5 rounded-[6px] px-1 py-0.5 text-[10.5px] leading-snug text-[var(--text-2)]"
              >
                <span className={`${chip} ${tierTone[m.tier]}`}>{m.code}</span>
                <span className="min-w-0 break-words">{m.raw}</span>
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
};
