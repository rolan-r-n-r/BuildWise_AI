/**
 * RouterRoot.tsx — two BuildWise surfaces:
 *   "/"    → marketing landing page (scrolling, Lenis-smoothed)
 *   "/app" → the full-screen site-analysis tool
 *
 * Both routes are code-split so neither pays for the other's graph:
 *   - the landing (framer-motion + Lenis) is never parsed on /app
 *   - MapLibre + the whole analysis tool is never parsed on /
 * The shared React runtime lives in its own chunk and is reused once the user
 * crosses routes, so switching surfaces costs one chunk fetch, not a re-parse.
 */
import { Suspense, lazy, useEffect } from 'react'
import { APP_PATH, PREVIEW_PREFIX, usePathname } from './landing/router'

const App = lazy(() => import('./App'))
const LandingPage = lazy(() =>
  import('./landing/LandingPage').then((m) => ({ default: m.LandingPage })),
)
/**
 * Centrepiece prototype — UNLINKED, `noindex`, and NOT IN THE SHIPPED
 * GRAPH.
 *
 * A prototype under review must not move the artifact it is asking to join. A
 * first cut of this route was always-compiled and its measurements proved why
 * that is the wrong shape: a third dynamic entry made the bundler re-group shared
 * chunks, so `useTransform` left the landing's route chunk for a shared chunk the
 * landing now also loads (landing initial JS +1.22 KB gz) and `/app`'s initial
 * graph gained a module key it did not have (`_api.js`, +0.24 KB gz). The
 * `assert:bundle_split` gate caught both — correctly — and the honest fix is not
 * to widen the gate but to keep the experiment out of the product's graph.
 *
 * So the route is reachable in `vite dev` (where the prototype is reviewed) and
 * in a measurement build built with `VITE_PREVIEW_PROTOTYPES=1`, where the whole
 * production pipeline — minification, chunking, the boot plugin — applies, so the
 * frame histogram and the screenshots are taken on a real build rather than on a
 * dev-server approximation. A plain `npm run build` constant-folds this away and
 * emits exactly the chunk graph the landing had before the prototype existed.
 */
const PREVIEW_ENABLED = import.meta.env.DEV || import.meta.env.VITE_PREVIEW_PROTOTYPES === '1';
const PreviewTrace = PREVIEW_ENABLED
  ? lazy(() => import('./preview/PreviewTrace').then((m) => ({ default: m.PreviewTrace })))
  : null;

const APP_TITLE = 'BuildWise AI - Geo-Based Intelligent Construction Planning';

/**
 * Route-level loading placeholder. Deliberately static (no animation, no image,
 * no web font dependency) so it costs nothing while the route chunk arrives, and
 * fixed-positioned so it cannot shift the layout it is about to hand over.
 *
 * It is deliberately NOT the app's map placeholder: that was measured (mobile
 * preset, dist-b5) and did not help — Chrome re-candidates the largest paint when
 * the route tree swaps in, so the LCP stayed on the app's own placeholder while
 * the first paint got ~0.7 s later and CLS appeared (0.0005) from the hand-off.
 * The first view of /app is the app shell's placeholder; this splash is only the
 * bridge while the route chunk parses.
 */
const RouteFallback: React.FC = () => (
  <div
    className="fixed inset-0 flex items-center justify-center bg-slate-50"
    aria-busy="true"
    aria-live="polite"
  >
    <span className="text-[13px] font-semibold tracking-wide text-slate-400 select-none">
      BuildWise AI
    </span>
  </div>
);

export function RouterRoot() {
  const path = usePathname()
  const isApp = path === APP_PATH || path.startsWith(`${APP_PATH}/`)
  const isPreview = path === PREVIEW_PREFIX || path.startsWith(`${PREVIEW_PREFIX}/`)

  useEffect(() => {
    if (isApp) {
      document.title = APP_TITLE;
      window.scrollTo(0, 0);
    }
  }, [isApp])

  return (
    <Suspense fallback={<RouteFallback />}>
      {isPreview && PreviewTrace ? <PreviewTrace /> : isApp ? <App /> : <LandingPage />}
    </Suspense>
  )
}
