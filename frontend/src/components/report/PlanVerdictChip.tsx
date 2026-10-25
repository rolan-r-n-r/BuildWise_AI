import React from 'react';
import { Icon } from '../Icon';

interface PlanVerdictChipProps {
  /** The server-computed verdict; rendered verbatim when present. */
  verdict?: string | null;
  /** `mathematical_certificate.is_valid`; null/undefined means not reported. */
  isValid?: boolean | null;
  /** `validation_gate.overall_status`; only FAIL withholds certification. */
  gateStatus?: string | null;
}

/**
 * Refusal header fact: a withheld certificate or a FAILed gate is not a detail
 * to be buried in the QA panel. The plan is still drawn and exported, and this
 * chip keeps it from ever being mistaken for certified. A WARN gate never
 * receives the treatment — advisories are disclosed, not refused.
 */
export const PlanVerdictChip: React.FC<PlanVerdictChipProps> = ({ verdict, isValid, gateStatus }) => {
  // The verdict is the server's; the legacy flags are only a fallback for
  // payloads generated before the field existed.
  const notCertified =
    verdict === 'NOT-CERTIFIED-FAIL-STAMP' ||
    (verdict === undefined &&
      (isValid === false || String(gateStatus || '').toUpperCase() === 'FAIL'));
  if (!notCertified) return null;
  return (
    <span
      data-testid="viewer-not-certified-chip"
      data-verdict={verdict || 'NOT-CERTIFIED-FAIL-STAMP'}
      title="The plan is drawn but not certified; see the certificate and deficit banner below."
      className="font-mono text-[10px] sm:text-[11px] font-bold text-white bg-rose-600 px-2 py-0.5 rounded-[6px] whitespace-nowrap flex items-center gap-1.5 select-none"
    >
      <Icon name="alert-triangle" size={12} className="shrink-0" />
      <span>{verdict || 'NOT CERTIFIED'}</span>
    </span>
  );
};
