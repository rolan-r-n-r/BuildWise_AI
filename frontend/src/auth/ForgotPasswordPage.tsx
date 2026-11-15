/**
 * ForgotPasswordPage.tsx — Initiate password reset via Brevo transactional email OTP.
 * Generates secure OTP and transitions user to the OTP verification screen.
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
      setErrorMessage('Please enter your email address.');
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
    } catch (err: any) {
      setErrorMessage(err.message || 'A network error occurred. Please try again.');
      setIsLoading(false);
    }
  };

  return (
    <AuthLayout
      title="Reset your password"
      subtitle="Enter your email address and we will deliver a 6-digit one-time code to your inbox."
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

        {/* Email Field */}
        <div>
          <label
            htmlFor="forgot-email"
            className="block text-[12px] font-semibold text-[var(--text-1)] mb-1.5"
          >
            Registered Email Address
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
            className="w-full h-10 px-3 rounded-[10px] bg-slate-50 dark:bg-slate-800/80 border border-slate-300 dark:border-slate-700 text-[13px] text-[var(--text-1)] placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40 focus:border-[var(--accent)] transition-colors"
          />
        </div>

        {/* Action Button */}
        <button
          type="submit"
          disabled={isLoading}
          className="w-full h-11 mt-2 rounded-[12px] bg-[var(--accent)] hover:bg-[var(--accent-hover)] active:bg-[var(--accent-press)] text-white text-[13px] font-semibold flex items-center justify-center gap-2 transition-[background-color,transform,opacity] shadow-md active:scale-99 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
        >
          {isLoading ? (
            <>
              <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              <span>Sending Code...</span>
            </>
          ) : (
            <span>Send Verification Code</span>
          )}
        </button>

        {/* Back to sign in */}
        <div className="pt-4 text-center border-t border-slate-200/80 dark:border-slate-800/80">
          <button
            type="button"
            onClick={() => navigate(SIGN_IN_PATH)}
            className="text-[12px] font-medium text-[var(--text-2)] hover:text-[var(--text-1)] transition-colors cursor-pointer"
          >
            &larr; Back to sign in
          </button>
        </div>
      </form>
    </AuthLayout>
  );
};
