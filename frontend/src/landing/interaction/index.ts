/**
 * landing/interaction — the landing's interaction system.
 *
 * Seven primitives, each with a PURE core and a React binding:
 *
 *   P1 springs      `springs.ts`      presets with measured settle times, the
 *                                     transform-only guard, the damped follow
 *   P2 parallax     `pointer.ts`      normalized+clamped pointer maths, and the
 *                                     device-tilt equivalent for touch
 *   P3 tilt/light   `pointer.ts`      card tilt (≤ maxDeg) and the specular offset
 *   P4 scrub        `scrub.ts`        entry/set-piece bands, damping, no-jitter
 *   P5 drag         `drag.ts`         ring drag + keyboard nudge, clamped to frame
 *   P6 sticky stage `stage.ts`        strictly ordered beats over one progress
 *   P7 capability   `capability.ts`   four flags → documented degradations, dpr cap
 *
 * `hooks.ts` holds the React bindings for all seven. The split is not stylistic:
 * this repository's unit tests are plain node scripts with type stripping, so a
 * module that imports framer-motion or touches the DOM cannot be loaded there.
 * The cores import nothing, which is what lets `test_interaction_primitives.cjs`
 * MEASURE the spring settle times rather than trusting a comment about them.
 *
 * Consumers should import from here rather than from the individual files, so
 * the landing sections and the prototype share one spelling of every primitive.
 */
export * from './capability';
export * from './springs';
export * from './pointer';
export * from './geometry';
export * from './drag';
export * from './scrub';
export * from './stage';
export * from './hooks';
