/**
 * SignUpPage.tsx — User Registration Screen.
 * Enforces email validation, password security, confirmation check, and duplicate account prevention.
 */
import React, { useState, useEffect } from 'react';
import { AuthLayout } from './AuthLayout';
import { APP_PATH, SIGN_IN_PATH, navigate } from '../landing/router';
import { signUp, useSession, getSession } from '../lib/auth-client';
import { Icon } from '../components/Icon';

export const SignUpPage: React.FC = () => {
  const { data: sessionData, isPending: sessionPending } = useSession();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // If already authenticated, redirect to /app immediately
  useEffect(() => {
    if (!sessionPending && sessionData?.session) {
      window.location.replace(APP_PATH);
    }
  }, [sessionData, sessionPending]);

  const validateInputs = (): string | null => {
    if (!name.trim()) return 'Please enter your full name.';
    if (!email.trim()) return 'Please enter your email address.';

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email.trim())) {
      return 'Please enter a valid email address format.';
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

      // Refresh in-memory session atom so ProtectedApp immediately recognises authenticated state
      await getSession().catch(() => {});

      // Registration created account and established session -> redirect to /app
      window.location.replace(APP_PATH);
    } catch (err: any) {
      setErrorMessage(err.message || 'A network error occurred. Please try again.');
      setIsLoading(false);
    }
  };

  return (
    <AuthLayout
      title="Create your account"
      subtitle="Start designing and analyzing plots with private multi-user project isolation."
    >
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        {/* Error notification */}
        {errorMessage && (
          <div
            role="alert"
            className="p-3 rounded-[12px] bg-[var(--semantic-red)]/10 border border-[var(--semantic-red)]/30 text-[var(--semantic-red-ink)] text-[12px] flex items-start gap-2"
          >
            <Icon name="alert-triangle" size={14} className="shrink-0 mt-0.5 text-[var(--semantic-red-ink)]" />
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
            placeholder="Sarah Jenkins"
            className="w-full h-10 px-3 rounded-[10px] bg-slate-50 dark:bg-slate-800/80 border border-slate-300 dark:border-slate-700 text-[13px] text-[var(--text-1)] placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40 focus:border-[var(--accent)] transition-colors"
          />
        </div>

        {/* Email Address */}
        <div>
          <label
            htmlFor="signup-email"
            className="block text-[12px] font-semibold text-[var(--text-1)] mb-1.5"
          >
            Email Address
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
            className="w-full h-10 px-3 rounded-[10px] bg-slate-50 dark:bg-slate-800/80 border border-slate-300 dark:border-slate-700 text-[13px] text-[var(--text-1)] placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40 focus:border-[var(--accent)] transition-colors"
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
              disabled={isLoading}
              placeholder="••••••••••••"
              className="w-full h-10 pl-3 pr-10 rounded-[10px] bg-slate-50 dark:bg-slate-800/80 border border-slate-300 dark:border-slate-700 text-[13px] text-[var(--text-1)] placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40 focus:border-[var(--accent)] transition-colors"
            />
            <button
              type="button"
              onClick={() => setShowPassword((prev) => !prev)}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-[var(--text-1)] p-1 rounded transition-colors"
            >
              <Icon name={showPassword ? 'eye-off' : 'eye'} size={15} />
            </button>
          </div>
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
            className="w-full h-10 px-3 rounded-[10px] bg-slate-50 dark:bg-slate-800/80 border border-slate-300 dark:border-slate-700 text-[13px] text-[var(--text-1)] placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40 focus:border-[var(--accent)] transition-colors"
          />
        </div>

        {/* Submit Button */}
        <button
          type="submit"
          disabled={isLoading}
          className="w-full h-11 mt-2 rounded-[12px] bg-[var(--accent)] hover:bg-[var(--accent-hover)] active:bg-[var(--accent-press)] text-white text-[13px] font-semibold flex items-center justify-center gap-2 transition-[background-color,transform,opacity] shadow-md active:scale-99 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
        >
          {isLoading ? (
            <>
              <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              <span>Creating Account...</span>
            </>
          ) : (
            <span>Create Account</span>
          )}
        </button>

        {/* Switch to Sign In */}
        <div className="pt-4 text-center border-t border-slate-200/80 dark:border-slate-800/80">
          <p className="text-[12px] text-[var(--text-2)]">
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
