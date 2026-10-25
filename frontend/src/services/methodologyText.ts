/**
 * Which methodology sentence a factor card may show.
 *
 * The slope formula is generated server-side from the same band table the
 * engine evaluates (`backend/app/services/methodology.py`) and shipped as
 * `analysis.methodology[factorId]`.  A payload without it gets an
 * explicit "not supplied" sentence, never a hand-copied band table that can
 * drift from the calculation.
 */
export const NO_GENERATED_METHODOLOGY =
  'No generated methodology was supplied with this analysis; the formula is not restated here.';

export function methodologyFormula(
  factorId: string,
  generated?: Record<string, string> | null,
): string {
  const fromServer = generated?.[factorId];
  if (typeof fromServer === 'string' && fromServer.trim().length > 0) {
    return fromServer.trim();
  }
  return NO_GENERATED_METHODOLOGY;
}
