/**
 * ForgotPasswordPage.tsx — Initiate Password Recovery via Brevo Email OTP.
 * Generates a 6-digit one-time code and transitions the user to the verification screen.
 */
import React, { useState } from 'react';
import { AuthLayout } from './AuthLayout';
import { RESET_PASSWORD_PATH, SIGN_IN_PATH, navigate } from '../landing/router';
import { authClient } from '../lib/auth-client';
import { Icon } from '../components/Icon';

export const ForgotPasswordPage: React.FC = () => {
  const [email, setEmail] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) {
      setErrorMessage('Please enter your registered work email address.');
      return;
    }

    setIsLoading(true);
    setErrorMessage(null);

    try {
      // Better Auth emailOtp forget-password trigger
      const res = await authClient.emailOtp.sendVerificationOtp({
        email: email.trim(),
        type: 'forget-password',
      });

      if (res.error) {
        setErrorMessage(
          res.error.message ||
            'Could not initiate password reset. Please verify your email address and try again.'
        );
        setIsLoading(false);
        return;
      }

      // Navigate to reset password page with email query param
      navigate(`${RESET_PASSWORD_PATH}?email=${encodeURIComponent(email.trim())}`);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'A network error occurred. Please try again.';
      setErrorMessage(message);
      setIsLoading(false);
    }
  };

  return (
    <AuthLayout
      title="Reset your password"
      subtitle="Enter your work email address to receive a secure 6-digit one-time verification code."
      badge="Account Recovery"
    >
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        {/* Visual 3-step Recovery Progress Bar */}
        <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-slate-800 text-[11px] font-medium text-[var(--text-3)]">
          <div className="flex items-center gap-1.5 text-[var(--accent)] font-semibold">
            <span className="w-5 h-5 rounded-full bg-blue-50 dark:bg-blue-950/70 border border-blue-200 dark:border-blue-900/80 text-[var(--accent)] flex items-center justify-center text-[10px]">
              1
            </span>
            <span>Request Code</span>
          </div>
          <span className="h-px w-6 bg-slate-200 dark:bg-slate-700" />
          <div className="flex items-center gap-1.5 opacity-60">
            <span className="w-5 h-5 rounded-full bg-slate-100 dark:bg-slate-800 text-[var(--text-3)] flex items-center justify-center text-[10px]">
              2
            </span>
            <span>Verify OTP</span>
          </div>
          <span className="h-px w-6 bg-slate-200 dark:bg-slate-700" />
          <div className="flex items-center gap-1.5 opacity-60">
            <span className="w-5 h-5 rounded-full bg-slate-100 dark:bg-slate-800 text-[var(--text-3)] flex items-center justify-center text-[10px]">
              3
            </span>
            <span>Set Password</span>
          </div>
        </div>

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

        {/* Email Field */}
        <div>
          <label
            htmlFor="forgot-email"
            className="block text-[12px] font-semibold text-[var(--text-1)] mb-1.5"
          >
            Registered Work Email
          </label>
          <input
            id="forgot-email"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={isLoading}
            placeholder="architect@buildwise.ai"
            className="w-full h-11 px-3.5 rounded-[12px] bg-slate-50 dark:bg-slate-800/80 border border-slate-300 dark:border-slate-700 text-[13.5px] text-[var(--text-1)] placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/30 focus:border-[var(--accent)] transition-colors"
          />
        </div>

        {/* Security notice */}
        <div className="p-3 rounded-[10px] bg-slate-50 dark:bg-slate-800/50 border border-slate-200/60 dark:border-slate-700/60 flex items-start gap-2.5 text-[11.5px] text-[var(--text-2)] leading-relaxed">
          <Icon name="info" size={14} className="shrink-0 mt-0.5 text-slate-400" />
          <span>
            Verification codes are valid for 10 minutes and automatically invalidate after 5 consecutive incorrect attempts for account security.
          </span>
        </div>

        {/* Action Button */}
        <button
          type="submit"
          disabled={isLoading}
          className="w-full h-11 mt-2 rounded-[12px] bg-[var(--accent)] hover:bg-[var(--accent-hover)] active:bg-[var(--accent-press)] text-white text-[13.5px] font-semibold flex items-center justify-center gap-2 transition-[background-color,transform,opacity] shadow-md active:scale-99 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
        >
          {isLoading ? (
            <>
              <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              <span>Transmitting Code...</span>
            </>
          ) : (
            <>
              <span>Send Verification Code</span>
              <Icon name="chevron-right" size={14} />
            </>
          )}
        </button>

        {/* Back to sign in */}
        <div className="pt-4 text-center border-t border-slate-200/80 dark:border-slate-800/80">
          <button
            type="button"
            onClick={() => navigate(SIGN_IN_PATH)}
            className="text-[12.5px] font-medium text-[var(--text-2)] hover:text-[var(--text-1)] transition-colors cursor-pointer"
          >
            &larr; Return to sign in
          </button>
        </div>
      </form>
    </AuthLayout>
  );
};