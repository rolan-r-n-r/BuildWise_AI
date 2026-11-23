/**
 * SignInPage.tsx — Secure Email & Password Login Screen.
 * Integrates with Better Auth client signIn.email with caps lock detection,
 * inline validation, password visibility toggling, and clean redirect preservation.
 */
import React, { useState, useEffect } from 'react';
import { AuthLayout } from './AuthLayout';
import { APP_PATH, FORGOT_PASSWORD_PATH, SIGN_UP_PATH, VERIFY_EMAIL_PATH, navigate } from '../landing/router';
import { signIn, useSession, getSession } from '../lib/auth-client';
import { Icon } from '../components/Icon';

export const SignInPage: React.FC = () => {
  const { data: sessionData, isPending: sessionPending } = useSession();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const [isCapsOn, setIsCapsOn] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isUnverified, setIsUnverified] = useState(false);

  // Preserve intended internal destination safely
  const getRedirectDestination = (): string => {
    try {
      const params = new URLSearchParams(window.location.search);
      const redirect = params.get('redirect');
      if (redirect && redirect.startsWith('/') && !redirect.startsWith('//')) {
        return redirect;
      }
    } catch {
      // fallback
    }
    return APP_PATH;
  };

  // If already authenticated and verified, redirect immediately; if unverified, redirect to /verify-email
  useEffect(() => {
    if (!sessionPending && sessionData?.session) {
      if (sessionData.user?.emailVerified) {
        window.location.replace(getRedirectDestination());
      } else if (sessionData.user?.email) {
        navigate(`${VERIFY_EMAIL_PATH}?email=${encodeURIComponent(sessionData.user.email)}`);
      }
    }
  }, [sessionData, sessionPending]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.getModifierState && e.getModifierState('CapsLock')) {
      setIsCapsOn(true);
    } else {
      setIsCapsOn(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password) {
      setErrorMessage('Please enter both your work email and password.');
      return;
    }

    setIsLoading(true);
    setErrorMessage(null);
    setIsUnverified(false);

    try {
      const res = await signIn.email({
        email: email.trim(),
        password,
        rememberMe,
      });

      if (res.error) {
        const isNotVerified =
          res.error.code === 'EMAIL_NOT_VERIFIED' ||
          res.error.status === 403 ||
          (res.error.message && res.error.message.toLowerCase().includes('verification'));

        setIsUnverified(Boolean(isNotVerified));
        setErrorMessage(
          res.error.message || 'Invalid email or password. Please verify your credentials and try again.'
        );
        setIsLoading(false);
        return;
      }

      // Refresh in-memory session atom so ProtectedApp immediately recognises authenticated state
      await getSession().catch(() => {});

      // Successful login -> navigate to intended destination cleanly
      const destination = getRedirectDestination();
      window.location.replace(destination);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'An unexpected network error occurred. Please try again.';
      setErrorMessage(message);
      setIsLoading(false);
    }
  };

  return (
    <AuthLayout
      title="Welcome back"
      subtitle="Sign in to your BuildWise account to access your feasibility studies and architectural dossiers."
      badge="Sign In"
    >
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        {/* Error Notification */}
        {errorMessage && (
          <div
            role="alert"
            className="p-3.5 rounded-[12px] bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900/60 text-red-700 dark:text-red-300 text-[12px] flex flex-col gap-2.5 animate-in fade-in duration-150"
          >
            <div className="flex items-start gap-2.5">
              <Icon name="alert-triangle" size={15} className="shrink-0 mt-0.5 text-red-600 dark:text-red-400" />
              <span className="flex-1 leading-relaxed font-medium">{errorMessage}</span>
            </div>
            {isUnverified && (
              <button
                type="button"
                onClick={() =>
                  navigate(`${VERIFY_EMAIL_PATH}?email=${encodeURIComponent(email.trim())}`)
                }
                className="self-start text-[11.5px] font-semibold text-[var(--accent)] hover:underline inline-flex items-center gap-1 cursor-pointer ml-6"
              >
                <span>Verify email address now</span>
                <Icon name="chevron-right" size={12} />
              </button>
            )}
          </div>
        )}

        {/* Email Field */}
        <div>
          <label
            htmlFor="signin-email"
            className="block text-[12px] font-semibold text-[var(--text-1)] mb-1.5"
          >
            Work Email Address
          </label>
          <div className="relative">
            <input
              id="signin-email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={isLoading}
              placeholder="architect@studio.com"
              className="w-full h-11 px-3.5 rounded-[12px] bg-slate-50 dark:bg-slate-800/80 border border-slate-300 dark:border-slate-700 text-[13.5px] text-[var(--text-1)] placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/30 focus:border-[var(--accent)] transition-colors"
            />
          </div>
        </div>

        {/* Password Field */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label
              htmlFor="signin-password"
              className="text-[12px] font-semibold text-[var(--text-1)]"
            >
              Password
            </label>
            <button
              type="button"
              onClick={() => navigate(FORGOT_PASSWORD_PATH)}
              className="text-[11.5px] font-medium text-[var(--accent)] hover:underline cursor-pointer"
            >
              Forgot password?
            </button>
          </div>
          <div className="relative">
            <input
              id="signin-password"
              type={showPassword ? 'text' : 'password'}
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={handleKeyDown}
              onKeyUp={handleKeyDown}
              disabled={isLoading}
              placeholder="••••••••••••"
              className="w-full h-11 pl-3.5 pr-11 rounded-[12px] bg-slate-50 dark:bg-slate-800/80 border border-slate-300 dark:border-slate-700 text-[13.5px] text-[var(--text-1)] placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/30 focus:border-[var(--accent)] transition-colors"
            />
            <button
              type="button"
              onClick={() => setShowPassword((prev) => !prev)}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              aria-pressed={showPassword}
              aria-controls="signin-password"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-[var(--text-1)] p-2 rounded-md transition-colors cursor-pointer"
            >
              <Icon name={showPassword ? 'eye-off' : 'eye'} size={16} />
            </button>
          </div>

          {/* Caps Lock Warning Banner */}
          {isCapsOn && (
            <p
              role="status"
              aria-live="polite"
              className="mt-1.5 text-[11px] text-amber-600 dark:text-amber-400 flex items-center gap-1"
            >
              <Icon name="alert-triangle" size={12} />
              <span>Caps Lock is ON</span>
            </p>
          )}
        </div>

        {/* Remember Me Checkbox */}
        <div className="flex items-center gap-2 pt-1">
          <input
            id="remember-me"
            type="checkbox"
            checked={rememberMe}
            onChange={(e) => setRememberMe(e.target.checked)}
            disabled={isLoading}
            className="w-4 h-4 rounded border-slate-300 dark:border-slate-700 text-[var(--accent)] focus:ring-[var(--accent)] cursor-pointer"
          />
          <label htmlFor="remember-me" className="text-[12.5px] text-[var(--text-2)] cursor-pointer">
            Remember this session on this computer (7 days)
          </label>
        </div>

        {/* Submit Button */}
        <button
          type="submit"
          disabled={isLoading}
          className="w-full h-11 mt-2 rounded-[12px] bg-[var(--accent)] hover:bg-[var(--accent-hover)] active:bg-[var(--accent-press)] text-white text-[13.5px] font-semibold flex items-center justify-center gap-2 transition-[background-color,transform,opacity] shadow-md active:scale-99 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
        >
          {isLoading ? (
            <>
              <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              <span>Authenticating...</span>
            </>
          ) : (
            <>
              <span>Sign In</span>
              <Icon name="chevron-right" size={14} />
            </>
          )}
        </button>

        {/* Switch to Sign Up */}
        <div className="pt-4 text-center border-t border-slate-200/80 dark:border-slate-800/80">
          <p className="text-[12.5px] text-[var(--text-2)]">
            Don&apos;t have an account?{' '}
            <button
              type="button"
              onClick={() => navigate(SIGN_UP_PATH)}
              className="font-semibold text-[var(--accent)] hover:underline cursor-pointer"
            >
              Create an account
            </button>
          </p>
        </div>
      </form>
    </AuthLayout>
  );
};