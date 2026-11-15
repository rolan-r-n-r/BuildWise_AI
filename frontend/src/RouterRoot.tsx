/**
 * RouterRoot.tsx — BuildWise Application Routing:
 *   "/"                → marketing landing page (scrolling, Lenis-smoothed)
 *   "/sign-in"         → user login
 *   "/sign-up"         → user registration
 *   "/forgot-password" → OTP password recovery
 *   "/reset-password"  → OTP verification & password reset
 *   "/app"             → authenticated multi-user site-analysis tool (protected route)
 *
 * All routes are code-split for performance and isolated dependency graphs.
 */
import { Suspense, lazy, useEffect, useState } from 'react';
import {
  APP_PATH,
  SIGN_IN_PATH,
  SIGN_UP_PATH,
  FORGOT_PASSWORD_PATH,
  RESET_PASSWORD_PATH,
  PREVIEW_PREFIX,
  currentPath,
  navigate,
  usePathname,
} from './landing/router';
import { useSession, getSession } from './lib/auth-client';

const App = lazy(() => import('./App'));
const LandingPage = lazy(() =>
  import('./landing/LandingPage').then((m) => ({ default: m.LandingPage })),
);
const SignInPage = lazy(() =>
  import('./auth/SignInPage').then((m) => ({ default: m.SignInPage })),
);
const SignUpPage = lazy(() =>
  import('./auth/SignUpPage').then((m) => ({ default: m.SignUpPage })),
);
const ForgotPasswordPage = lazy(() =>
  import('./auth/ForgotPasswordPage').then((m) => ({ default: m.ForgotPasswordPage })),
);
const ResetPasswordPage = lazy(() =>
  import('./auth/ResetPasswordPage').then((m) => ({ default: m.ResetPasswordPage })),
);

const PREVIEW_ENABLED = import.meta.env.DEV || import.meta.env.VITE_PREVIEW_PROTOTYPES === '1';
const PreviewTrace = PREVIEW_ENABLED
  ? lazy(() => import('./preview/PreviewTrace').then((m) => ({ default: m.PreviewTrace })))
  : null;

const APP_TITLE = 'BuildWise AI - Geo-Based Intelligent Construction Planning';

/** Route-level loading placeholder. */
const RouteFallback: React.FC = () => (
  <div
    className="fixed inset-0 flex items-center justify-center bg-slate-50 dark:bg-slate-900"
    aria-busy="true"
    aria-live="polite"
  >
    <div className="flex flex-col items-center gap-2">
      <span className="w-5 h-5 border-2 border-slate-300 dark:border-slate-700 border-t-[var(--accent)] rounded-full animate-spin" />
      <span className="text-[12px] font-semibold tracking-wide text-slate-400 select-none">
        BuildWise AI
      </span>
    </div>
  </div>
);

/** Protected Route wrapper for /app ensuring only authenticated sessions enter the tool. */
const ProtectedApp: React.FC = () => {
  const { data: session, isPending } = useSession();
  const [isVerifying, setIsVerifying] = useState(false);

  useEffect(() => {
    if (!isPending && !session) {
      // Before bouncing to sign-in, double check directly with getSession()
      // to resolve any race conditions with un-hydrated in-memory session atoms
      let isMounted = true;
      setIsVerifying(true);
      getSession()
        .then((res) => {
          if (!isMounted) return;
          if (!res?.data?.session) {
            const destination = currentPath();
            const redirectQuery =
              destination && destination !== APP_PATH
                ? `?redirect=${encodeURIComponent(destination)}`
                : `?redirect=${encodeURIComponent(APP_PATH)}`;
            navigate(`${SIGN_IN_PATH}${redirectQuery}`);
          }
        })
        .catch(() => {
          if (!isMounted) return;
          navigate(SIGN_IN_PATH);
        })
        .finally(() => {
          if (isMounted) setIsVerifying(false);
        });

      return () => {
        isMounted = false;
      };
    }
  }, [session, isPending]);

  if (isPending || isVerifying || !session) {
    return <RouteFallback />;
  }

  return <App />;
};

export function RouterRoot() {
  const path = usePathname();
  const isApp = path === APP_PATH || path.startsWith(`${APP_PATH}/`);
  const isPreview = path === PREVIEW_PREFIX || path.startsWith(`${PREVIEW_PREFIX}/`);
  const isSignIn = path === SIGN_IN_PATH || path.startsWith(`${SIGN_IN_PATH}/`);
  const isSignUp = path === SIGN_UP_PATH || path.startsWith(`${SIGN_UP_PATH}/`);
  const isForgotPassword =
    path === FORGOT_PASSWORD_PATH || path.startsWith(`${FORGOT_PASSWORD_PATH}/`);
  const isResetPassword =
    path === RESET_PASSWORD_PATH || path.startsWith(`${RESET_PASSWORD_PATH}/`);

  useEffect(() => {
    if (isApp) {
      document.title = APP_TITLE;
      window.scrollTo(0, 0);
    } else if (isSignIn) {
      document.title = 'Sign In — BuildWise AI';
    } else if (isSignUp) {
      document.title = 'Create Account — BuildWise AI';
    } else if (isForgotPassword || isResetPassword) {
      document.title = 'Password Recovery — BuildWise AI';
    } else {
      document.title = 'BuildWise AI — Intelligent Construction Planning';
    }
  }, [isApp, isSignIn, isSignUp, isForgotPassword, isResetPassword]);

  return (
    <Suspense fallback={<RouteFallback />}>
      {isPreview && PreviewTrace ? (
        <PreviewTrace />
      ) : isSignIn ? (
        <SignInPage />
      ) : isSignUp ? (
        <SignUpPage />
      ) : isForgotPassword ? (
        <ForgotPasswordPage />
      ) : isResetPassword ? (
        <ResetPasswordPage />
      ) : isApp ? (
        <ProtectedApp />
      ) : (
        <LandingPage />
      )}
    </Suspense>
  );
}
