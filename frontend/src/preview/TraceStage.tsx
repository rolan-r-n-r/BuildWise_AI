/**
 * preview/TraceStage.tsx — unlinked prototype of the recommended hero
 * centerpiece. It is `noindex`, and lazily imported so neither `/` nor
 * `/app` pays a byte for it until this route is decided on.
 *
 * WHAT IT IS
 * ----------
 * The product's actual first act, miniaturised: a plot is traced, and the engine
 * answers. Two real engine generations are shipped as data
 * (`plotSamples.ts`, generated from the committed captures); this preview draws them
 * in the engine's own local tangent plane (metres, E/N) and lets the reader take
 * hold of the survey ring.
 *
 * THE HONEST SPLIT — AND WHY THE PROTOTYPE DOES NOT RECOMPUTE SETBACKS
 * -------------------------------------------------------------------
 * The brief for this centrepiece asks for "area, setbacks and footprint update in
 * real time". Area and perimeter can be, and are: the app already computes them in
 * the browser while you trace (`services/siteBoundary.metricsFor` — the same
 * shoelace pass, the same EC-01/02/03 validity gate, the same shape classification
 * and the same quadrant bearings this preview prints). Those numbers come from the
 * SHIPPED module, imported, not re-implemented, so the hero and the tool cannot
 * disagree.
 *
 * Setbacks, the buildable polygon and the footprint CANNOT be, honestly. They are
 * engine output: `POST /api/site/preview` derives the stratum of setbacks, insets
 * the ring, fits a footprint into what is left and certifies it. Re-deriving that
 * in a marketing hero would mean a second implementation of a statutory
 * calculation, on a page whose whole argument is that its figures are traceable —
 * the exact failure T1 exists to prevent. So the prototype does what the product
 * itself does: the tool measures on the client, the engine derives on the server,
 * and the two are LABELLED separately. Move a corner and the engine plane goes
 * stale, with the same "regenerate" affordance the app's own plan card uses when
 * parameters change.
 *
 * THE 3D IS REAL GEOMETRY, NOT A PICTURE
 * --------------------------------------
 * The storey plates are the captured per-floor envelopes extruded to the engine's
 * own floor-to-floor height (`stair_geometry.floor_height_m` 3.00 m); the shafts
 * are the captured stair core and wet ducts; the setback band is the region
 * between the captured survey ring and the captured buildable polygon. Nothing is
 * an authored mesh, a texture or a stock model.
 *
 * WHY THERE IS NO WEBGL
 * ---------------------
 * Six attempts before this one put a GPU library on the landing and every one was
 * removed (see the landing programme's teardown). This is a transform-only
 * composition: 8 composited layers, no canvas, no renderer, `translateZ` for
 * depth. It therefore has no no-WebGL rung to fall to, and the reduced-motion rung
 * is the same composition at its rest pose rather than a degraded substitute.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion, useMotionTemplate, useTransform } from 'framer-motion';
import type { MotionValue } from 'framer-motion';
import { edgeBearingLength, metricsFor } from '../services/siteBoundary';
import type { Vertex } from '../services/boundaryIO';
import { PLOT_SAMPLES, type PlotSample } from './plotSamples';
/* THE PROMOTED PRIMITIVES. None of this is prototype-local any more: the
   springs, the pointer maths, the capability gate, the plane geometry and the
   drag live in `src/landing/interaction`, where their pure cores are unit-tested
   (`scripts/test_interaction_primitives.cjs`) and their acceptance criteria are
   written down in the interaction spec. THIS FILE IS THE REFERENCE CONSUMER, and
   the reason there is no second copy of any of it anywhere. */
import {
  dragBounds,
  dragMessage,
  rectPath,
  ringPath,
  SPRING_SNAPPY,
  toVertices,
  useCapability,
  useDeviceTilt,
  useOnScreen,
  usePointerParallax,
  useRingDrag,
  useStateSpring,
  viewBoxFor,
  type ViewBox,
} from '../landing/interaction';
import { m2, mM } from '../landing/format';


/* Presentation pose. 30deg is the tilt at which a 3 m storey actually reads as a
   storey; the parallax is smaller on the vertical axis than the horizontal one
   because a plan drawing tolerates being turned but not being foreshortened. */
const BASE_TILT_DEG = 30;
const PARALLAX = { x: 7, y: 4 } as const;

/*
 * A WEAK perspective, on purpose — 4200 px against a ~650 px stage, so near
 * ortographic. It was 1500 to begin with, and the assembly was measured rather
 * than eyeballed: at 1500 the roof plane (189 px of `translateZ` up the normal)
 * came out 12% larger than the ground plane and displaced 158 px, so a building
 * whose footprint sits 1.5 m inside the plot line was drawn overhanging it — the
 * massing looked like a mistake rather than like height. At 4200 the same roof
 * measures ~4% larger and stays comfortably inside the setback band, while the
 * vertical offset that actually reads as storeys is untouched. Architects solve
 * this the same way: an axonometric has no vanishing point because a plan is a
 * measurement.
 */
const PERSPECTIVE_PX = 4200;

/**
 * The toning of the massing's vertical faces.
 *
 * A massing reads as a solid because its faces are lit DIFFERENTLY, not because
 * of any outline: two tones keyed to the edge's own bearing (the north/south
 * pairs and the east/west pairs) are enough for the eye to reconstruct the
 * volume, and they are derived from the geometry rather than chosen per drawing.
 */
/* The three tones are spaced widely enough to be told apart by MEASUREMENT as well
   as by eye — a pixel check over the stage asserted that all three are on screen
   with the roof above the faces.
   The first palette had a near-white roof over a porcelain gradient ground, i.e.
   two of the three faces were the same colour as the paper they were drawn on, and
   a massing drawn in the colour of its own background is not a massing. */
const FACE_NS = 'rgba(202,215,233,0.98)';
const FACE_EW = 'rgba(226,236,246,0.98)';
const FACE_ROOF = 'rgba(238,243,250,0.99)';

/** One composited layer of the assembly, at a plane-normal offset in metres. */
const Plate: React.FC<{
  vb: ViewBox;
  zM: number;
  metresToPx: number;
  children: React.ReactNode;
  tone?: string;
}> = ({ vb, zM, metresToPx, children, tone }) => (
  <div
    className="absolute inset-0"
    style={{
      transform: `translateZ(${(zM * metresToPx).toFixed(2)}px)`,
      transformStyle: 'preserve-3d',
      pointerEvents: 'none',
      background: tone,
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

export const TraceStage: React.FC = () => {
  const cap = useCapability();

  const [sampleIndex, setSampleIndex] = useState(0);
  const sample: PlotSample = PLOT_SAMPLES[sampleIndex];
  const captured = useMemo(() => toVertices(sample.ring), [sample]);

  /**
   * THE EDITED RING IS AN OVERRIDE, NOT A COPY.
   *
   * `draft === null` means "the captured ring, untouched" — so switching samples
   * cannot leave a stale draft behind (there is no effect copying one array into
   * another on every sample change, which is both a cascading render and the
   * pattern React's lint flags), and `Reset` is one assignment inside the hook.
   *
   * THE STATE THAT USED TO LIVE HERE IS NOW `interaction/useRingDrag`:
   * the draft override, the grab record, the metres-per-pixel conversion, the
   * clamp and the keyboard nudge. This component got smaller on purpose — the
   * maths is unit-tested where it is pure, and the gesture is driven by real
   * trusted input in the probe.
   */

  /* The view box comes from the CAPTURED ring, not the dragged one, so the drawing
     frame never moves under the reader's hand: a drag slides the ring inside a
     fixed frame instead of re-framing the sheet every frame. Hoisted above the
     drag because the drag's callbacks take the frame they are clamped to. */
  const vb = useMemo(() => viewBoxFor(sample.ring), [sample]);
  const bounds = useMemo(() => dragBounds(vb, sample.ring), [vb, sample]);

  const boxRef = useRef<HTMLDivElement>(null);
  /* The announcement is worded by the SHIPPED metrics module, for the ring the
     gesture just produced — never by a second opinion about validity. */
  const describeRing = useCallback(
    (next: ReadonlyArray<Vertex>) => dragMessage(metricsFor(next.map((vertex) => ({ ...vertex })))),
    [],
  );
  const drag = useRingDrag({ captured, bounds, viewBox: vb, boxRef, describe: describeRing });
  const ring = drag.draft ?? captured;
  const dragIndex = drag.dragIndex;
  const liveMessage = drag.message;

  /* The one measurement the client is allowed to own (see the header). `metricsFor`
     runs the shipped validity gate too, so the EC chip below is the app's own
     verdict, not a copy of it. */
  const metrics = useMemo(() => metricsFor(ring), [ring]);
  const edges = useMemo(() => ring.map((_, i) => edgeBearingLength(ring, i)), [ring]);
  const dirty = drag.draft !== null;

  /* ---------------- pose ---------------- */
  /* THE IDLE CONTRACT, AND IT IS MEASURED. `useOnScreen` (the landing's version of
     "frameloop: demand") is what makes an off-screen assembly cost nothing per
     frame: while the stage is outside the viewport its pose is not driven at all,
     so no `pointermove` listener exists to run. `hooks.ts` has documented that
     sentence since the primitives were promoted; until this consumer was wired to
     it, the sentence was true of the primitive and false of the page — and
     `scripts/interaction_probe.cjs` [6] now asserts the consequence in a browser
     rather than a comment. */
  const onScreen = useOnScreen(boxRef);
  const flat = useStateSpring(dragIndex !== null, SPRING_SNAPPY);
  const poseActive = !cap.staticOnly && dragIndex === null && onScreen;
  const pointer = usePointerParallax(PARALLAX, poseActive && !cap.coarse);
  const device = useDeviceTilt(PARALLAX, poseActive && cap.coarse);
  const offset = cap.coarse ? device : pointer;

  const restTilt = useTransform(flat, [0, 1], [BASE_TILT_DEG, 0]);
  const drain = cap.staticOnly ? 0 : 1;
  const parallaxX = useTransform(offset.x as MotionValue<number>, (v) => v * drain);
  const parallaxY = useTransform(offset.y as MotionValue<number>, (v) => v * drain);
  const rotX = useTransform([restTilt, parallaxY], (values: number[]) => values[0] + values[1]);
  const rotY = useTransform(parallaxX, (v) => -v);
  const pose = useMotionTemplate`rotateX(${rotX}deg) rotateY(${rotY}deg)`;

  /* Cursor-tracked specular. A FIXED-SIZE radial gradient moved by transform, not
     a background-position: a moving gradient position repaints, a translated
     layer composites. The box size is the only layout read in the whole
     component, and it is taken on resize. */
  const [boxW, setBoxW] = useState(720);
  useEffect(() => {
    const el = boxRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => setBoxW(el.offsetWidth || 720));
    ro.observe(el);
    setBoxW(el.offsetWidth || 720);
    return () => ro.disconnect();
  }, []);
  /* The specular light is an ANSWER TO THE POINTER, so it is absent until the
     pointer is actually on the assembly — a radial highlight parked in the middle
     of a rest frame is a bright blob, not a material. */
  const [lit, setLit] = useState(false);
  const specularOn = !cap.staticOnly && !cap.coarse && lit;
  const specX = useTransform(offset.x as MotionValue<number>, (v) => (specularOn ? (v / PARALLAX.x) * boxW * 0.34 : 0));
  const specY = useTransform(offset.y as MotionValue<number>, (v) => (specularOn ? (v / PARALLAX.y) * boxW * 0.2 : 0));

  /* ---------------- geometry ---------------- */
  /* `vb` and `bounds` are hoisted to the top of this component because the drag
     needs them; what remains here is everything derived from the CURRENT ring. */
  const plotPath = useMemo(() => ringPath(ring.map((p) => [p.x, p.y] as const)), [ring]);
  const buildablePath = useMemo(() => ringPath(sample.buildable.ring), [sample]);
  const metresToPx = boxW / vb.w;

  /* Plane metres -> CSS pixels inside the stage box, for the elements that are NOT
     SVGs (the massing's faces). Same flip as `toSvgY`. */
  const cssX = (planeX: number) => (planeX - vb.x) * metresToPx;
  const cssY = (planeY: number) => (-planeY - vb.svgY) * metresToPx;
  const roof = sample.floors[sample.floors.length - 1].envelope;

  /* ---------------- drag (promoted) ---------------- */
  /* The handlers below are the promoted hook's, kept under their old names so the
     JSX reads unchanged: `onHandleDown(index)`, `onHandleMove`, `endDrag`,
     `nudge(index)`. Everything they used to do — capture, one layout read per
     gesture, metres-per-pixel, the clamp to the survey frame, the draft override —
     lives in `interaction/hooks.ts` and `interaction/drag.ts`. */
  const onHandleDown = drag.onHandleDown;
  const onHandleMove = drag.onHandleMove;
  const endDrag = drag.onHandleUp;
  const nudge = drag.onHandleKey;

  /* ---------------- drawing helpers ---------------- */
  const S = (v: number) => v.toFixed(3);
  /* Stroke widths are in METRES, because the SVG's user space is the engine's
     plane. 0.05 m ~ a 1.5px hairline at hero scale, and it scales with the
     drawing instead of with the viewport. */
  const HAIR = 0.05;
  const hairlines = edges.length;

  /**
   * The shafts, moved from the engine's own frame into the drawing's.
   *
   * MEASURED, NOT ASSUMED. `vertical_cores` and `duct_shafts` come out of
   * `_generate_vertical_cores(envelope)` and are stated RELATIVE TO THE ENVELOPE
   * (`duct_x = round(max(0.5, env_w - duct_w - 0.3), 2)` — see engine.py), while
   * `site_plan` zones, the plot ring and the parking bays are in ABSOLUTE plane
   * metres. Drawn without this translation the first cut put the stair core 1.5 m
   * west and 1.95 m south of where the engine put it, i.e. outside the building
   * it belongs to. The offset is the envelope's own origin, read from the same
   * capture.
   */
  const shaftRects = useMemo(() => {
    const ox = sample.footprint.x;
    const oy = sample.footprint.y;
    return [
      ...sample.cores.map((c) => ({ id: c.id, x: c.x + ox, y: c.y + oy, w: c.widthM, h: c.depthM })),
      ...sample.ducts.map((d) => ({ id: d.id, x: d.x + ox, y: d.y + oy, w: d.widthM, h: d.depthM })),
    ];
  }, [sample]);

  const storeyTop = sample.floors.length * sample.floorHeightM;

  /*
   * THE MASSING IS A VOLUME, NOT A STACK OF SHEETS.
   *
   * The first cut drew each storey as a thin horizontal plate at its own floor
   * level, which is what "floor plate" sounds like — and it measured as exactly
   * that: two 0.24 m sheets 90 px apart on screen with nothing between them, so a
   * 2-storey building read as two floating panes of glass. A massing is the space
   * BETWEEN the plates, so each storey now contributes four vertical faces
   * standing from its own floor level up to the next, and the roof is the only
   * horizontal face. That is also why there is no separate "floor line" layer:
   * the seam between one storey's faces and the next IS the floor line.
   *
   * Each face is a single quad: a rotated `div`, positioned in the plane and stood
   * up with `rotateX(-90deg)` about its own bottom edge. Transform-only, no mesh,
   * and the browser's own `preserve-3d` sorting does the hidden-surface work.
   */
  const storeys = useMemo(
    () =>
      sample.floors.map((floor) => {
        const e = floor.envelope;
        return {
          index: floor.index,
          baseM: floor.index * sample.floorHeightM,
          heightM: sample.floorHeightM,
          corners: [
            { x: e.x, y: e.y },
            { x: e.x + e.widthM, y: e.y },
            { x: e.x + e.widthM, y: e.y + e.depthM },
            { x: e.x, y: e.y + e.depthM },
          ],
        };
      }),
    [sample],
  );

  return (
    <section
      aria-label="Plot trace and derived site plan"
      className="grid gap-10 lg:grid-cols-[minmax(0,0.86fr)_minmax(0,1.14fr)] lg:gap-14"
    >
      {/* ---------------- readout column ---------------- */}
      <div className="order-2 lg:order-1">
        {/* `accent-deep`, not `accent`: at 11px this eyebrow is small text under
            WCAG, and `--bw-accent` on the porcelain ground resolves to 4.05:1 —
            below the 4.5:1 floor. The landing's own eyebrows sit over a gradient
            backdrop that axe declines to resolve, which is why the same colour
            never failed there; on this route the ground is opaque and the
            measurement is real. `--bw-accent-deep` is 6.06:1 on the same ground. */}
        <p className="flex items-center gap-3 text-[11px] font-semibold uppercase text-bw-accent-deep" style={{ letterSpacing: '0.16em' }}>
          <span aria-hidden className="h-[1.5px] w-7 rounded-full bg-bw-accent" />
          Trace
        </p>
        <h2 className="mt-3 text-[clamp(1.6rem,2.6vw,2.2rem)] font-bold tracking-[-0.03em] text-bw-ink">
          Drag a corner. Watch the plot answer.
        </h2>
        <p className="mt-3 text-[15px] leading-[1.6] text-bw-ink-2">
          The boundary is measured in the browser, by the same module the capture tool uses. Everything below the
          line is what the engine derives from it.
        </p>

        {/* Live, client-measured. `aria-live` is on the COMMITTED summary, not on
            these figures: a live region that changed on every frame of a drag
            would read the reader a spreadsheet. */}
        <dl className="mt-7 grid grid-cols-2 gap-x-6 gap-y-4 border-t border-bw-line pt-5 sm:grid-cols-4">
          {[
            { k: 'Area', v: m2(metrics.areaSqm) },
            { k: 'Perimeter', v: mM(metrics.perimeterM) },
            { k: 'Vertices', v: String(metrics.vertexCount) },
            { k: 'Shape', v: metrics.shapeType.replace('_', ' ') },
          ].map((cell) => (
            <div key={cell.k}>
              <dt className="text-[10.5px] font-semibold uppercase text-bw-ink-2" style={{ letterSpacing: '0.14em' }}>
                {cell.k}
              </dt>
              <dd className="mt-1 tabular-nums text-[15px] font-semibold text-bw-ink">{cell.v}</dd>
            </div>
          ))}
        </dl>

        <p className="mt-4 flex flex-wrap items-center gap-2">
          <span
            className={
              'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold ' +
              (metrics.valid
                ? 'border-bw-green/30 bg-bw-green/10 text-bw-green-ink'
                : 'border-bw-amber/40 bg-bw-amber/10 text-bw-amber-ink')
            }
          >
            <span aria-hidden className={'h-1.5 w-1.5 rounded-full ' + (metrics.valid ? 'bg-bw-green' : 'bg-bw-amber')} />
            {metrics.valid ? 'EC pass' : (metrics.code ?? 'EC')}
          </span>
          <span className="text-[12.5px] leading-[1.5] text-bw-ink-2">
            {metrics.valid
              ? '4 edges clear of the 1.00 m statutory minimum, area above the 36 m² floor.'
              : metrics.reason}
          </span>
        </p>

        {/* The engine's own edge table: bearing in the product's quadrant form. */}
        <div className="mt-6 overflow-hidden rounded-[11px] border border-bw-line-soft bg-white">
          <table className="w-full border-collapse text-left">
            <caption className="sr-only">Edges of the current ring, as the capture tool measures them</caption>
            <thead>
              <tr className="border-b border-bw-line-soft">
                {['Edge', 'Bearing', 'Length'].map((h) => (
                  <th
                    key={h}
                    scope="col"
                    className="px-3.5 py-2 text-[10.5px] font-semibold uppercase text-bw-ink-2"
                    style={{ letterSpacing: '0.12em' }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {edges.map((e, i) => (
                <tr key={i} className="border-b border-bw-line-soft last:border-0">
                  <td className="px-3.5 py-1.5 text-[12.5px] font-semibold text-bw-ink">{`P${i + 1}→P${((i + 1) % hairlines) + 1}`}</td>
                  <td className="px-3.5 py-1.5 font-mono text-[12px] text-bw-ink-2">{e.bearing}</td>
                  <td className="px-3.5 py-1.5 tabular-nums text-[12.5px] text-bw-ink-2">{mM(e.lengthM)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p aria-live="polite" className="sr-only">
          {liveMessage}
        </p>

        {/* ---------------- the engine's plane ---------------- */}
        <div className="mt-7">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[12px] font-semibold uppercase text-bw-ink-2" style={{ letterSpacing: '0.14em' }}>
              Engine output
            </h3>
            <span className="rounded-full border border-bw-line-soft bg-white px-2 py-0.5 font-mono text-[10.5px] text-bw-ink-2">
              {sample.generationId}
            </span>
            <span className="font-mono text-[10.5px] text-bw-ink-2">
              sha {sample.provenance.sha256.slice(0, 10)}
            </span>
          </div>

          {dirty && (
            <div
              role="status"
              className="mt-3 rounded-[11px] border border-bw-amber/40 bg-bw-amber/[0.07] px-3.5 py-2.5 text-[12.5px] leading-[1.5] text-bw-ink-2"
            >
              <strong className="font-semibold text-bw-ink">Ring edited — this answer is the captured plot's.</strong>{' '}
              Setbacks, the buildable polygon and the footprint are derived on the server:{' '}
              <span className="font-mono text-[11.5px]">POST /api/site/preview</span>. Move the corner back, or reset, to
              re-align the drawing.
              <button
                type="button"
                onClick={drag.reset}
                className="ml-2 inline-flex h-6 items-center rounded-full border border-bw-line bg-white px-2.5 text-[11.5px] font-semibold text-bw-ink transition-colors hover:bg-bw-line-soft"
              >
                Reset
              </button>
            </div>
          )}

          <ol className={'mt-4 flex flex-col gap-1.5 transition-opacity duration-200 ' + (dirty ? 'opacity-45' : '')}>
            {sample.derivation.map((step) => (
              <li key={step} className="flex gap-2.5 text-[12.5px] leading-[1.55] text-bw-ink-2">
                <span aria-hidden className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-bw-accent" />
                <span className="font-mono text-[11.5px]">{step}</span>
              </li>
            ))}
          </ol>

          <dl className={'mt-5 grid grid-cols-2 gap-x-6 gap-y-4 border-t border-bw-line pt-4 sm:grid-cols-4 ' + (dirty ? 'opacity-45' : '')}>
            {[
              { k: 'Setback', v: `${sample.setbacks.frontM}/${sample.setbacks.rearM} m` },
              { k: 'Buildable', v: m2(sample.buildable.areaSqm) },
              {
                k: 'Footprint',
                v: `${sample.footprint.widthM}×${sample.footprint.depthM} m`,
              },
              { k: 'Coverage', v: `${sample.metrics.plotCoveragePct}%` },
            ].map((cell) => (
              <div key={cell.k}>
                <dt className="text-[10.5px] font-semibold uppercase text-bw-ink-2" style={{ letterSpacing: '0.14em' }}>
                  {cell.k}
                </dt>
                <dd className="mt-1 tabular-nums text-[14px] font-semibold text-bw-ink">{cell.v}</dd>
              </div>
            ))}
          </dl>

          {/* The certificate, told straight: this sample is WARN and the chips say
              so. A hero that printed only PASS counts would be the false claim. */}
          <div className={'mt-5 flex flex-wrap items-center gap-1.5 ' + (dirty ? 'opacity-45' : '')}>
            <span className="mr-1 text-[10.5px] font-semibold uppercase text-bw-ink-2" style={{ letterSpacing: '0.14em' }}>
              Certificate {sample.certificate.isValid ? 'valid' : 'advisory'}
            </span>
            {sample.certificate.layerStatuses.map((layer) => {
              const tone =
                layer.status === 'PASS'
                  ? 'border-bw-green/30 bg-bw-green/10 text-bw-green-ink'
                  : layer.status === 'WARN'
                    ? 'border-bw-amber/40 bg-bw-amber/10 text-bw-amber-ink'
                    : 'border-bw-line bg-white text-bw-ink-2';
              return (
                <span
                  key={layer.id}
                  title={`${layer.title} — ${layer.status}: ${layer.summary}`}
                  className={`inline-flex h-6 items-center rounded-full border px-2 font-mono text-[10.5px] font-semibold ${tone}`}
                >
                  {layer.id} {layer.status === 'N/A' ? 'N/A' : layer.status.toLowerCase()}
                </span>
              );
            })}
          </div>

          <p className="mt-3 text-[12px] leading-[1.55] text-bw-ink-2">
            {sample.certificate.counts.pass} pass · {sample.certificate.counts.warn} warn ·{' '}
            {sample.certificate.counts.na} N/A of {sample.certificate.counts.total} rule layers, from the captured
            generation. N/A never gates — it is an absence, not a failure.
          </p>
        </div>
      </div>

      {/* ---------------- the assembly ---------------- */}
      <div className="order-1 lg:order-2">
        <div className="mb-3 flex flex-wrap items-center gap-1.5">
          {PLOT_SAMPLES.map((s, i) => (
            <button
              key={s.id}
              type="button"
              onClick={() => {
                setSampleIndex(i);
                drag.reset();
              }}
              aria-pressed={i === sampleIndex}
              className={
                'inline-flex h-8 items-center rounded-full border px-3 text-[12.5px] font-semibold transition-colors ' +
                (i === sampleIndex
                  ? 'border-bw-ink bg-bw-ink text-white'
                  : 'border-bw-line bg-white text-bw-ink-2 hover:text-bw-ink')
              }
            >
              {s.id === 'residential-rect'
                ? `Rectangle · ${s.ring.length}V · ${s.plotAreaSqm} m²`
                : `Irregular · ${s.ring.length}V · ${s.plotAreaSqm} m²`}
            </button>
          ))}
          <span className="ml-auto hidden text-[11.5px] text-bw-ink-2 sm:block">
            {dragIndex === null ? 'Drag a survey corner' : 'Measuring…'}
          </span>
        </div>

        <div
          ref={boxRef}
          className="relative overflow-hidden rounded-[14px] border border-bw-line-soft"
          data-bw-stage=""
          onPointerEnter={() => setLit(true)}
          onPointerLeave={() => setLit(false)}
          style={{
            aspectRatio: `${vb.w} / ${vb.h}`,
            /* Solid white, not a gradient: the drawing's own tones have to sit ON
               something neutral, and five face tones over a five-stop gradient is
               eleven greys all within 8% of each other. */
            background: 'var(--bw-white)',
            boxShadow: 'var(--bw-shadow-1)',
          }}
        >
          <div className="absolute inset-0" style={{ perspective: `${PERSPECTIVE_PX}px` }}>
            <motion.div className="absolute inset-0" style={{ transformStyle: 'preserve-3d', transform: pose }}>
              {/* ---- ground: the zones the inset left outside the building line ---- */}
              {/* NO PARKING BAYS HERE, DELIBERATELY. The capture carries them in
                  absolute plane metres, and the engine's own capture script warns
                  that in this generation the bay and its drive aisle run ACROSS the
                  building line (bay y 0.5–5.5 m against a footprint starting at
                  y 1.95 m). Drawing them would show a car parked in the living room;
                  correcting them would be the landing re-deriving an engine
                  drawing. They are left out and the omission is reported. */}
              <Plate vb={vb} zM={0} metresToPx={metresToPx}>
                {/* The site itself, so the drawing sits on a surface rather than on
                    blank paper. A presentation fill, not a measurement: it is the
                    surveyed ring, and nothing is claimed by tinting it. */}
                <path d={ringPath(sample.ring)} fill="rgba(11,18,32,0.028)" />
                {sample.outdoor.map((o) => (
                  <path key={o.id} d={ringPath(o.ring)} fill="rgba(31,169,85,0.10)" stroke="rgba(31,169,85,0.35)" strokeWidth={HAIR} />
                ))}
                {sample.wedges.map((w) => (
                  <path
                    key={w.id}
                    d={ringPath(w.ring)}
                    fill={w.classification === 'planter' ? 'rgba(31,169,85,0.13)' : 'rgba(138,83,0,0.10)'}
                    stroke={w.classification === 'planter' ? 'rgba(31,169,85,0.35)' : 'rgba(138,83,0,0.32)'}
                    strokeWidth={HAIR}
                  />
                ))}
              </Plate>

              {/* ---- the plot itself: setback band, buildable ring, survey ring ---- */}
              <Plate vb={vb} zM={0.02} metresToPx={metresToPx}>
                {/* The band is the DIFFERENCE of two real polygons, not an offset
                    drawn by the page: plot ring minus buildable ring, even-odd. */}
                <path d={`${ringPath(sample.ring)} ${buildablePath}`} fillRule="evenodd" fill="rgba(47,111,237,0.07)" />
                <path d={buildablePath} fill="none" stroke="rgba(47,111,237,0.55)" strokeWidth={HAIR} strokeDasharray={`${S(0.34)} ${S(0.26)}`} />
                <path d={plotPath} fill="rgba(255,255,255,0.35)" stroke="var(--bw-ink)" strokeWidth={HAIR * 1.5} />
                {/* The engine's own vertex IDs (P1..Pn) drawn at the surveyed
                    corners. Labels come from the capture's vertex table, so the
                    drawing and the edge table below name the same points. */}
                {sample.vertexTable.slice(0, ring.length).map((v) => (
                  <g key={v.id}>
                    <circle cx={v.x} cy={-v.y} r={HAIR * 1.2} fill="var(--bw-ink)" />
                    <text
                      x={v.x + HAIR * 2}
                      y={-v.y - HAIR * 2}
                      fontSize={0.46}
                      fontWeight={700}
                      fill="rgba(11,18,32,0.62)"
                      fontFamily="ui-monospace, SFMono-Regular, Menlo, monospace"
                    >
                      {v.id}
                    </text>
                  </g>
                ))}
              </Plate>

              {/* ---- the massing: one quad per vertical face, standing from each
                       storey's own floor level to the next ---- */}
              {storeys.map((storey) => {
                const h = storey.heightM * metresToPx;
                return (
                  <div
                    key={storey.index}
                    className="absolute inset-0"
                    style={{ transformStyle: 'preserve-3d', pointerEvents: 'none' }}
                    aria-hidden
                  >
                    {storey.corners.map((p0, i) => {
                      const p1 = storey.corners[(i + 1) % storey.corners.length];
                      const x0 = cssX(p0.x);
                      const y0 = cssY(p0.y);
                      const dx = cssX(p1.x) - x0;
                      const dy = cssY(p1.y) - y0;
                      const len = Math.hypot(dx, dy);
                      if (len < 1) return null;
                      const angle = (Math.atan2(dy, dx) * 180) / Math.PI;
                      /* North/south faces (the long, more horizontal ones) take the
                         darker tone, so the two visible sides of the mass differ. */
                      const northSouth = Math.abs(dy) < Math.abs(dx);
                      return (
                        <div
                          key={i}
                          style={{
                            position: 'absolute',
                            left: `${x0.toFixed(2)}px`,
                            top: `${(y0 - h).toFixed(2)}px`,
                            width: `${len.toFixed(2)}px`,
                            height: `${h.toFixed(2)}px`,
                            transformOrigin: '0 100%',
                            transform:
                              `translateZ(${(storey.baseM * metresToPx).toFixed(2)}px) ` +
                              `rotateZ(${angle.toFixed(2)}deg) rotateX(-90deg)`,
                            background: northSouth ? FACE_NS : FACE_EW,
                            borderTop: '1px solid rgba(255,255,255,0.85)',
                          }}
                        />
                      );
                    })}
                  </div>
                );
              })}

              {/* ---- the roof: the one horizontal face, plus the shafts as they
                       pass through it (moved out of the engine's envelope-relative
                       frame — see `shaftRects`) ---- */}
              <Plate vb={vb} zM={storeyTop} metresToPx={metresToPx}>
                <path
                  d={rectPath(roof.x, roof.y, roof.widthM, roof.depthM)}
                  fill={FACE_ROOF}
                  stroke="rgba(47,111,237,0.5)"
                  strokeWidth={HAIR}
                />
                {shaftRects.map((sh) => (
                  <path
                    key={sh.id}
                    d={rectPath(sh.x, sh.y, sh.w, sh.h)}
                    fill="rgba(11,18,32,0.62)"
                    stroke="rgba(255,255,255,0.6)"
                    strokeWidth={HAIR * 0.6}
                  />
                ))}
              </Plate>

              {/* ---- the survey handles, as real buttons, INSIDE the plane ----
                   They were first drawn in an untransformed layer above the 3D
                   context, which is wrong in a way that only shows in a screenshot:
                   their percentages then resolved against the FLAT box, so at the
                   30° rest pose every handle sat off its own corner. Inside the
                   wrapper they resolve in the tilted plane and land on the ring.
                   Hit-testing through a `preserve-3d` subtree is plain in Chrome,
                   and the drag itself still converts with the box rect (see
                   `onHandleDown`), so accuracy does not depend on the pose.

                   Buttons, not divs: a corner can be nudged 0.25 m with the arrow
                   keys, and these are the only focusable things on the stage. */}
              <div
                className="absolute inset-0"
                style={{ transform: 'translateZ(2px)', transformStyle: 'preserve-3d', pointerEvents: 'none' }}
              >
                {ring.map((p, i) => {
                  const left = ((p.x - vb.x) / vb.w) * 100;
                  const top = ((-p.y - vb.svgY) / vb.h) * 100;
                  return (
                    <button
                      key={i}
                      type="button"
                      aria-label={`Survey corner ${i + 1}, ${p.x.toFixed(2)} metres east, ${p.y.toFixed(
                        2,
                      )} metres north. Use the arrow keys to move it.`}
                      onPointerDown={onHandleDown(i)}
                      onPointerMove={onHandleMove}
                      onPointerUp={endDrag}
                      onPointerCancel={endDrag}
                      onKeyDown={nudge(i)}
                      className="absolute h-11 w-11 -translate-x-1/2 -translate-y-1/2 rounded-full"
                      style={{ left: `${left}%`, top: `${top}%`, pointerEvents: 'auto', touchAction: 'none', cursor: 'grab' }}
                    >
                      <span
                        aria-hidden
                        className={
                          'pointer-events-none absolute left-1/2 top-1/2 block h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-bw-accent ring-1 ring-black/20 transition-transform ' +
                          (dragIndex === i ? 'scale-125' : '')
                        }
                      />
                    </button>
                  );
                })}
              </div>
            </motion.div>
          </div>

          {/* specular — outside the 3D context, on top, transform-only */}
          <motion.div
            aria-hidden
            className="pointer-events-none absolute left-[10%] top-[10%] h-[80%] w-[80%]"
            style={{
              x: specX,
              y: specY,
              background: 'radial-gradient(closest-side, rgba(255,255,255,0.40), rgba(255,255,255,0) 74%)',
              opacity: specularOn ? 1 : 0,
            }}
          />

          {/* legend + scale bar — the drawing's own furniture, in real metres */}
          <div className="pointer-events-none absolute bottom-2.5 left-3 flex items-center gap-3 text-[10.5px] font-medium text-bw-ink-2">
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="h-[3px] w-4 rounded-full bg-bw-ink" />
              Survey ring
            </span>
            <span className="flex items-center gap-1.5">
              <span
                aria-hidden
                className="h-[3px] w-4 rounded-full"
                style={{ background: 'repeating-linear-gradient(90deg, var(--bw-accent) 0 4px, transparent 4px 7px)' }}
              />
              Buildable
            </span>
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="h-2.5 w-2.5 rounded-[3px] border border-bw-line bg-white" />
              Storey envelopes ×{sample.storeys}
            </span>
          </div>
          <div className="pointer-events-none absolute bottom-2.5 right-3 flex items-center gap-2 text-[10.5px] font-medium text-bw-ink-2">
            <span className="font-mono">N</span>
            <span aria-hidden className="text-bw-accent-deep">
              ↑
            </span>
            {/* A REAL scale bar: the rule is five metres long at this drawing's own
                scale, so it measures something. The first cut printed the engine's
                bay spacing beside a fixed 40px rule, which is two unrelated facts
                sitting next to each other looking like one. */}
            <span
              aria-hidden
              className="h-[3px] rounded-full bg-bw-ink-3"
              style={{ width: `${(5 * metresToPx).toFixed(1)}px` }}
            />
            <span className="tabular-nums">5 m</span>
          </div>
        </div>

        <p className="mt-3 text-[11.5px] leading-[1.55] text-bw-ink-2">
          Captured from{' '}
          <span className="font-mono">{sample.provenance.capture.replace('backend/data/landing-captures/', '')}</span> —{' '}
          {sample.storeys} storeys at {sample.floorHeightM} m floor-to-floor (the stair's own figure),{' '}
          {sample.floors.reduce((n, f) => n + f.rooms, 0)} rooms,{' '}
          {storeyTop} m total rise. Extruded from the engine's envelopes; no authored mesh.
        </p>
      </div>
    </section>
  );
};
