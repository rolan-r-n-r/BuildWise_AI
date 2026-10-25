/**
 * Manual-coordinate guard.
 *
 * The latitude/longitude inputs used to accept a swap silently: entering
 * 77.59219 / 12.97425 for a Bengaluru site moved the pin to the Arctic Ocean
 * without a word.  The guard never hard-rejects a coordinate — a legitimate
 * project can be far from the last pin — it only decides when the UI must ask
 * for confirmation, and says exactly why.
 */

/** A manual pin further than this from the current one needs confirmation. */
export const FAR_MOVE_WARNING_KM = 500;

const EARTH_RADIUS_KM = 6371.0088;

const toRadians = (deg: number): number => (deg * Math.PI) / 180;

/** Great-circle distance in kilometres. */
export function haversineKm(
  latA: number,
  lonA: number,
  latB: number,
  lonB: number,
): number {
  const dLat = toRadians(latB - latA);
  const dLon = toRadians(lonB - lonA);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRadians(latA)) * Math.cos(toRadians(latB)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(a)));
}

export type CoordinateGuardTrigger = 'distance' | 'water';

export interface CoordinateGuardResult {
  needsConfirmation: boolean;
  triggers: CoordinateGuardTrigger[];
  distanceKm: number | null;
  message: string | null;
}

export interface CoordinateGuardInput {
  lat: number;
  lon: number;
  /** The pin currently in force; null when the user has not placed one yet. */
  currentLat?: number | null;
  currentLon?: number | null;
  /** Result of the reverse-geocode water probe (false when it could not run). */
  water?: boolean;
  waterName?: string | null;
}

export function evaluateManualCoordinate({
  lat,
  lon,
  currentLat,
  currentLon,
  water = false,
  waterName = null,
}: CoordinateGuardInput): CoordinateGuardResult {
  const triggers: CoordinateGuardTrigger[] = [];
  const reasons: string[] = [];
  let distanceKm: number | null = null;

  if (
    typeof currentLat === 'number' &&
    typeof currentLon === 'number' &&
    Number.isFinite(currentLat) &&
    Number.isFinite(currentLon)
  ) {
    distanceKm = haversineKm(currentLat, currentLon, lat, lon);
    if (distanceKm > FAR_MOVE_WARNING_KM) {
      triggers.push('distance');
      reasons.push(
        `This pin is ${Math.round(distanceKm).toLocaleString()} km from the current site.`,
      );
    }
  }

  if (water) {
    triggers.push('water');
    reasons.push(
      `The reverse lookup places this point in ${waterName || 'open water'}.`,
    );
  }

  if (triggers.length === 0) {
    return { needsConfirmation: false, triggers, distanceKm, message: null };
  }

  return {
    needsConfirmation: true,
    triggers,
    distanceKm,
    message: `${reasons.join(' ')} The latitude and longitude may be swapped or offshore — confirm the pin before it replaces the current site.`,
  };
}
