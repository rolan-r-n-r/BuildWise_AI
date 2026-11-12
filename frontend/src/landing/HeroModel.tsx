/**
 * HeroModel.tsx — the landing's set piece: the captured plot, extruded.
 *
 * WHAT IT IS, AND WHY IT IS ALLOWED TO EXIST. Two 3D heroes were built on this
 * page before and both were removed (see Hero.tsx): a WebGL massing that implied a
 * viewer the product does not ship, and a scroll-driven corridor of engine sheets
 * that spent three viewports of the reader's attention on itself. This is the third,
 * and it is different in the two ways those failed:
 *
 *  1. It is TRANSFORM-ONLY. No canvas, no GPU library, no renderer, no authored
 *     mesh: every storey is a `div` stood up with `rotateX(-90deg)`, lit by its own
 *     bearing, and every opening on it is an engine-returned window placement
 *     (`floors[].windows` in heroMassing.ts). It therefore has no no-WebGL rung to
 *     fall to, and the reduced-motion rung is the same composition settled rather
 *     than a different picture.
 *  2. It is ONE screen, and it is scrubbed by the reader's own scroll with no
 *     pinning and no runway. The ground floor and the site are always drawn; the
 *     first storey rises and the roof lands on it as the window comes up to the
 *     reading line, and the drawing's dimension chains arrive last. Nothing is
 *     held on screen and nothing is invented: the caption below prints the
 *     generation id, the certificate the engine returned, and where the geometry
 *     came from.
 *
 * WHY IT LOOKS LIKE A BUILDING RATHER THAN FOUR BLOCKS. A massing drawn as one flat
 * tone per face is exactly what a stack of boxes looks like — measured on the first
 * build of this file, where the whole volume sat between RGB 214 and 249 against a
 * white sheet and read as a pale lid on two bands. What makes a model read as
 * architecture is everything BETWEEN the corners:
 *
 *  · FOUR VALUES, NOT TWO. Each face is lit by its own outward normal against one
 *    light direction (see `shadeOf`), so the lit east elevation and the shaded south
 *    one separate at the corner without an outline being drawn anywhere.
 *  · A SLAB BAND WITH A REAL CAST SHADOW. The band is at the engine's own
 *    floor-to-floor line; the shadow under it is what makes two storeys read as
 *    two, and it is why the band is drawn as a gradient rather than a stripe.
 *  · A PLINTH. The bottom 0.14 m of the ground floor is a darker base course, the
 *    one convention that stops a wall meeting the ground in a hard line.
 *  · REVEALED OPENINGS. The engine's window schedule gives a sill, a head and a
 *    span, and the renderer uses all three: a recessed reveal with a shadowed head,
 *    a light frame, glazing with a sky reflection, a mullion pattern by width, and
 *    a projecting sill that throws its own line. A dark rectangle painted on a wall
 *    is a hole; a window with a reveal is an opening.
 *  · PANEL JOINTS. Fine vertical joints at 1.35 m give a 13.5 m wall a scale. This
 *    is TEXTURE, not a capture field, and is the only wall pattern here that is not
 *    derived from the generation (the roof paving is the same kind of texture).
 *
 * THE POSE WAS CHOSEN BY LOOKING AT THE RESULT. The first version of the third hero
 * was pitched 50° and yawed −22°, which put one elevation across most of the sheet
 * and turned the other — where seven of the twelve openings are — into a sliver. The
 * pose is now 45° / −38°, and the rotations were also corrected rather than just
 * retuned: `rotateY` on a flat sheet ROLLS it out of the page instead of turning the
 * plan, which is why the east elevation measured 70 px against the south's 437. A
 * `rotateZ` first turns the plan within its own plane and the pitch then tilts it,
 * so both visible elevations arrive at their true foreshortened widths. See the
 * pose write in `HeroModel` for the measurement.
 *
 * THE SCRUB IS P4'S FIRST REAL CONSUMER, and it is why this file exists at all.
 * `useDampedScrub` had unit coverage and no landing section to prove it on; the
 * acceptance items it could not be measured against (settled end under reduced
 * motion, a monotone value across a real scroll) are now asserted in a browser
 * against this element — see `scripts/interaction_probe.cjs` [7], which reads the
 * ROOF's projected position, not an internal value, so what it measures is the
 * drawing rather than a mirror of the state that drew it.
 *
 * THE SUB-BANDS END BEFORE THE BAND DOES, on purpose: the rise completes at 60 %
 * of the entry band and the annotation at 86 %, so the settled frame is reached
 * with scroll still left. That is what lets the reduced-motion frame and the
 * animated page's end state be compared as pixels rather than as intent.
 */
import React, { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useTransform, type MotionValue } from 'framer-motion';
import { HERO_MASSING, type MassingEdge, type MassingOpening } from './heroMassing';
import {
  ENTRY_BAND,
  fitAspect,
  rectPath,
  ringPath,
  useCapability,
  useDampedScrub,
  useDeviceTilt,
  useOnScreen,
  usePointerParallax,
  viewBoxFor,
  type ViewBox,
} from './interaction';
import { m2, mM } from './format';

/* ------------------------------------------------------------------ */
/* constants                                                           */
/* ------------------------------------------------------------------ */

/**
 * THE TILT, MEASURED BY LOOKING AT IT.
 *
 * It was 50°, chosen when the drawing was mostly a plan and the extrusion was a
 * detail on it: a 6 m volume on a 13.5 × 9 m footprint seen from there is a lid with
 * a stripe under it, which is exactly the "stack of blocks" reading.
 *
 * Measured at 18°, 28°, 38° and 45°: at 18° the drawing is a plan with a lip on it
 * (the roof takes over half the model and the facades are a band); at 45° the two
 * elevations carry the drawing and the terrace is still legible inside its parapet.
 * Below ~32° a 1.2 m window head is only a few pixels of reveal, and above ~55° the
 * roof closes up and the drawing becomes an elevation with a fold. 45° is the far
 * side of that band, chosen to give the facade the height the openings need.
 */
const BASE_TILT_DEG = 45;

/**
 * THE REST YAW, AND WHY THE MODEL IS NOT SQUARE-ON.
 *
 * At −22° the south elevation held ~two thirds of the visible corner and the east
 * elevation was 40 px wide, so the model showed one face and hid the one with four
 * windows on it; −38° brings the east elevation up to 9 m × sin 38° ≈ 5.5 m of
 * facade, which is a legible width for four windows. The lit/shaded corner then
 * falls near the middle of the drawing, which is where an axonometric is composed,
 * and both elevations the reader can see carry openings on both storeys.
 */
const BASE_YAW_DEG = -38;
const PARALLAX = { x: 2.2, y: 1.2 } as const;

/**
 * A WEAK PERSPECTIVE, the same 4200 px the prototype measured and kept: at a
 * strong one the roof plane grew faster than the ground plane and the building
 * appeared to overhang its own setback. Architects draw an axonometric for the same
 * reason — a plan is a measurement, not a photograph.
 */
const PERSPECTIVE_PX = 4200;

/**
 * THE SCRUB'S TWO BEATS, as fractions of the entry band.
 *
 * `rise` extrudes the first floor and carries the roof up with it; `annotate`
 * brings in the setback band, the buildable line and the dimension chains. Both
 * finish early enough (0.60 / 0.86) that the settled frame is reached while the
 * stage is still rising through the band, which is what makes "reduced motion is
 * the settled frame" a statement about pixels instead of about timing.
 */
const RISE_FROM = 0.10;
const RISE_TO = 0.60;
const DRAW_FROM = 0.58;
const DRAW_TO = 0.86;

/* Roof furniture. PRESENTATION HEIGHTS, NOT CAPTURE FIELDS: the capture places the
   stair core and the wet ducts in plan, and states no height above the roof. A
   stair head-house and two vent stacks are what those two elements become on a
   real terrace, and they are the detail that stops a roof reading as a lid. */
const STAIR_HEAD_M = 2.4;
const STACK_M = 0.55;
const PARAPET_M = 0.5;
const PARAPET_INSET_M = 0.24;
/** The coping's overhang past the parapet's outer face. */
const COPING_OVERHANG_M = 0.07;
/** The ground course, in metres — the one invented facade element, and it is a base. */
const PLINTH_M = 0.14;

/** The slab / beam band at the top of every storey, in metres. */
const SLAB_BAND_M = 0.34;
/** How far the expressed floor plate stands proud of the facade. */
const SLAB_OVERHANG_M = 0.12;

/** Stroke width in PLANE METRES — a hairline that scales with the drawing. */
const HAIR = 0.05;

/**
 * THE SHEET, AND HOW MUCH OF IT THE DRAWING TAKES.
 *
 * The sheet's aspect ratio is also the stage's, because every face's
 * metres-to-pixels conversion is derived from the plane's width and a stage whose
 * ratio disagreed with the view box would letterbox the SVG and leave the extrusion
 * off its own plate.
 *
 * 1.45 is the pose's own projection: at 45° of pitch and 38° of yaw the drawing
 * fills roughly a 1.45 : 1 box. The plane is inset 8.5 % because the ROTATED plane
 * projects to 1.157 × its own size on both axes (measured on the live stage, and the
 * reason a 5 % inset put 51 px of it outside the sheet); the inset is what keeps the
 * corners — and a 6 m wall plus a 2.4 m stair head — inside the crop.
 */
const SHEET_ASPECT = 1.45;

/**
 * The same sheet on a phone. The RATIO is the pose's own (the drawing projects to
 * roughly 1.45 : 1 at this tilt and yaw), so the stage is not much taller than the
 * drawing on it; the MARGIN is the only thing that changes, because at 342 px of
 * column the same drawing is ~11 px per metre — a 3 m storey is 33 px — and the
 * sheet cannot afford to be cropped by a rounding error. Both are chosen by the
 * MEASURED box width rather than by a media query, so neither can disagree with the
 * box the faces are drawn into.
 */
const SHEET_ASPECT_NARROW = 1.45;
const SHEET_MARGIN = 0.035;
const SHEET_MARGIN_NARROW = 0.06;
const NARROW_BOX_PX = 640;

/**
 * How far the drawing PLANE is inset from the stage's own box, as a fraction.
 *
 * See the sheet block above for the measurement: the rotated plane projects to
 * 1.157 × its own size, so the inset is what keeps its corners on the paper rather
 * than outside the clipped frame. At 8.5 % the drawing occupies ~75 % of the sheet,
 * which is the trade the model wants anyway — a massing photographed from closer than
 * this fills the frame and loses its ground.
 */
const PLANE_INSET = 0.085;
/**
 * The plane is nudged up by 1.5 % of the stage: the model's own mass sits below the
 * sheet's centre (the roof rises out of a plan whose bottom vertex is the nearest
 * point), so a centred plane leaves twice the paper above the drawing as below it.
 * The two numbers must SUM to `2 × PLANE_INSET`, or the plane stops having the view
 * box's aspect and the SVG letterboxes under the faces.
 */
const PLANE_INSET_TOP = PLANE_INSET - 0.015;
const PLANE_INSET_BOTTOM = PLANE_INSET + 0.015;

/* ------------------------------------------------------------------ */
/* material                                                            */
/* ------------------------------------------------------------------ */

type Rgb = readonly [number, number, number];

const rgbCss = ([r, g, b]: Rgb, a = 1): string =>
  `rgba(${Math.round(r)},${Math.round(g)},${Math.round(b)},${a})`;

const scale = ([r, g, b]: Rgb, k: number): Rgb => [r * k, g * k, b * k];

/**
 * The model's material, in one place.
 *
 * LIMESTONE, NOT PORCELAIN. The page's ground is `--bw-white`; a wall within 5 % of
 * it has no edge and no depth, which is what the first build looked like. These are
 * warm neutrals a physical model would be made of — card, chipboard, acrylic — and
 * the 20 % spread between the lit and shaded faces is what a single directional
 * light does to them.
 */
const WALL: Rgb = [236, 233, 226];
/** The floor plates' edge, a shade lighter than the wall and unbanded. */
const SLAB_COLOR: Rgb = [250, 249, 245];
/** The parapet upstand reads as a shadowed rim around the terrace. */
const PARAPET_COLOR: Rgb = [214, 210, 202];
/** Roof furniture — head-house and stacks — is a touch greyer than the dwelling. */
const FURNITURE_COLOR: Rgb = [228, 224, 216];
const PLINTH_COLOR: Rgb = [176, 173, 164];
const ROOF_COLOR: Rgb = [199, 195, 186];
const COPING_COLOR: Rgb = [243, 241, 234];

const GLASS_TOP = 'rgba(126, 144, 163, 0.97)';
const GLASS_MID = 'rgba(77, 94, 116, 0.98)';
const GLASS_BOTTOM = 'rgba(38, 50, 66, 0.98)';
const FRAME = 'rgba(248, 248, 245, 0.96)';
const INK = '11,18,32';

/**
 * ONE LIGHT, AND THE FACES IT FALLS ON.
 *
 * In plane metres, from the north-east and above: the east elevation is the lit
 * one, the south elevation is in shade, and the roof is brightest. The shade is a
 * value between 0.76 and 1 rather than an arbitrary tone per side, so a wall keeps
 * its material when it turns the corner and only its value changes.
 */
const LIGHT = { x: 0.55, y: 0.84 } as const;

/** The outward normal of an edge, from its own corners (clockwise in the plane). */
function normalOf(from: { x: number; y: number }, to: { x: number; y: number }) {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.hypot(dx, dy) || 1;
  return { x: dy / length, y: -dx / length };
}

/** 0.76 (facing away) → 1 (facing the light). */
function shadeOf(from: { x: number; y: number }, to: { x: number; y: number }): number {
  const n = normalOf(from, to);
  const dot = n.x * LIGHT.x + n.y * LIGHT.y;
  return 0.76 + 0.24 * (0.5 + 0.5 * dot);
}

type PlanePoint = { x: number; y: number };

const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v);

/*
 * HOW THE MOTION REACHES THE DOM, AND WHY NOT THROUGH A MOTION COMPONENT.
 *
 * MEASURED TWICE, both times as a visual defect rather than as an error. First:
 * framer applies a MotionValue placed in `style` when that value CHANGES, not when
 * the element mounts, so a face whose transform was a constant template rendered
 * with no transform at all — it lay flat on the sheet while the storey above it
 * stood up. Second: `useMotionTemplate` bakes PLAIN inputs at creation, so every
 * `translateZ`/`rotateZ` computed from measured pixels stayed at the value it had
 * on the first render, before the box had been measured — the massing came out
 * displaced by a third of the sheet.
 *
 * The scene therefore has exactly ONE animated input: the scrub. It is published
 * as three custom properties on the stage (the rise, the roof's height in px, and
 * the drawing's opacity), and every transform that depends on it is written in CSS
 * with `var(...)` and static geometry otherwise. One subscription, three property
 * writes, no per-frame React render — and a transform that never changes is plain
 * CSS that cannot be left unwritten.
 */
const VAR_RISE = '--bw-rise';
const VAR_ROOF_Z = '--bw-roof-z';
const VAR_DRAWING = '--bw-drawing';

/* ------------------------------------------------------------------ */
/* drawing primitives                                                  */
/* ------------------------------------------------------------------ */

/**
 * One horizontal sheet in the tilted plane: an absolutely-positioned div at a
 * plane-normal offset, holding an SVG whose user space IS the engine's plane
 * (metres, E/N). Stroke widths are therefore in metres too, so the drawing scales
 * as one object.
 */
const Sheet: React.FC<{
  vb: ViewBox;
  zM: number;
  metresToPx: number;
  className?: string;
  style?: React.CSSProperties;
  children: React.ReactNode;
}> = ({ vb, zM, metresToPx, className, style, children }) => (
  <div
    className={'absolute inset-0 ' + (className ?? '')}
    style={{
      transform: `translateZ(${(zM * metresToPx).toFixed(2)}px)`,
      transformStyle: 'preserve-3d',
      pointerEvents: 'none',
      ...style,
    }}
  >
    <svg
      viewBox={`${vb.x} ${vb.svgY} ${vb.w} ${vb.h}`}
      preserveAspectRatio="xMidYMid meet"
      className="absolute inset-0 h-full w-full overflow-visible"
      aria-hidden
    >
      {children}
    </svg>
  </div>
);

/**
 * One window or door, as a recessed opening rather than a rectangle of paint.
 *
 * The order is what does the work: the reveal is the dark border between the wall
 * and the frame, the head carries a shadow (light comes from above, so a reveal is
 * always darkest at its top), the frame is a light bead around the glazing, and the
 * sill is a projecting lip below the opening. A 2.4 m window at this scale is ~85 px
 * wide and 43 px tall, so each of those is two or three pixels — but they are the
 * pixels that make it read as a window instead of as a hole.
 */
const Opening: React.FC<{
  opening: MassingOpening;
  heightM: number;
  lengthM: number;
  metresToPx: number;
}> = ({ opening, heightM, lengthM, metresToPx }) => {
  const left = (opening.alongM / lengthM) * 100;
  const width = (opening.widthM / lengthM) * 100;
  const top = ((heightM - opening.headM) / heightM) * 100;
  const height = ((opening.headM - opening.sillM) / heightM) * 100;

  const isDoor = opening.kind === 'door';
  const framePx = Math.max(1, Math.round(metresToPx * 0.06));
  /* Panes by width, the way a schedule would size a light: a 2.4 m window is three
     lights, a 1.4 m one is two, a 1.2 m one is a single casement. This is a drawing
     convention, not a capture field — the capture states the span, not its divisions. */
  const panes = isDoor ? 1 : opening.widthM >= 2.2 ? 3 : opening.widthM >= 1.4 ? 2 : 1;

  return (
    <div
      data-bw-opening={opening.id}
      style={{
        position: 'absolute',
        left: `${left.toFixed(3)}%`,
        top: `${top.toFixed(3)}%`,
        width: `${width.toFixed(3)}%`,
        height: `${height.toFixed(3)}%`,
        background: 'linear-gradient(180deg, rgba(26,33,44,0.92) 0 30%, rgba(40,48,60,0.82) 100%)',
        boxShadow: `inset 1px 0 2px rgba(${INK},0.5), inset -1px 0 0 rgba(255,255,255,0.28)`,
      }}
    >
      {/* the reveal's cast shadow, falling from the head down the opening */}
      <span
        aria-hidden
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: 0,
          height: '38%',
          background: 'linear-gradient(180deg, rgba(6,10,18,0.58), rgba(6,10,18,0))',
        }}
      />

      {/* the frame, the glazing and its reflection */}
      <div
        style={{
          position: 'absolute',
          inset: framePx,
          background: isDoor
            ? 'linear-gradient(174deg, rgba(63,72,84,0.98) 0%, rgba(45,54,66,0.99) 58%, rgba(33,41,52,1) 100%)'
            : `linear-gradient(178deg, ${GLASS_TOP} 0%, ${GLASS_MID} 46%, ${GLASS_BOTTOM} 100%)`,
          boxShadow: `inset 0 0 0 ${Math.max(1, framePx - 1)}px ${FRAME}, inset 0 3px 5px -2px rgba(${INK},0.55)`,
          overflow: 'hidden',
        }}
      >
        {/* a sky reflection: one diagonal band, the way a photograph catches glass */}
        {!isDoor ? (
          <span
            aria-hidden
            style={{
              position: 'absolute',
              inset: 0,
              background:
                'linear-gradient(116deg, rgba(206,220,234,0.34) 0 16%, rgba(255,255,255,0.09) 16% 30%, rgba(255,255,255,0) 30%)',
            }}
          />
        ) : (
          <>
            {/* A door leaf: two recessed panels, which is what reads as a door at 3 px. */}
            <span
              aria-hidden
              style={{
                position: 'absolute',
                left: '18%',
                right: '18%',
                top: '12%',
                bottom: '52%',
                boxShadow: `inset 0 1px 2px rgba(${INK},0.6), inset 0 -1px 0 rgba(255,255,255,0.22)`,
              }}
            />
            <span
              aria-hidden
              style={{
                position: 'absolute',
                left: '18%',
                right: '18%',
                top: '58%',
                bottom: '8%',
                boxShadow: `inset 0 1px 2px rgba(${INK},0.6), inset 0 -1px 0 rgba(255,255,255,0.22)`,
              }}
            />
            {/* the handle */}
            <span
              aria-hidden
              style={{
                position: 'absolute',
                right: '12%',
                top: '46%',
                width: 2,
                height: 2,
                borderRadius: 2,
                background: 'rgba(238,236,228,0.95)',
                boxShadow: '0 0 1px rgba(0,0,0,0.8)',
              }}
            />
          </>
        )}

        {/* mullions — one bar per division, light metal against dark glass */}
        {panes > 1
          ? Array.from({ length: panes - 1 }, (_, index) => (
              <span
                key={index}
                aria-hidden
                style={{
                  position: 'absolute',
                  top: 0,
                  bottom: 0,
                  left: `${(((index + 1) / panes) * 100).toFixed(3)}%`,
                  width: 1.5,
                  marginLeft: -0.75,
                  background: 'rgba(246,246,242,0.9)',
                  boxShadow: `0 0 1px rgba(${INK},0.55)`,
                }}
              />
            ))
          : null}
      </div>

      {/* the sill: a light lip that projects past the reveal, with its own shadow */}
      <span
        aria-hidden
        style={{
          position: 'absolute',
          left: -1,
          right: -1,
          bottom: -Math.max(1, framePx),
          height: 2,
          background: 'rgba(250,249,245,0.96)',
          boxShadow: `0 1px 2px rgba(${INK},0.42)`,
        }}
      />
    </div>
  );
};

/**
 * One vertical face of a solid: a quad stood up about its own bottom edge.
 *
 * `rise` is appended to the transform chain and therefore applies in the face's
 * LOCAL frame, which is what makes it a vertical extrusion rather than a squash:
 * scale → rotateX(-90°) → rotateZ → translateZ is applied right to left, so the
 * height shrinks toward the floor line and the rotations stand it up afterwards.
 * Transform-only, so a rising storey costs a composite and no layout.
 *
 * THE FACE'S BACKGROUND IS THE FACADE. Lit in four layers: the corner occlusion,
 * the sky falling down the wall, the panel joints, and the slab band with the
 * shadow it casts — over a solid body colour that carries the face's value.
 */
const Face: React.FC<{
  from: PlanePoint;
  to: PlanePoint;
  heightM: number;
  zPx: number;
  metresToPx: number;
  cssX: (x: number) => number;
  cssY: (y: number) => number;
  lengthM: number;
  openings?: ReadonlyArray<MassingOpening>;
  rise?: MotionValue<number>;
  /** A base course on the ground storey only. */
  plinth?: boolean;
  /** Fine vertical joints, for the walls of the dwelling (not the roof furniture). */
  joints?: boolean;
  /** A light coping band at the top of a low solid (parapet, stair head, stacks). */
  coping?: boolean;
  /**
   * Metres of wall at the TOP of this face that the expressed floor plate covers;
   * the shadow the plate throws is drawn immediately below it. The wall is still
   * full height — the plate is a separate solid standing proud of it.
   */
  plateAboveM?: number;
  /** The body colour and value multiplier for this element's material. */
  body?: Rgb;
  value?: number;
}> = ({
  from,
  to,
  heightM,
  zPx,
  metresToPx,
  cssX,
  cssY,
  lengthM,
  openings,
  rise,
  plinth,
  joints,
  coping,
  plateAboveM = 0,
  body = WALL,
  value = 1,
}) => {
  const x0 = cssX(from.x);
  const y0 = cssY(from.y);
  const dx = cssX(to.x) - x0;
  const dy = cssY(to.y) - y0;
  const angle = (Math.atan2(dy, dx) * 180) / Math.PI;
  const transform =
    `translateZ(${zPx.toFixed(2)}px) rotateZ(${angle.toFixed(2)}deg) rotateX(-90deg) ` +
    `scaleY(${rise ? `var(${VAR_RISE}, 1)` : '1'})`;

  const heightPx = heightM * metresToPx;
  if (heightPx < 1 || Math.hypot(dx, dy) < 1) return null;

  const k = shadeOf(from, to) * value;
  const wall = scale(body, k);
  const plinthPx = plinth ? Math.min(heightPx * 0.12, PLINTH_M * metresToPx) : 0;
  const coverPx = Math.min(heightPx * 0.45, plateAboveM * metresToPx);
  const shadowPx = coverPx > 0 ? Math.min(heightPx * 0.35, 0.6 * metresToPx) : 0;
  const jointPx = Math.max(18, 1.35 * metresToPx);

  const layers: string[] = [];

  /* 1. Corner occlusion: a face loses light where it turns away from the reader. */
  layers.push(
    'linear-gradient(90deg, rgba(11,18,32,0.12), rgba(11,18,32,0) 14%, rgba(11,18,32,0) 86%, rgba(11,18,32,0.09))',
  );
  /* 2. Sky above, ground bounce below — a flat wall is the tell of a box. */
  layers.push(
    'linear-gradient(180deg, rgba(255,255,255,0.26) 0%, rgba(255,255,255,0) 26%, rgba(11,18,32,0.07) 100%)',
  );
  /* 3. Panel joints, in texture only. */
  if (joints) {
    layers.push(
      `repeating-linear-gradient(90deg, rgba(11,18,32,0.075) 0 1px, rgba(255,255,255,0.4) 1px 2px, rgba(0,0,0,0) 2px ${jointPx.toFixed(
        2,
      )}px)`,
    );
  }
  /* 4. The lit top lip, and — where a floor plate stands proud of this wall — the
        shadow that plate throws down its face. The plate itself is GEOMETRY (see
        `SlabEdge`), not paint: this layer is only the light it removes. */
  layers.push(
    coverPx > 0 && shadowPx > 0
      ? `linear-gradient(180deg, rgba(0,0,0,0) 0 ${coverPx.toFixed(2)}px, ` +
          `rgba(8,13,22,0.28) ${coverPx.toFixed(2)}px ${(coverPx + 1.5).toFixed(2)}px, ` +
          `rgba(8,13,22,0.13) ${(coverPx + 1.5).toFixed(2)}px ${(coverPx + shadowPx).toFixed(2)}px, ` +
          `rgba(0,0,0,0) ${(coverPx + shadowPx).toFixed(2)}px)`
      : `linear-gradient(180deg, rgba(255,255,255,0.42) 0 1px, rgba(255,255,255,0) 1px)`,
  );
  /* 5. A coping highlight on the low solids (parapet, head-house, stacks). */
  if (coping) {
    layers.push(
      `linear-gradient(180deg, rgba(255,255,255,0.55) 0 1.5px, rgba(255,255,255,0.12) 1.5px ${Math.max(
        2,
        heightPx * 0.16,
      ).toFixed(2)}px, rgba(0,0,0,0) ${Math.max(2, heightPx * 0.16).toFixed(2)}px)`,
    );
  }
  /* 6. The plinth, with the shadow the wall above it throws down onto it. */
  if (plinthPx > 0) {
    layers.push(
      `linear-gradient(180deg, rgba(0,0,0,0) ${(heightPx - plinthPx).toFixed(2)}px, ` +
        `rgba(8,13,22,0.18) ${(heightPx - plinthPx).toFixed(2)}px ${(heightPx - plinthPx + 1.5).toFixed(2)}px, ` +
        `${rgbCss(scale(PLINTH_COLOR, k))} ${(heightPx - plinthPx + 1.5).toFixed(2)}px 100%)`,
    );
  }
  /* 7. The body of the wall. */
  layers.push(rgbCss(wall));

  return (
    <div
      aria-hidden
      data-bw-face={edgeLabel(from, to)}
      style={{
        position: 'absolute',
        left: `${x0.toFixed(2)}px`,
        top: `${(y0 - heightPx).toFixed(2)}px`,
        width: `${Math.hypot(dx, dy).toFixed(2)}px`,
        height: `${heightPx.toFixed(2)}px`,
        transformOrigin: '0 100%',
        transform,
        background: layers.join(', '),
        boxShadow: `inset 1px 0 0 rgba(255,255,255,0.42), inset -1px 0 0 rgba(11,18,32,0.2), inset 0 -1px 0 rgba(11,18,32,0.28)`,
        pointerEvents: 'none',
      }}
    >
      {openings?.map((opening) => (
        <Opening
          key={opening.id}
          opening={opening}
          heightM={heightM}
          lengthM={lengthM}
          metresToPx={metresToPx}
        />
      ))}
    </div>
  );
};

/**
 * The four corners of an envelope, clockwise in the plane, and the schedule letter
 * that owns each edge.
 *
 * THE LETTER IS THE ENGINE'S, NOT THE COMPASS'S. The capture's `wall_edge` names
 * the side of the plan AS THE ENGINE DRAWS IT (its blueprint has its origin at the
 * top-left), and the openings were extracted with that naming. The renderer walks
 * the same corners in the same order, so `floors[].openings` land on the wall they
 * were extracted from; the SHADING is computed from each edge's own normal instead
 * of from the letter, so a relabelled schedule cannot mis-light the model.
 */
const EDGES: ReadonlyArray<MassingEdge> = ['N', 'E', 'S', 'W'];

const cornersOf = (env: { x: number; y: number; widthM: number; depthM: number }): PlanePoint[] => [
  { x: env.x, y: env.y },
  { x: env.x + env.widthM, y: env.y },
  { x: env.x + env.widthM, y: env.y + env.depthM },
  { x: env.x, y: env.y + env.depthM },
];

/** A debugging/marker label for a face, from the direction it faces. */
function edgeLabel(from: PlanePoint, to: PlanePoint): string {
  const n = normalOf(from, to);
  if (Math.abs(n.x) > Math.abs(n.y)) return n.x > 0 ? 'E' : 'W';
  return n.y > 0 ? 'N' : 'S';
}

/** The openings that belong to one wall of a solid, in the schedule's own edge names. */
const byEdgeOf = (openings: ReadonlyArray<MassingOpening>) => ({
  N: openings.filter((o) => o.edge === 'N'),
  E: openings.filter((o) => o.edge === 'E'),
  S: openings.filter((o) => o.edge === 'S'),
  W: openings.filter((o) => o.edge === 'W'),
});

/**
 * A solid: four faces around a ring plus nothing else. Used for the storeys, the
 * floor plates, the parapet upstand, the stair head and the two vent stacks — one
 * shape, six uses, which is why the roof reads as one building rather than as
 * assembled parts.
 */
const Solid: React.FC<{
  corners: ReadonlyArray<PlanePoint>;
  baseZPx: number;
  heightM: number;
  metresToPx: number;
  cssX: (x: number) => number;
  cssY: (y: number) => number;
  openingsByEdge?: Partial<Record<MassingEdge, ReadonlyArray<MassingOpening>>>;
  rise?: MotionValue<number>;
  plinth?: boolean;
  joints?: boolean;
  coping?: boolean;
  plateAboveM?: number;
  body?: Rgb;
  value?: number;
}> = ({
  corners,
  baseZPx,
  heightM,
  metresToPx,
  cssX,
  cssY,
  openingsByEdge,
  rise,
  plinth,
  joints,
  coping,
  plateAboveM,
  body,
  value,
}) => (
  <>
    {corners.map((corner, index) => {
      const next = corners[(index + 1) % corners.length];
      const edge = EDGES[index];
      return (
        <Face
          key={edge}
          from={corner}
          to={next}
          heightM={heightM}
          zPx={baseZPx}
          metresToPx={metresToPx}
          cssX={cssX}
          cssY={cssY}
          lengthM={Math.hypot(next.x - corner.x, next.y - corner.y)}
          openings={openingsByEdge?.[edge]}
          rise={rise}
          plinth={plinth}
          joints={joints}
          coping={coping}
          plateAboveM={plateAboveM}
          body={body}
          value={value}
        />
      );
    })}
  </>
);

/**
 * THE FLOOR PLATE, EXPRESSED.
 *
 * A massing with two painted tones per facade is still two boxes stacked. What
 * makes a real building read as one is the floor plate: a slab edge standing proud
 * of the wall, casting a line and picking up a lit top. This draws it as GEOMETRY —
 * a fascia 0.34 m tall standing 0.12 m off the envelope, with its top surface as a
 * ring — so the horizontal line across the corner is a real occlusion rather than a
 * gradient, and the wall above it carries the shadow the plate throws.
 *
 * PRESENTATION GEOMETRY, and the only element here whose dimension is not the
 * capture's: the engine states the floor-to-floor height, not the slab's thickness
 * or its overhang. Nothing about the openings, the storeys or the site changes. The
 * plate sits at the top of the GROUND storey only — one expressed line is what the
 * eye needs; a plate at the roof line would fight the parapet for the same edge.
 */
const SlabEdge: React.FC<{
  env: { x: number; y: number; widthM: number; depthM: number };
  zPx: number;
  heightM: number;
  overhangM: number;
  vb: ViewBox;
  metresToPx: number;
  cssX: (x: number) => number;
  cssY: (y: number) => number;
}> = ({ env, zPx, heightM, overhangM, vb, metresToPx, cssX, cssY }) => {
  const ring = `${rectPath(env.x, env.y, env.widthM, env.depthM)} ${rectPath(
    env.x + overhangM,
    env.y + overhangM,
    env.widthM - overhangM * 2,
    env.depthM - overhangM * 2,
  )}`;
  return (
    <>
      <Solid
        corners={cornersOf({
          x: env.x - overhangM,
          y: env.y - overhangM,
          widthM: env.widthM + overhangM * 2,
          depthM: env.depthM + overhangM * 2,
        })}
        baseZPx={zPx}
        heightM={heightM}
        metresToPx={metresToPx}
        cssX={cssX}
        cssY={cssY}
        body={SLAB_COLOR}
      />
      {/* The plate's top surface, a 0.12 m ledge picking up the sky. The underside
          faces down and is never visible from above, so it is not drawn. */}
      <Sheet vb={vb} zM={0} metresToPx={metresToPx} style={{ transform: `translateZ(${(zPx + heightM * metresToPx).toFixed(2)}px)` }}>
        <path d={ring} fillRule="evenodd" fill={rgbCss(scale(SLAB_COLOR, 1.0))} />
        <path d={ring} fillRule="evenodd" fill="none" stroke="rgba(11,18,32,0.17)" strokeWidth={HAIR * 0.6} />
      </Sheet>
    </>
  );
};

/* ------------------------------------------------------------------ */
/* the stage                                                           */
/* ------------------------------------------------------------------ */

export const HeroModel: React.FC = () => {
  const M = HERO_MASSING;
  const cap = useCapability();
  const boxRef = useRef<HTMLDivElement>(null);
  const onScreen = useOnScreen(boxRef);

  /**
   * The scrub. `enabled` is the idle contract: an off-screen stage runs no
   * animation frame and reads no geometry. Under reduced motion the hook returns
   * the settled END by itself (P4), and on the other two "do less" flags the
   * derived values below are pinned to 1 — a save-data reader gets the finished
   * composition rather than a half-built one, which is the difference between a
   * fallback and a broken page.
   */
  const scrub = useDampedScrub(boxRef, { band: ENTRY_BAND, enabled: onScreen && !cap.staticOnly });
  const settled = cap.staticOnly;
  const rise = useTransform(scrub, (v) => (settled ? 1 : clamp01((v - RISE_FROM) / (RISE_TO - RISE_FROM))));
  const annotation = useTransform(scrub, (v) => (settled ? 1 : clamp01((v - DRAW_FROM) / (DRAW_TO - DRAW_FROM))));

  /* The box's own width, read once and on resize. This is the only layout read in
     the component; every face's pixel height derives from it. */
  const [boxW, setBoxW] = useState(0);
  useLayoutEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const measure = () => setBoxW(el.offsetWidth || 0);
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  /* Pose. Pointer on a fine pointer, the device's own tilt on a coarse one — the
     same swap the capability gate documents, and the same small amplitude. */
  const poseActive = !cap.staticOnly && onScreen;
  const pointer = usePointerParallax(PARALLAX, poseActive && !cap.coarse);
  const device = useDeviceTilt(PARALLAX, poseActive && cap.coarse);
  const offset = cap.coarse ? device : pointer;
  const rotX = useTransform(offset.y as MotionValue<number>, (v) => BASE_TILT_DEG + v);
  const rotY = useTransform(offset.x as MotionValue<number>, (v) => BASE_YAW_DEG - v);
  const poseRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = poseRef.current;
    if (!el) return;
    const write = () => {
      /*
       * RotateZ, not rotateY, and this was measured rather than reasoned.
       * `rotateX(a) rotateY(b)` tips a flat sheet about its own north-south axis:
       * the plan is ROLLED out of the page, not turned in it, and the east facade
       * (which runs along that axis) projects to a 70 px sliver while the south one
       * gets 437 px. The transform list is applied right to left, so `rotateZ`
       * first turns the plan within its own plane — a real yaw — and `rotateX` then
       * pitches it. Both visible elevations come out at their true foreshortened
       * widths, which is what an axonometric is.
       */
      el.style.transform = `rotateX(${rotX.get()}deg) rotateZ(${rotY.get()}deg)`;
    };
    write();
    const offs = [rotX.on('change', write), rotY.on('change', write)];
    return () => {
      for (const off of offs) off();
    };
  }, [rotX, rotY]);

  /* Geometry in the engine's plane, and the one conversion to CSS pixels for the
     elements that are not SVGs (the faces). */
  const narrow = boxW > 0 && boxW < NARROW_BOX_PX;
  const vb = useMemo(
    () =>
      fitAspect(
        viewBoxFor(M.plot.ring, narrow ? SHEET_MARGIN_NARROW : SHEET_MARGIN),
        narrow ? SHEET_ASPECT_NARROW : SHEET_ASPECT,
      ),
    [M.plot.ring, narrow],
  );
  /* The plane is a fraction of the stage, so every metre-to-pixel conversion — and
     therefore every face, opening and stroke — is derived from the PLANE's width.
     One constant, read in one place: the sheet's furniture is the only thing that
     still measures against the stage. */
  const planeW = boxW * (1 - PLANE_INSET * 2);
  const metresToPx = planeW > 0 ? planeW / vb.w : 0;
  const cssX = (x: number) => (x - vb.x) * metresToPx;
  const cssY = (y: number) => (-y - vb.svgY) * metresToPx;

  const storeys = M.floors;
  const ground = storeys[0];
  const upper = storeys[1];
  const env = ground.envelope;

  const byEdge = useMemo(
    () => ({ ground: byEdgeOf(ground.openings), upper: upper ? byEdgeOf(upper.openings) : undefined }),
    [ground, upper],
  );

  /* The one subscription: the scrub publishes the rise, the roof's height in px and
     the drawing's opacity onto the stage element. Everything below reads them from
     CSS, so a scroll frame costs three property writes and no React render. */
  const varsRef = useRef<HTMLDivElement>(null);
  const roofAt = (r: number) => M.floorHeightM * (1 + r) * metresToPx;
  useLayoutEffect(() => {
    const el = varsRef.current;
    if (!el) return;
    const writeRise = (r: number) => {
      el.style.setProperty(VAR_RISE, String(r));
      el.style.setProperty(VAR_ROOF_Z, `${roofAt(r).toFixed(2)}px`);
    };
    const writeDrawing = (a: number) => el.style.setProperty(VAR_DRAWING, String(a));
    writeRise(rise.get());
    writeDrawing(annotation.get());
    const offs = [rise.on('change', writeRise), annotation.on('change', writeDrawing)];
    return () => {
      for (const off of offs) off();
    };
    // `roofAt` reads metresToPx from this render; re-subscribing on resize is the
    // point, since the roof's pixel height changes with the box's width.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rise, annotation, metresToPx]);

  const plotPath = useMemo(() => ringPath(M.plot.ring), [M.plot.ring]);
  const buildablePath = useMemo(() => ringPath(M.buildable.ring), [M.buildable.ring]);
  const roofRect = useMemo(() => rectPath(env.x, env.y, env.widthM, env.depthM), [env]);
  const roofInnerRect = useMemo(
    () => rectPath(env.x + PARAPET_INSET_M, env.y + PARAPET_INSET_M, env.widthM - PARAPET_INSET_M * 2, env.depthM - PARAPET_INSET_M * 2),
    [env],
  );
  const copingRect = useMemo(
    () =>
      rectPath(
        env.x - COPING_OVERHANG_M,
        env.y - COPING_OVERHANG_M,
        env.widthM + COPING_OVERHANG_M * 2,
        env.depthM + COPING_OVERHANG_M * 2,
      ),
    [env],
  );

  const figure = [
    { label: 'Plot', value: m2(M.plot.areaSqm) },
    { label: 'Buildable', value: m2(M.buildable.areaSqm) },
    { label: 'Footprint', value: `${M.footprint.widthM.toFixed(1)} × ${M.footprint.depthM.toFixed(1)} m` },
    { label: 'Storeys', value: `${M.storeys} × ${M.floorHeightM.toFixed(2)} m` },
  ];

  return (
    <figure className="m-0">
      <div
        ref={(node) => {
          boxRef.current = node;
          varsRef.current = node;
        }}
        data-bw-massing=""
        role="img"
        aria-label={
          `Massing of the captured plot: ${M.storeys} storeys at ${M.floorHeightM.toFixed(2)} metres, ` +
          `a ${M.footprint.widthM} by ${M.footprint.depthM} metre footprint inside a ${M.plot.areaSqm} square metre plot, ` +
          'with the window and entrance openings the engine placed on each facade.'
        }
        className="relative overflow-hidden rounded-[14px] border border-bw-line-soft"
        style={
          {
            aspectRatio: `${vb.w} / ${vb.h}`,
            /* Solid white, not a gradient: the massing's own tones have to sit ON
               something neutral, and five tones over a five-stop gradient is eleven
               greys within 8 % of each other. */
            background: 'var(--bw-white)',
            boxShadow: 'var(--bw-shadow-1)',
            /* The initial values, so the first paint is already correct rather
               than waiting for the layout effect below. */
            [VAR_RISE]: String(rise.get()),
            [VAR_ROOF_Z]: `${roofAt(rise.get()).toFixed(2)}px`,
            [VAR_DRAWING]: String(annotation.get()),
          } as React.CSSProperties
        }
      >
        <div className="absolute inset-0" style={{ perspective: `${PERSPECTIVE_PX}px` }} aria-hidden>
          <div
            ref={poseRef}
            className="absolute"
            style={{
              left: `${(PLANE_INSET * 100).toFixed(2)}%`,
              right: `${(PLANE_INSET * 100).toFixed(2)}%`,
              top: `${(PLANE_INSET_TOP * 100).toFixed(2)}%`,
              bottom: `${(PLANE_INSET_BOTTOM * 100).toFixed(2)}%`,
              transformStyle: 'preserve-3d',
              transform: `rotateX(${rotX.get()}deg) rotateZ(${rotY.get()}deg)`,
            }}
          >
            {/* ---- ground: the site, its shadow and the plot line ---- */}
            <Sheet vb={vb} zM={0} metresToPx={metresToPx}>
              <defs>
                <filter id="bw-massing-shadow" x="-40%" y="-40%" width="180%" height="180%">
                  <feGaussianBlur stdDeviation={0.7} />
                </filter>
                <filter id="bw-massing-soft" x="-30%" y="-30%" width="160%" height="160%">
                  <feGaussianBlur stdDeviation={0.22} />
                </filter>
              </defs>
              {/* THE CAST SHADOW, offset south-west of the building — the same light
                  direction the faces are shaded by. It is drawn first and blurred:
                  the earlier version offset it to the north-east, where the volume
                  hid all of it, and the model appeared to float. */}
              <path
                d={rectPath(env.x - 2.4, env.y - 2.9, env.widthM, env.depthM)}
                fill="rgba(11,18,32,0.13)"
                filter="url(#bw-massing-shadow)"
              />
              {/* a tighter shadow right at the base, so the walls sit on the paper */}
              <path
                d={rectPath(env.x - 0.35, env.y - 0.55, env.widthM + 0.9, env.depthM + 0.9)}
                fill="none"
                stroke="rgba(11,18,32,0.16)"
                strokeWidth={0.42}
                filter="url(#bw-massing-soft)"
              />
              <path d={plotPath} fill="rgba(11,18,32,0.032)" />
              {M.outdoor.map((zone) => (
                <path
                  key={zone.id}
                  d={ringPath(zone.ring)}
                  fill="rgba(31,169,85,0.075)"
                  stroke="rgba(31,169,85,0.30)"
                  strokeWidth={HAIR}
                />
              ))}
              <path d={plotPath} fill="none" stroke="var(--bw-ink)" strokeWidth={HAIR * 1.4} />
              {M.plot.ring.map(([x, y], i) => (
                <circle key={i} cx={x} cy={-y} r={HAIR * 1.1} fill="var(--bw-ink)" />
              ))}
            </Sheet>

            {/* ---- the drawing layer: setbacks, the buildable line, dimensions ---- */}
            <div
              className="absolute inset-0"
              data-bw-massing-drawing=""
              style={{ transformStyle: 'preserve-3d', opacity: `var(${VAR_DRAWING}, 1)` }}
            >
              <Sheet vb={vb} zM={0.03} metresToPx={metresToPx}>
                {/* The band is the DIFFERENCE of two real polygons — plot minus
                    buildable — not an offset the page drew. */}
                <path d={`${plotPath} ${buildablePath}`} fillRule="evenodd" fill="rgba(47,111,237,0.07)" />
                <path
                  d={buildablePath}
                  fill="none"
                  stroke="rgba(47,111,237,0.55)"
                  strokeWidth={HAIR}
                  strokeDasharray={`${(0.34).toFixed(2)} ${(0.26).toFixed(2)}`}
                />
                {/* Two dimension chains, as a drawing would carry them: the width
                    on the ground south of the building and the depth to its east,
                    because those are the two margins the pose leaves visible. The
                    figures are the capture's footprint, not a re-measurement. Each
                    label sits on a small paper plate so the drawing stays legible
                    over a shadow. */}
                {[
                  {
                    x1: env.x,
                    y1: env.y - 1.55,
                    x2: env.x + env.widthM,
                    y2: env.y - 1.55,
                    label: mM(env.widthM),
                    textX: env.x + env.widthM / 2,
                    textY: env.y - 1.55,
                  },
                  {
                    x1: env.x + env.widthM + 1.45,
                    y1: env.y,
                    x2: env.x + env.widthM + 1.45,
                    y2: env.y + env.depthM,
                    label: mM(env.depthM),
                    textX: env.x + env.widthM + 1.45,
                    textY: env.y + env.depthM / 2,
                  },
                ].map((dim) => {
                  const tick = 0.34;
                  const vertical = Math.abs(dim.x2 - dim.x1) < 1e-6;
                  return (
                    <g key={dim.label + (vertical ? 'v' : 'h')}>
                      <path
                        d={`M ${dim.x1} ${-dim.y1} L ${dim.x2} ${-dim.y2}`}
                        stroke="rgba(11,18,32,0.5)"
                        strokeWidth={HAIR}
                      />
                      <path
                        d={
                          vertical
                            ? `M ${dim.x1 - tick / 2} ${-dim.y1} L ${dim.x1 + tick / 2} ${-dim.y1} M ${dim.x2 - tick / 2} ${-dim.y2} L ${dim.x2 + tick / 2} ${-dim.y2}`
                            : `M ${dim.x1} ${-dim.y1 - tick / 2} L ${dim.x1} ${-dim.y1 + tick / 2} M ${dim.x2} ${-dim.y2 - tick / 2} L ${dim.x2} ${-dim.y2 + tick / 2}`
                        }
                        stroke="rgba(11,18,32,0.5)"
                        strokeWidth={HAIR}
                      />
                      {/* A halo rather than a plate: the label has to stay legible
                          over the cast shadow it sits in, and a translucent plate
                          over a blurred shadow is a smudge with type in it. A
                          stroke of paper colour behind the glyphs keeps the
                          drawing's own shading visible around the figure. */}
                      <text
                        x={dim.textX}
                        y={-dim.textY + (vertical ? 0.26 : 0.26)}
                        fill="rgba(11,18,32,0.78)"
                        stroke="rgba(255,255,255,0.92)"
                        strokeWidth={0.2}
                        paintOrder="stroke"
                        /* The annotation is sized in plane metres, so it scales with
                           the drawing — which is right until the drawing is 11 px to
                           the metre on a phone, where 0.6 m of text is 7 px and reads
                           as a smudge. The figure is what has to survive there, not
                           the scale. */
                        fontSize={narrow ? 1.15 : 0.6}
                        fontWeight={600}
                        textAnchor="middle"
                        transform={vertical ? `rotate(-90 ${dim.textX} ${-dim.textY})` : undefined}
                        fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
                      >
                        {dim.label}
                      </text>
                    </g>
                  );
                })}
              </Sheet>
            </div>

            {/* ---- the ground storey: always drawn, so the window is never empty ---- */}
            <Solid
              corners={cornersOf(env)}
              baseZPx={0}
              heightM={M.floorHeightM}
              metresToPx={metresToPx}
              cssX={cssX}
              cssY={cssY}
              openingsByEdge={byEdge.ground}
              plinth
              joints
              plateAboveM={SLAB_BAND_M}
            />

            {/* ---- the floor plate: one expressed line between the storeys ---- */}
            <SlabEdge
              env={env}
              zPx={(M.floorHeightM - SLAB_BAND_M) * metresToPx}
              heightM={SLAB_BAND_M}
              overhangM={SLAB_OVERHANG_M}
              vb={vb}
              metresToPx={metresToPx}
              cssX={cssX}
              cssY={cssY}
            />

            {/* ---- the first storey: extruded by the reader's own scroll ---- */}
            {upper ? (
              <Solid
                corners={cornersOf(upper.envelope)}
                baseZPx={M.floorHeightM * metresToPx}
                heightM={M.floorHeightM}
                metresToPx={metresToPx}
                cssX={cssX}
                cssY={cssY}
                openingsByEdge={byEdge.upper}
                rise={rise}
                joints
              />
            ) : null}

            {/* ---- the roof, carrying its parapet, stair head and vent stacks ---- */}
            <div
              className="absolute inset-0"
              data-bw-massing-roof=""
              style={{ transformStyle: 'preserve-3d', transform: `translateZ(var(${VAR_ROOF_Z}, 0px))` }}
            >
              <Sheet vb={vb} zM={0} metresToPx={metresToPx}>
                <path d={roofRect} fill={rgbCss(ROOF_COLOR)} />
                {/* Paving joints. TEXTURE, not a capture field: 2 m bays at 8 % ink,
                    because a 13.5 × 9 m terrace with no markings on it reads as an
                    unrendered plane. No dimension on this sheet derives from it. */}
                <g stroke="rgba(11,18,32,0.13)" strokeWidth={HAIR * 0.5}>
                  {Array.from({ length: Math.floor(env.depthM / 2) }, (_, i) => (
                    <path
                      key={`h${i}`}
                      d={`M ${env.x} ${-(env.y + (i + 1) * 2)} L ${env.x + env.widthM} ${-(env.y + (i + 1) * 2)}`}
                    />
                  ))}
                  {Array.from({ length: Math.floor(env.widthM / 2) }, (_, i) => (
                    <path
                      key={`v${i}`}
                      d={`M ${env.x + (i + 1) * 2} ${-env.y} L ${env.x + (i + 1) * 2} ${-(env.y + env.depthM)}`}
                    />
                  ))}
                </g>
                {/* The shadow the parapet casts INTO the terrace — the line that
                    turns a rim into an enclosure. */}
                <path
                  d={roofInnerRect}
                  fill="none"
                  stroke="rgba(11,18,32,0.30)"
                  strokeWidth={0.34}
                  filter="url(#bw-massing-soft)"
                />
                {/* A drainage channel down the east side, at the low edge. */}
                <path
                  d={`M ${env.x + env.widthM - 0.55} ${-env.y} L ${env.x + env.widthM - 0.55} ${-(env.y + env.depthM)}`}
                  stroke="rgba(11,18,32,0.13)"
                  strokeWidth={0.12}
                />
                {/* The head-house and the vent stacks sit ON this surface, so they
                    throw a shadow onto it. Without one they read as boxes floating
                    a few centimetres above the terrace. */}
                <g fill="rgba(11,18,32,0.20)" filter="url(#bw-massing-shadow)">
                  <path
                    d={rectPath(
                      M.stairHead.x - 0.55,
                      M.stairHead.y - 0.75,
                      M.stairHead.widthM + 0.55,
                      M.stairHead.depthM + 0.75,
                    )}
                  />
                  {M.stacks.map((stack) => (
                    <path
                      key={stack.id}
                      d={rectPath(stack.x - 0.22, stack.y - 0.3, stack.widthM + 0.22, stack.depthM + 0.3)}
                    />
                  ))}
                </g>
                {/* The coping: a ring wider than the parapet, so it overhangs and
                    reads as a capping stone rather than as the wall's top. */}
                <path d={`${copingRect} ${roofInnerRect}`} fillRule="evenodd" fill={rgbCss(COPING_COLOR)} />
                <path d={`${copingRect} ${roofInnerRect}`} fillRule="evenodd" fill="none" stroke="rgba(11,18,32,0.26)" strokeWidth={HAIR} />
              </Sheet>

              <Solid
                corners={cornersOf(env)}
                baseZPx={0}
                heightM={PARAPET_M}
                metresToPx={metresToPx}
                cssX={cssX}
                cssY={cssY}
                coping
                body={PARAPET_COLOR}
              />

              {/* The captured stair core, as the head-house it becomes on a roof. */}
              <Solid
                corners={cornersOf(M.stairHead)}
                baseZPx={0}
                heightM={STAIR_HEAD_M}
                metresToPx={metresToPx}
                cssX={cssX}
                cssY={cssY}
                coping
                joints
                body={FURNITURE_COLOR}
                value={0.98}
              />
              <Sheet vb={vb} zM={STAIR_HEAD_M} metresToPx={metresToPx}>
                <path
                  d={rectPath(M.stairHead.x, M.stairHead.y, M.stairHead.widthM, M.stairHead.depthM)}
                  fill={rgbCss(scale(COPING_COLOR, 0.97))}
                  stroke="rgba(11,18,32,0.24)"
                  strokeWidth={HAIR}
                />
              </Sheet>

              {/* The captured wet ducts, as the two vent stacks they become. */}
              {M.stacks.map((stack) => (
                <Solid
                  key={stack.id}
                  corners={cornersOf(stack)}
                  baseZPx={0}
                  heightM={STACK_M}
                  metresToPx={metresToPx}
                  cssX={cssX}
                  cssY={cssY}
                  coping
                  body={FURNITURE_COLOR}
                />
              ))}
              <Sheet vb={vb} zM={STACK_M} metresToPx={metresToPx}>
                {M.stacks.map((stack) => (
                  <path
                    key={stack.id}
                    d={rectPath(stack.x, stack.y, stack.widthM, stack.depthM)}
                    fill={rgbCss(scale(ROOF_COLOR, 0.94))}
                    stroke="rgba(11,18,32,0.24)"
                    strokeWidth={HAIR}
                  />
                ))}
              </Sheet>
            </div>
          </div>
        </div>

        {/* ---- the sheet's own furniture, in screen space ---- */}
        <div className="pointer-events-none absolute left-3 top-2.5 flex flex-wrap items-center gap-2 font-mono text-[10px] uppercase text-bw-ink-2">
          <span className="font-semibold">{M.generationId}</span>
          <span aria-hidden className="h-2.5 w-px bg-bw-line" />
          <span>
            {M.storeys}F · {M.floorHeightM.toFixed(2)} m
          </span>
          <span aria-hidden className="h-2.5 w-px bg-bw-line" />
          <span>{M.plot.areaSqm.toFixed(1)} m² plot</span>
        </div>
        <div className="pointer-events-none absolute bottom-2.5 right-3 flex items-center gap-2 text-[10px] font-medium text-bw-ink-2">
          <span className="font-mono">N</span>
          <span aria-hidden className="text-bw-accent-deep">
            ↑
          </span>
          {/* A real scale bar: five metres at this drawing's own scale. */}
          <span
            aria-hidden
            className="h-[3px] rounded-full bg-bw-ink-3"
            style={{ width: `${(5 * metresToPx).toFixed(1)}px` }}
          />
          <span className="tabular-nums">5 m</span>
        </div>
        <div className="pointer-events-none absolute bottom-2.5 left-3 flex items-center gap-2.5 text-[10px] font-medium text-bw-ink-2">
          <span className="flex items-center gap-1.5">
            <span aria-hidden className="h-[3px] w-4 rounded-full bg-bw-ink" />
            Plot
          </span>
          <span className="flex items-center gap-1.5">
            <span
              aria-hidden
              className="h-[3px] w-4 rounded-full"
              style={{ background: 'repeating-linear-gradient(90deg, var(--bw-accent) 0 4px, transparent 4px 7px)' }}
            />
            Buildable
          </span>
        </div>
      </div>

      <figcaption className="mt-4">
        <dl className="grid max-w-3xl grid-cols-2 gap-x-8 gap-y-4 border-t border-bw-line pt-4 sm:grid-cols-4">
          {figure.map((cell) => (
            <div key={cell.label}>
              <dt className="text-[11px] font-semibold uppercase text-bw-ink-2" style={{ letterSpacing: '0.14em' }}>
                {cell.label}
              </dt>
              <dd className="mt-1 ui-font-tabular text-[15px] font-semibold text-bw-ink">{cell.value}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-3 max-w-3xl text-[12px] leading-[1.6] text-bw-ink-2">
          Extruded from the engine's own per-floor envelopes and window schedule for{' '}
          <span className="font-mono">{M.generationId}</span> — {M.storeys} storeys at {M.floorHeightM.toFixed(2)} m
          floor-to-floor, {M.floors.reduce((n, f) => n + f.openings.length, 0)} openings placed on the facades where the
          engine put them. Certificate {M.certificate.pass} pass · {M.certificate.warn} warn · {M.certificate.na} N/A of{' '}
          {M.certificate.total} rule layers: the engine's own verdict for a captured generation, not a marketing figure.
        </p>
      </figcaption>
    </figure>
  );
};
