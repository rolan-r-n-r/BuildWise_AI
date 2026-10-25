import type { MultiFloorRoomRectangle, MultiStoreyBuildingModel, SingleFloorPlanModel } from './types';
import { getTypologyConfig, normalizeTypology, type CanonicalTypology } from './typology';

export type UseClass = 'Residential' | 'Commercial' | 'Industrial & Logistics';

export interface TypologyProfile {
  canonical: CanonicalTypology;
  label: string;
  shortCode: string;
  useClass: UseClass;
  occupancy: string;
  intent: string;
}

export interface ProgrammeCount {
  label: string;
  count: number;
}

const PROFILES: Record<CanonicalTypology, Omit<TypologyProfile, 'canonical' | 'label' | 'shortCode'>> = {
  T1_SINGLE_FAMILY: {
    useClass: 'Residential',
    occupancy: 'Single household',
    intent: 'A single-family residence with private rooms, one kitchen and a private stair when stacked.',
  },
  T2_FAMILY_APARTMENT: {
    useClass: 'Residential',
    occupancy: 'Multi-unit apartments',
    intent: 'A multi-family apartment floor with repeated units sharing one stair and floor lobby.',
  },
  T3_LARGE_COMPLEX: {
    useClass: 'Commercial',
    occupancy: 'Commercial suites / offices',
    intent: 'A commercial floor of office suites, shared core, restrooms and service rooms.',
  },
  T4_WAREHOUSE: {
    useClass: 'Industrial & Logistics',
    occupancy: 'Warehouse & logistics',
    intent: 'A warehouse facility with a clear-span storage bay, dock, dispatch buffer and admin mezzanine.',
  },
};

export function getTypologyProfile(raw?: string): TypologyProfile {
  const config = getTypologyConfig(raw);
  return {
    canonical: config.canonical,
    label: config.label,
    shortCode: config.shortCode,
    ...PROFILES[config.canonical],
  };
}

function spaceId(room: MultiFloorRoomRectangle): string {
  return room.identity?.space_type_id || room.space_type_id || room.room_id.replace(/_F\d+$/, '');
}

function identityName(room: MultiFloorRoomRectangle): string {
  return room.identity?.name || room.room_name;
}

/**
 * Count the generated programme using ontology space types, not display names.
 * This is what lets the blueprint say "2 bedrooms · 2 kitchens" and stay true
 * for T1 houses, T2 apartments, T3 offices and T4 warehouses alike.
 */
export function summariseFloorProgramme(floor: SingleFloorPlanModel | null | undefined): ProgrammeCount[] {
  if (!floor) return [];
  const buckets: ProgrammeCount[] = [];
  const add = (label: string, count: number) => {
    if (count > 0) buckets.push({ label, count });
  };

  let bedrooms = 0;
  let bathrooms = 0;
  let kitchens = 0;
  let living = 0;
  let offices = 0;
  let storage = 0;
  let docks = 0;
  let other = 0;

  for (const room of floor.rooms) {
    const sid = spaceId(room);
    const name = identityName(room).toLowerCase();
    if (['master_bed', 'bed_2', 'unit_bed', 'guest_bed'].includes(sid) || (name.includes('bedroom') && !name.includes('bath'))) {
      bedrooms += 1;
    } else if (['bath_1', 'bath_2', 'unit_bath', 'bath_master', 'powder_room'].includes(sid) || name.includes('bath') || name.includes('restroom') || name.includes('wc')) {
      bathrooms += 1;
    } else if (sid.includes('kitchen') || name.includes('kitchen')) {
      kitchens += 1;
    } else if (['living', 'dining', 'unit_living'].includes(sid) || name.includes('living') || name.includes('dining')) {
      living += 1;
    } else if (
      sid === 'commercial_suite' ||
      sid.includes('office') ||
      sid.includes('conference') ||
      sid.includes('meeting') ||
      name.includes('office') ||
      name.includes('suite')
    ) {
      offices += 1;
    } else if (sid.includes('storage') || sid === 'warehouse_bay' || sid === 'heavy_bay' || sid === 'racked_storage') {
      storage += 1;
    } else if (sid.includes('dock')) {
      docks += 1;
    } else if (room.zone_category !== 'circulation' && room.zone_category !== 'terrace') {
      other += 1;
    }
  }

  add('bedroom', bedrooms);
  add('bathroom', bathrooms);
  add('kitchen', kitchens);
  add('living/dining', living);
  add('office/suite', offices);
  add('storage bay', storage);
  add('dock', docks);
  add('support space', other);
  return buckets;
}

/**
 * Which plate supplies the header's programme summary.
 *
 * `currentFloor` is null for every single-storey plan (the floor switcher is
 * gated on `floors.length > 1`), which made the header claim "no rooms on this
 * floor" beside the room chips it had just listed.  The summary
 * therefore falls back to the first floor without enabling the switcher.
 */
export function resolveProgrammeFloor(
  currentFloor: SingleFloorPlanModel | null | undefined,
  floors: readonly SingleFloorPlanModel[] | null | undefined,
): SingleFloorPlanModel | null {
  if (currentFloor) return currentFloor;
  return floors && floors.length > 0 ? floors[0] : null;
}

export function formatProgrammeCounts(counts: ProgrammeCount[]): string {
  return counts
    .map(({ label, count }) => `${count} ${label}${count === 1 ? '' : 's'}`)
    .join(' · ');
}

export function unitCountForFloor(floor: SingleFloorPlanModel | null | undefined): number {
  if (!floor) return 0;
  const units = new Set<string>();
  for (const room of floor.rooms) {
    if (room.unit_id) units.add(room.unit_id);
  }
  return units.size;
}

export function generatedTypologyMatches(
  building: MultiStoreyBuildingModel | null | undefined,
  requestedTypology?: string
): boolean {
  if (!building || !requestedTypology) return true;
  return normalizeTypology(building.building_typology) === normalizeTypology(requestedTypology);
}
