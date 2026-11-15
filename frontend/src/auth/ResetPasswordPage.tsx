/**
 * ResetPasswordPage.tsx — Complete Password Reset with Brevo Email OTP Verification.
 * Verifies 6-digit OTP, updates password, and revokes active sessions.
 */
import React, { useState, useEffect } from 'react';
import { AuthLayout } from './AuthLayout';
import { SIGN_IN_PATH, navigate } from '../landing/router';
import { authClient } from '../lib/auth-client';
import { Icon } from '../components/Icon';

export const ResetPasswordPage: React.FC = () => {
  // Read email from URL query if available
  const initialEmail = new URLSearchParams(window.location.search).get('email') || '';
  const [email, setEmail] = useState(initialEmail);
  const [otp, setOtp] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Resend cooldown timer
  const [resendCooldown, setResendCooldown] = useState(60);
  const [canResend, setCanResend] = useState(false);
  const redirectTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  // Clean up redirect timer on unmount to prevent memory leaks
  useEffect(() => {
    return () => {
      if (redirectTimerRef.current) {
        clearTimeout(redirectTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (resendCooldown <= 0) {
      setCanResend(true);
      return;
    }
    const timer = setInterval(() => {
      setResendCooldown((prev) => prev - 1);
    }, 1000);
    return () => clearInterval(timer);
  }, [resendCooldown]);

  const handleResendOtp = async () => {
    if (!email.trim() || !canResend) return;
    setErrorMessage(null);
    try {
      await authClient.emailOtp.sendVerificationOtp({
        email: email.trim(),
        type: 'forget-password',
      });
      setResendCooldown(60);
      setCanResend(false);
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to resend code. Please wait before trying again.');
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) {
      setErrorMessage('Please provide your email address.');
      return;
    }
    if (!otp.trim() || otp.trim().length !== 6) {
      setErrorMessage('Please enter the complete 6-digit verification code.');
      return;
    }
    if (!newPassword || newPassword.length < 8) {
      setErrorMessage('New password must be at least 8 characters long.');
      return;
    }
    if (newPassword !== confirmPassword) {
      setErrorMessage('Passwords do not match. Please verify your confirmation password.');
      return;
    }

    setIsLoading(true);
    setErrorMessage(null);

    try {
      // Better Auth emailOtp resetPassword
      const res = await authClient.emailOtp.resetPassword({
        email: email.trim(),
        otp: otp.trim(),
        password: newPassword,
      });

      if (res.error) {
        setErrorMessage(
          res.error.message ||
            'The code entered is invalid or has expired. Please check your email or request a new code.'
        );
        setIsLoading(false);
        return;
      }

      setSuccessMessage('Your password has been successfully updated. Redirecting to sign in...');
      redirectTimerRef.current = setTimeout(() => {
        navigate(SIGN_IN_PATH);
      }, 2000);
    } catch (err: any) {
      setErrorMessage(err.message || 'Verification failed. Please check the code and try again.');
      setIsLoading(false);
    }
  };

  return (
    <AuthLayout
      title="Set new password"
      subtitle="Enter the 6-digit code delivered to your email and your new password."
    >
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        {/* Success notification */}
        {successMessage && (
          <div
            role="alert"
            className="p-3.5 rounded-[12px] bg-[var(--semantic-green)]/10 border border-[var(--semantic-green)]/30 text-[var(--semantic-green-ink)] text-[12px] flex items-start gap-2"
          >
            <Icon name="check" size={15} className="shrink-0 mt-0.5 text-[var(--semantic-green-ink)]" />
            <span className="flex-1 leading-relaxed font-semibold">{successMessage}</span>
          </div>
        )}

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

        {/* Email Address */}
        <div>
          <label
            htmlFor="reset-email"
            className="block text-[12px] font-semibold text-[var(--text-1)] mb-1.5"
          >
            Email Address
          </label>
          <input
            id="reset-email"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={isLoading || Boolean(initialEmail)}
            className="w-full h-10 px-3 rounded-[10px] bg-slate-50 dark:bg-slate-800/80 border border-slate-300 dark:border-slate-700 text-[13px] text-[var(--text-1)] placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40 focus:border-[var(--accent)] transition-colors disabled:opacity-75"
          />
        </div>

        {/* OTP Code */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label
              htmlFor="reset-otp"
              className="text-[12px] font-semibold text-[var(--text-1)]"
            >
              6-Digit One-Time Code
            </label>
            <button
              type="button"
              onClick={handleResendOtp}
              disabled={!canResend || isLoading}
              className="text-[11px] font-medium text-[var(--accent)] hover:underline disabled:opacity-50 disabled:no-underline cursor-pointer"
            >
              {canResend ? 'Resend code' : `Resend in ${resendCooldown}s`}
            </button>
          </div>
          <input
            id="reset-otp"
            type="text"
            required
            maxLength={6}
            pattern="\d{6}"
            value={otp}
            onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
            disabled={isLoading}
            placeholder="123456"
            className="w-full h-11 px-3 text-center tracking-[0.35em] font-mono text-[18px] font-bold rounded-[10px] bg-slate-50 dark:bg-slate-800/80 border border-slate-300 dark:border-slate-700 text-[var(--text-1)] placeholder-slate-300 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40 focus:border-[var(--accent)] transition-colors"
          />
        </div>

        {/* New Password */}
        <div>
          <label
            htmlFor="reset-new-password"
            className="block text-[12px] font-semibold text-[var(--text-1)] mb-1.5"
          >
            New Password (min 8 characters)
          </label>
          <div className="relative">
            <input
              id="reset-new-password"
              type={showPassword ? 'text' : 'password'}
              required
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
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

        {/* Confirm New Password */}
        <div>
          <label
            htmlFor="reset-confirm-password"
            className="block text-[12px] font-semibold text-[var(--text-1)] mb-1.5"
          >
            Confirm New Password
          </label>
          <input
            id="reset-confirm-password"
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
          disabled={isLoading || Boolean(successMessage)}
          className="w-full h-11 mt-2 rounded-[12px] bg-[var(--accent)] hover:bg-[var(--accent-hover)] active:bg-[var(--accent-press)] text-white text-[13px] font-semibold flex items-center justify-center gap-2 transition-[background-color,transform,opacity] shadow-md active:scale-99 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
        >
          {isLoading ? (
            <>
              <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              <span>Verifying & Resetting...</span>
            </>
          ) : (
            <span>Update Password</span>
          )}
        </button>

        {/* Back to sign in */}
        <div className="pt-4 text-center border-t border-slate-200/80 dark:border-slate-800/80">
          <button
            type="button"
            onClick={() => navigate(SIGN_IN_PATH)}
            className="text-[12px] font-medium text-[var(--text-2)] hover:text-[var(--text-1)] transition-colors cursor-pointer"
          >
            &larr; Return to sign in
          </button>
        </div>
      </form>
    </AuthLayout>
  );
};
