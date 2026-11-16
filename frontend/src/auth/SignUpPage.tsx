/**
 * SignUpPage.tsx — User Registration Screen with Live Security Checklist.
 * Integrates with Better Auth client signUp.email, enforcing client-side
 * password strength validation, real-time matching, and caps lock detection.
 */
import React, { useState, useEffect, useMemo } from 'react';
import { AuthLayout } from './AuthLayout';
import { APP_PATH, SIGN_IN_PATH, VERIFY_EMAIL_PATH, navigate } from '../landing/router';
import { signUp, useSession } from '../lib/auth-client';
import { Icon } from '../components/Icon';

export const SignUpPage: React.FC = () => {
  const { data: sessionData, isPending: sessionPending } = useSession();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isCapsOn, setIsCapsOn] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // If already authenticated and verified, redirect to /app; if unverified, redirect to /verify-email
  useEffect(() => {
    if (!sessionPending && sessionData?.session) {
      if (sessionData.user?.emailVerified) {
        window.location.replace(APP_PATH);
      } else if (sessionData.user?.email) {
        navigate(`${VERIFY_EMAIL_PATH}?email=${encodeURIComponent(sessionData.user.email)}`);
      }
    }
  }, [sessionData, sessionPending]);

  // Real-time password criteria evaluation
  const passwordCriteria = useMemo(() => {
    const hasMinLength = password.length >= 8;
    const hasUpper = /[A-Z]/.test(password);
    const hasLower = /[a-z]/.test(password);
    const hasMixedCase = hasUpper && hasLower;
    const hasNumberOrSymbol = /[\d!@#$%^&*(),.?":{}|<>]/.test(password);
    const isMatching = Boolean(password && confirmPassword && password === confirmPassword);

    let score = 0;
    if (hasMinLength) score++;
    if (hasMixedCase) score++;
    if (hasNumberOrSymbol) score++;
    if (password.length >= 12) score++;

    return {
      hasMinLength,
      hasMixedCase,
      hasNumberOrSymbol,
      isMatching,
      score, // 0 to 4
    };
  }, [password, confirmPassword]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.getModifierState && e.getModifierState('CapsLock')) {
      setIsCapsOn(true);
    } else {
      setIsCapsOn(false);
    }
  };

  const validateInputs = (): string | null => {
    if (!name.trim()) return 'Please enter your full name.';
    if (!email.trim()) return 'Please enter your work email address.';

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email.trim())) {
      return 'Please enter a valid work email address format.';
    }

    if (!password || password.length < 8) {
      return 'Password must be at least 8 characters long.';
    }

    if (password !== confirmPassword) {
      return 'Passwords do not match. Please verify your confirmation password.';
    }

    return null;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const validationError = validateInputs();
    if (validationError) {
      setErrorMessage(validationError);
      return;
    }

    setIsLoading(true);
    setErrorMessage(null);

    try {
      const res = await signUp.email({
        name: name.trim(),
        email: email.trim(),
        password,
      });

      if (res.error) {
        setErrorMessage(
          res.error.message ||
            'Registration could not be completed. An account with this email may already exist.'
        );
        setIsLoading(false);
        return;
      }

      // Registration successful and OTP dispatched -> navigate to dedicated verification screen
      navigate(`${VERIFY_EMAIL_PATH}?email=${encodeURIComponent(email.trim())}`);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'A network error occurred. Please try again.';
      setErrorMessage(message);
      setIsLoading(false);
    }
  };

  // Color bar styling based on password strength score
  const getStrengthBarColor = (index: number) => {
    if (index >= passwordCriteria.score) {
      return 'bg-slate-200 dark:bg-slate-700';
    }
    if (passwordCriteria.score === 1) return 'bg-red-500';
    if (passwordCriteria.score === 2) return 'bg-amber-500';
    if (passwordCriteria.score === 3) return 'bg-blue-500';
    return 'bg-emerald-500';
  };

  return (
    <AuthLayout
      title="Create your account"
      subtitle="Start designing and analyzing plots with private multi-user project isolation and zero paid API keys."
      badge="Get Started"
    >
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        {/* Error notification */}
        {errorMessage && (
          <div
            role="alert"
            className="p-3.5 rounded-[12px] bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900/60 text-red-700 dark:text-red-300 text-[12px] flex items-start gap-2.5 animate-in fade-in duration-150"
          >
            <Icon name="alert-triangle" size={15} className="shrink-0 mt-0.5 text-red-600 dark:text-red-400" />
            <span className="flex-1 leading-relaxed font-medium">{errorMessage}</span>
          </div>
        )}

        {/* Full Name */}
        <div>
          <label
            htmlFor="signup-name"
            className="block text-[12px] font-semibold text-[var(--text-1)] mb-1.5"
          >
            Full Name
          </label>
          <input
            id="signup-name"
            type="text"
            required
            autoComplete="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={isLoading}
            placeholder="Sarah Jenkins, Architect"
            className="w-full h-11 px-3.5 rounded-[10px] bg-slate-50 dark:bg-slate-800/80 border border-slate-300 dark:border-slate-700 text-[13.5px] text-[var(--text-1)] placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/30 focus:border-[var(--accent)] transition-colors"
          />
        </div>

        {/* Work Email Address */}
        <div>
          <label
            htmlFor="signup-email"
            className="block text-[12px] font-semibold text-[var(--text-1)] mb-1.5"
          >
            Work Email Address
          </label>
          <input
            id="signup-email"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={isLoading}
            placeholder="architect@buildwise.ai"
            className="w-full h-11 px-3.5 rounded-[10px] bg-slate-50 dark:bg-slate-800/80 border border-slate-300 dark:border-slate-700 text-[13.5px] text-[var(--text-1)] placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/30 focus:border-[var(--accent)] transition-colors"
          />
        </div>

        {/* Password */}
        <div>
          <label
            htmlFor="signup-password"
            className="block text-[12px] font-semibold text-[var(--text-1)] mb-1.5"
          >
            Password (min 8 characters)
          </label>
          <div className="relative">
            <input
              id="signup-password"
              type={showPassword ? 'text' : 'password'}
              required
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              onKeyDown={handleKeyDown}
              onKeyUp={handleKeyDown}
              disabled={isLoading}
              placeholder="••••••••••••"
              className="w-full h-11 pl-3.5 pr-11 rounded-[10px] bg-slate-50 dark:bg-slate-800/80 border border-slate-300 dark:border-slate-700 text-[13.5px] text-[var(--text-1)] placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/30 focus:border-[var(--accent)] transition-colors"
            />
            <button
              type="button"
              onClick={() => setShowPassword((prev) => !prev)}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              aria-pressed={showPassword}
              aria-controls="signup-password"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-[var(--text-1)] p-2 rounded-md transition-colors cursor-pointer"
            >
              <Icon name={showPassword ? 'eye-off' : 'eye'} size={16} />
            </button>
          </div>

          {/* Caps Lock Warning */}
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

          {/* Real-time Password Strength Meter */}
          {password.length > 0 && (
            <div className="mt-2 space-y-1.5">
              <div className="flex gap-1.5 h-1.5">
                {[0, 1, 2, 3].map((idx) => (
                  <div
                    key={idx}
                    className={`flex-1 rounded-full transition-colors duration-200 ${getStrengthBarColor(idx)}`}
                  />
                ))}
              </div>

              {/* Requirement Checklist Badges */}
              <div className="grid grid-cols-2 gap-1.5 pt-1 text-[11px]">
                <div className={`flex items-center gap-1.5 ${passwordCriteria.hasMinLength ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-400'}`}>
                  {passwordCriteria.hasMinLength ? (
                    <Icon name="check" size={11} strokeWidth={2.4} />
                  ) : (
                    <span className="w-1.5 h-1.5 rounded-full bg-slate-300 dark:bg-slate-600 inline-block" />
                  )}
                  <span>8+ characters</span>
                </div>
                <div className={`flex items-center gap-1.5 ${passwordCriteria.hasMixedCase ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-400'}`}>
                  {passwordCriteria.hasMixedCase ? (
                    <Icon name="check" size={11} strokeWidth={2.4} />
                  ) : (
                    <span className="w-1.5 h-1.5 rounded-full bg-slate-300 dark:bg-slate-600 inline-block" />
                  )}
                  <span>Upper & lowercase</span>
                </div>
                <div className={`flex items-center gap-1.5 ${passwordCriteria.hasNumberOrSymbol ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-400'}`}>
                  {passwordCriteria.hasNumberOrSymbol ? (
                    <Icon name="check" size={11} strokeWidth={2.4} />
                  ) : (
                    <span className="w-1.5 h-1.5 rounded-full bg-slate-300 dark:bg-slate-600 inline-block" />
                  )}
                  <span>Number or symbol</span>
                </div>
                <div className={`flex items-center gap-1.5 ${passwordCriteria.isMatching ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-400'}`}>
                  {passwordCriteria.isMatching ? (
                    <Icon name="check" size={11} strokeWidth={2.4} />
                  ) : (
                    <span className="w-1.5 h-1.5 rounded-full bg-slate-300 dark:bg-slate-600 inline-block" />
                  )}
                  <span>Passwords match</span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Confirm Password */}
        <div>
          <label
            htmlFor="signup-confirm-password"
            className="block text-[12px] font-semibold text-[var(--text-1)] mb-1.5"
          >
            Confirm Password
          </label>
          <input
            id="signup-confirm-password"
            type={showPassword ? 'text' : 'password'}
            required
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            disabled={isLoading}
            placeholder="••••••••••••"
            className="w-full h-11 px-3.5 rounded-[10px] bg-slate-50 dark:bg-slate-800/80 border border-slate-300 dark:border-slate-700 text-[13.5px] text-[var(--text-1)] placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/30 focus:border-[var(--accent)] transition-colors"
          />
        </div>

        {/* Terms notice */}
        <p className="text-[11.5px] text-[var(--text-3)] leading-relaxed pt-1">
          By signing up, you agree to BuildWise&apos;s{' '}
          <span className="text-[var(--text-2)] font-medium">Standard Terms of Service</span> and{' '}
          <span className="text-[var(--text-2)] font-medium">Privacy Policy</span>.
        </p>

        {/* Submit Button */}
        <button
          type="submit"
          disabled={isLoading}
          className="w-full h-11 mt-2 rounded-[12px] bg-[var(--accent)] hover:bg-[var(--accent-hover)] active:bg-[var(--accent-press)] text-white text-[13.5px] font-semibold flex items-center justify-center gap-2 transition-[background-color,transform,opacity] shadow-md active:scale-99 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
        >
          {isLoading ? (
            <>
              <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              <span>Creating Account...</span>
            </>
          ) : (
            <>
              <span>Create Account</span>
              <Icon name="chevron-right" size={14} />
            </>
          )}
        </button>

        {/* Switch to Sign In */}
        <div className="pt-4 text-center border-t border-slate-200/80 dark:border-slate-800/80">
          <p className="text-[12.5px] text-[var(--text-2)]">
            Already have an account?{' '}
            <button
              type="button"
              onClick={() => navigate(SIGN_IN_PATH)}
              className="font-semibold text-[var(--accent)] hover:underline cursor-pointer"
            >
              Sign in
            </button>
          </p>
        </div>
      </form>
    </AuthLayout>
  );
};