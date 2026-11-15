/**
 * landing/router.ts — minimal pathname routing for the two BuildWise
 * surfaces: the marketing landing ("/") and the analysis tool ("/app").
 * History-API based; Vite's SPA fallback serves index.html for /app.
 */
import { useEffect, useState } from 'react';

export const APP_PATH = '/app';
export const LANDING_PATH = '/';
export const SIGN_IN_PATH = '/sign-in';
export const SIGN_UP_PATH = '/sign-up';
export const FORGOT_PASSWORD_PATH = '/forgot-password';
export const RESET_PASSWORD_PATH = '/reset-password';
/**
 * Prefix for the unlinked, `noindex` prototype routes (`/preview/...`).
 *
 * A real path prefix rather than a query parameter on `/`, deliberately: a
 * prototype that lived at `/?proto=trace` would share the landing's document, its
 * indexed URL and its boot shell, so a search engine would index a marketing page
 * that is part experiment. A prefix is excluded by `robots.txt` (the one place
 * the protocol actually allows a page to opt out) and by a `robots` meta tag set
 * when the route mounts.
 */
export const PREVIEW_PREFIX = '/preview';

export function currentPath(): string {
  if (typeof window === 'undefined') return LANDING_PATH;
  return window.location.pathname;
}

/** Programmatic navigation that also notifies same-tab listeners. */
export function navigate(to: string): void {
  if (currentPath() === to) return;
  window.history.pushState({}, '', to);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

/** Subscribe to pathname changes (back/forward + programmatic nav). */
export function usePathname(): string {
  const [path, setPath] = useState(currentPath);
  useEffect(() => {
    const onNav = () => setPath(currentPath());
    window.addEventListener('popstate', onNav);
    return () => window.removeEventListener('popstate', onNav);
  }, []);
  return path;
}
