#!/usr/bin/env node
/**
 * test_validation_guards.cjs — validation and disclosure pins.
 * ==============================================================================
 * Repo dialect: plain-node assertions, Vite's SSR loader for the TS modules.
 *
 *   1. A swapped or offshore manual coordinate needs confirmation;
 *      a nearby coordinate does not; water alone triggers; the 500 km edge is
 *      exclusive.
 *   2. A single-storey plan's programme summary resolves the first
 *      floor even though the floor switcher stays off.
 *   3. The banner counts only the page-1 plan lines (15-line
 *      fixture -> 6 plan / 9 resolver; a 40-line log keeps the same 6).
 *   4. The card renders the server-generated formula verbatim and never
 *      falls back to the old hand-copied slope table.
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
let failures = 0;
let passes = 0;

function check(cond, label, detail) {
  if (cond) {
    passes++;
    console.log(`  ok   ${label}`);
  } else {
    failures++;
    console.log(`  FAIL ${label}${detail ? ` — ${detail}` : ''}`);
  }
}

/** A 15-line solver log fixture: 6 plan warnings + 9 resolver notes. */
const SOLVER_LOG_15 = [
  "RULE-FP-02: Wing 'wing_b' not present in footprint decomposition (single-rectangle plate) - floor plate mask for level 0 ignored.",
  'PROP-SPLIT: living split into 2 parts (aspect 1:2.38 over the 1:1.80 hard band); each part is inside the declared band.',
  'PROP-CEILING: bath_1 is 9.8 m² against its 8.0 m² declared ceiling; sanitary rooms are governed by fixture fit and are disclosed, not subdivided.',
  'PROP-IDEAL: bath_1 aspect 1:1.80 is outside the 1:1.50 ideal band but inside the 1:2.00 hard band (WARN).',
  'ROOM-MAX: dining_0_1 is 19.1 m², above its 14.0 m² catalogue maximum on floor 0; the 78.2 m² plate stretched it past its band.',
  'ROOM-MAX: bath_1 is 9.8 m², above its 6.0 m² catalogue maximum on floor 0; the 78.2 m² plate stretched it past its band.',
  "Swing resolution: Flipped door 'door_bath_1' (1.28,4.00,inward_right -> 1.28,4.00,inward_left).",
  "Swing resolution: Flipped door 'door_master_bed' (2.48,4.00,inward_right -> 2.48,4.00,inward_left).",
  "Swing resolution: Flipped door 'door_kitchen' (6.70,4.00,inward_right -> 6.70,4.00,inward_left).",
  'CIRC-REPAIR: added a door living -> dining_0_1 so no room is unreachable from the entry',
  "Swing resolution: Flipped door 'main_entry' (1.88,0.00,inward_right -> 1.88,0.00,inward_right).",
  "Swing resolution: Converted door 'main_entry' to sliding buffer (unresolvable arc conflict).",
  "Swing resolution: Flipped door 'door_circulation_repair_dining_0_1' (4.77,1.55,inward_right -> 4.77,1.55,inward_left).",
  'LAND-03 Circulation ratio 0.0% is outside the 12–20% target band.',
  'PLINTH: the built-up target (78.2 m²) exceeds the programme need (59.5 m²); the declared upgrade ladder absorbed 0.0 m² and 18.8 m² is left unbuilt.',
];

async function main() {
  const { createServer } = await import('vite');
  const server = await createServer({
    root: ROOT,
    logLevel: 'error',
    appType: 'custom',
    server: { middlewareMode: true },
  });

  try {
    const {
      haversineKm,
      evaluateManualCoordinate,
      FAR_MOVE_WARNING_KM,
    } = await server.ssrLoadModule('/src/services/coordinateGuard.ts');
    const { resolveProgrammeFloor } = await server.ssrLoadModule('/src/services/typologyProgramme.ts');
    const { splitPlanWarnings, planWarningsHeadline } = await server.ssrLoadModule('/src/services/planWarnings.ts');
    const {
      methodologyFormula,
      NO_GENERATED_METHODOLOGY,
    } = await server.ssrLoadModule('/src/services/methodologyText.ts');

    // ----------------------------------------------------------------------- //
    console.log('\n[1] Manual coordinate confirmation');
    const BLR = { lat: 12.97425, lon: 77.59219 };
    const swapped = evaluateManualCoordinate({
      lat: 77.59219,
      lon: 12.97425,
      currentLat: BLR.lat,
      currentLon: BLR.lon,
    });
    check(swapped.needsConfirmation, 'swapped lat/lon requires confirmation');
    check(swapped.triggers.includes('distance'), 'swap is reported as a far move');
    check(
      (swapped.distanceKm ?? 0) > 7000,
      'swap distance is intercontinental',
      String(swapped.distanceKm),
    );
    check(
      /swapped or offshore/i.test(swapped.message || ''),
      'confirmation names the swap/offshore risk',
    );

    const same = evaluateManualCoordinate({ ...BLR, currentLat: BLR.lat, currentLon: BLR.lon });
    check(!same.needsConfirmation && same.distanceKm === 0, 'same coordinate applies silently');

    const nearby = evaluateManualCoordinate({
      lat: BLR.lat + 0.1,
      lon: BLR.lon + 0.1,
      currentLat: BLR.lat,
      currentLon: BLR.lon,
    });
    check(!nearby.needsConfirmation, 'a 15 km move does not ask');

    const justOver = evaluateManualCoordinate({
      lat: BLR.lat + FAR_MOVE_WARNING_KM / 111.195 + 0.01,
      lon: BLR.lon,
      currentLat: BLR.lat,
      currentLon: BLR.lon,
    });
    check(
      justOver.distanceKm > FAR_MOVE_WARNING_KM && justOver.needsConfirmation,
      'just over the 500 km line asks',
      String(justOver.distanceKm),
    );
    const justUnder = evaluateManualCoordinate({
      lat: BLR.lat + FAR_MOVE_WARNING_KM / 111.195 - 0.01,
      lon: BLR.lon,
      currentLat: BLR.lat,
      currentLon: BLR.lon,
    });
    check(
      justUnder.distanceKm < FAR_MOVE_WARNING_KM && !justUnder.needsConfirmation,
      'just under the 500 km line passes',
      String(justUnder.distanceKm),
    );

    const offshore = evaluateManualCoordinate({
      lat: BLR.lat,
      lon: BLR.lon,
      currentLat: BLR.lat,
      currentLon: BLR.lon,
      water: true,
      waterName: 'Arabian Sea',
    });
    check(offshore.needsConfirmation && offshore.triggers.includes('water'), 'open water requires confirmation');
    check(/Arabian Sea/.test(offshore.message || ''), 'confirmation names the water body');

    const both = evaluateManualCoordinate({
      lat: 77.59219,
      lon: 12.97425,
      currentLat: BLR.lat,
      currentLon: BLR.lon,
      water: true,
      waterName: 'Arctic Ocean',
    });
    check(
      both.triggers.includes('distance') && both.triggers.includes('water'),
      'both triggers are reported together',
    );
    check(
      Math.abs(haversineKm(BLR.lat, BLR.lon, BLR.lat, BLR.lon)) < 1e-9,
      'haversine zero-distance is exact',
    );

    // ----------------------------------------------------------------------- //
    console.log('\n[2] Single-storey programme summary');
    const groundFloor = {
      floor_index: 0,
      floor_name: 'Ground Floor (G)',
      rooms: [
        { room_id: 'living_F0', room_name: 'Living', zone_category: 'public', space_type_id: 'living' },
        { room_id: 'master_bed_F0', room_name: 'Master Bedroom', zone_category: 'private', space_type_id: 'master_bed' },
        { room_id: 'bath_1', room_name: 'Bathroom', zone_category: 'service', space_type_id: 'bath_1' },
      ],
    };
    check(
      resolveProgrammeFloor(null, [groundFloor]) === groundFloor,
      'single-storey plan falls back to floors[0]',
    );
    check(resolveProgrammeFloor(null, []) === null, 'no floors stays null');
    const other = { ...groundFloor, floor_index: 1 };
    check(
      resolveProgrammeFloor(other, [groundFloor]) === other,
      'the current floor still wins when present',
    );

    const { summariseFloorProgramme, formatProgrammeCounts } = await server.ssrLoadModule(
      '/src/services/typologyProgramme.ts',
    );
    const resolved = resolveProgrammeFloor(null, [groundFloor]);
    const counts = summariseFloorProgramme(resolved);
    check(counts.length > 0, 'resolved single-storey programme is not empty');
    check(
      /bedroom|bathroom|living/.test(formatProgrammeCounts(counts)),
      'programme text names the rooms',
      formatProgrammeCounts(counts),
    );

    // ----------------------------------------------------------------------- //
    console.log('\n[3] The banner counts what its label names');
    const split15 = splitPlanWarnings(SOLVER_LOG_15);
    check(split15.planWarnings.length === 6, '15-line log -> 6 plan warnings', String(split15.planWarnings.length));
    check(split15.resolverNotes.length === 9, '15-line log -> 9 resolver notes', String(split15.resolverNotes.length));
    check(
      split15.planWarnings.every((w) => !/^Swing resolution|^CIRC-REPAIR|^RULE-FP-02|^LAND-03/.test(w)),
      'no resolver line is counted as a plan warning',
    );
    check(
      split15.resolverNotes.some((w) => w.startsWith('Swing resolution')) &&
        split15.resolverNotes.some((w) => w.startsWith('LAND-03')),
      'resolver notes keep the full solver log',
    );

    const SOLVER_LOG_40 = [
      ...SOLVER_LOG_15,
      ...Array.from(
        { length: 25 },
        (_, i) => `Swing resolution: Flipped door 'extra_${i}' (1.00,2.00,inward_right -> 1.00,2.00,inward_left).`,
      ),
    ];
    const split40 = splitPlanWarnings(SOLVER_LOG_40);
    check(
      split40.planWarnings.length === 6 && split40.resolverNotes.length === 34,
      '40-line log keeps 6 plan / 34 resolver',
      `${split40.planWarnings.length}/${split40.resolverNotes.length}`,
    );
    check(
      planWarningsHeadline(6, 9) === 'Plan warnings (6)',
      'headline counts the plan list, not the log',
      planWarningsHeadline(6, 9),
    );
    check(
      planWarningsHeadline(0, 3) === 'Resolver notes (3)',
      'resolver-only plan is labelled as resolver notes',
    );
    check(
      !/non-compliance/.test(planWarningsHeadline(6, 9)),
      'headline no longer claims all lines are non-compliance',
    );

    // ----------------------------------------------------------------------- //
    console.log('\n[4] Methodology text is the server sentence');
    const SENTINEL = 'Piecewise linear score: SENTINEL ROW A; SENTINEL ROW B.';
    check(
      methodologyFormula('slope', { slope: SENTINEL }) === SENTINEL,
      'card helper returns the server string verbatim',
    );
    check(
      methodologyFormula('slope', {}) === NO_GENERATED_METHODOLOGY,
      'missing server text falls back to an explicit no-formula note',
    );
    check(
      !/≤2%|100 at/.test(methodologyFormula('slope', {})),
      'fallback never restates a band table',
    );
    check(
      methodologyFormula('slope', { slope: '   ' }) === NO_GENERATED_METHODOLOGY,
      'blank server text is not rendered as a formula',
    );

    const cardSource = fs.readFileSync(
      path.join(ROOT, 'src/components/report/ProvenanceFactorCard.tsx'),
      'utf8',
    );
    check(
      cardSource.includes("methodologyFormula('slope', generatedMethodology)"),
      'slope card consumes the generated text',
    );
    check(!cardSource.includes('100 at ≤2%'), 'old hand-copied slope table is gone');

    // ----------------------------------------------------------------------- //
    console.log('\n[5] A 422 keeps its field-level detail');
    const { parseApiErrorDetail } = await server.ssrLoadModule('/src/services/api.ts');
    const detailed = parseApiErrorDetail(
      [
        {
          type: 'value_error',
          loc: ['body'],
          msg: "Value error, partition_variant='duplex' needs an even number of storeys so every dwelling has its paired upper level.",
          input: { floors: 3 },
        },
      ],
      'Fallback message',
    );
    check(
      detailed.message.includes('even number of storeys'),
      'the validation message is readable, not [object Object]',
      detailed.message,
    );
    check(!detailed.message.includes('[object Object]'), 'the detail array is never stringified raw');
    check(detailed.issues.length === 1, 'one rejected rule becomes one issue');

    const nested = parseApiErrorDetail(
      [{ loc: ['body', 'request', 'floors'], msg: 'Input should be a valid integer' }],
      'Fallback',
    );
    check(nested.issues[0].startsWith('request.floors:'), 'nested field path is preserved', nested.issues[0]);
    check(
      parseApiErrorDetail('Plain server message', 'Fallback').message === 'Plain server message',
      'a plain string detail is preserved verbatim',
    );

    // Structural pins for the two behaviours that cannot be exercised without
    // a live 422: the request snapshot is committed only on success, and the
    // rejected field list renders for the user.
    const generatorSource = fs.readFileSync(
      path.join(ROOT, 'src/components/FloorPlanGeneratorCard.tsx'),
      'utf8',
    );
    const successIndex = generatorSource.indexOf('const resp = await generateFloorPlan');
    const snapshotIndex = generatorSource.indexOf('setLastRequest(finalReq)');
    check(successIndex > 0 && snapshotIndex > successIndex, 'lastRequest is written after a successful solve');
    check(
      !/setLastRequest\(finalReq\);\s*const controller = new AbortController/.test(generatorSource),
      'a failed generation no longer becomes the remediation request snapshot',
    );
    check(
      generatorSource.includes('floorplan-validation-issues'),
      'the rejected field list is rendered to the user',
    );
    check(
      generatorSource.includes("finalReq.partition_variant === 'duplex'") &&
        generatorSource.includes('finalReq.floors % 2 === 1'),
      'the card refuses an odd-storey duplex before sending a 422',
    );
  } finally {
    await server.close();
  }

  console.log(`\n${passes} passed, ${failures} failed`);
  if (failures > 0) process.exit(1);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
