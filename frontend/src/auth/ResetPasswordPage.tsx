/**
 * ResetPasswordPage.tsx — Complete Password Reset with 6-Digit Segmented OTP.
 * Verifies 6-digit OTP code, sets the new password, and revokes prior active sessions.
 */
import React, { useState, useEffect, useRef } from 'react';
import { AuthLayout } from './AuthLayout';
import { SIGN_IN_PATH, navigate } from '../landing/router';
import { authClient } from '../lib/auth-client';
import { Icon } from '../components/Icon';

export const ResetPasswordPage: React.FC = () => {
  // Read email from URL query if available
  const initialEmail = new URLSearchParams(window.location.search).get('email') || '';
  const [email, setEmail] = useState(initialEmail);
  const [otp, setOtp] = useState(['', '', '', '', '', '']);
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Resend cooldown timer
  const [resendCooldown, setResendCooldown] = useState(60);
  const [canResend, setCanResend] = useState(false);
  const redirectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);

  // Clean up redirect timer on unmount
  useEffect(() => {
    return () => {
      if (redirectTimerRef.current) {
        clearTimeout(redirectTimerRef.current);
      }
    };
  }, []);

  // Countdown timer effect
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

  // Handle segmented OTP input changes
  const handleOtpChange = (index: number, value: string) => {
    const digit = value.replace(/\D/g, '').slice(-1);
    const newOtp = [...otp];
    newOtp[index] = digit;
    setOtp(newOtp);

    // Auto-advance to next box if digit entered
    if (digit && index < 5) {
      inputRefs.current[index + 1]?.focus();
    }
  };

  const handleOtpKeyDown = (index: number, e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Backspace' && !otp[index] && index > 0) {
      inputRefs.current[index - 1]?.focus();
    }
  };

  const handleOtpPaste = (e: React.ClipboardEvent<HTMLInputElement>) => {
    e.preventDefault();
    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6);
    if (!pasted) return;

    const newOtp = [...otp];
    for (let i = 0; i < 6; i++) {
      newOtp[i] = pasted[i] || '';
    }
    setOtp(newOtp);

    const nextIndex = Math.min(pasted.length, 5);
    inputRefs.current[nextIndex]?.focus();
  };

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
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Failed to resend code. Please wait before trying again.';
      setErrorMessage(message);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const fullOtp = otp.join('');

    if (!email.trim()) {
      setErrorMessage('Please provide your registered work email address.');
      return;
    }
    if (fullOtp.length !== 6) {
      setErrorMessage('Please enter the complete 6-digit one-time verification code.');
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
        otp: fullOtp,
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
    } catch (err: unknown) {
      const message =
        err instanceof Error
          ? err.message
          : 'Verification failed. Please check the code and try again.';
      setErrorMessage(message);
      setIsLoading(false);
    }
  };

  const passwordsMatch = Boolean(newPassword && confirmPassword && newPassword === confirmPassword);

  return (
    <AuthLayout
      title="Set new password"
      subtitle="Enter the 6-digit one-time code delivered to your email and choose your new password."
      badge="Verification & Reset"
    >
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        {/* Visual 3-step Recovery Progress Bar */}
        <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-slate-800 text-[11px] font-medium text-[var(--text-3)]">
          <div className="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400 font-semibold">
            <span className="w-5 h-5 rounded-full bg-emerald-50 dark:bg-emerald-950/70 border border-emerald-200 dark:border-emerald-900/80 flex items-center justify-center text-[10px]">
              <Icon name="check" size={10} className="text-emerald-600 dark:text-emerald-400" />
            </span>
            <span>Request</span>
          </div>
          <span className="h-px w-6 bg-emerald-500" />
          <div className="flex items-center gap-1.5 text-[var(--accent)] font-semibold">
            <span className="w-5 h-5 rounded-full bg-blue-50 dark:bg-blue-950/70 border border-blue-200 dark:border-blue-900/80 flex items-center justify-center text-[10px]">
              2
            </span>
            <span>Verify OTP</span>
          </div>
          <span className="h-px w-6 bg-slate-200 dark:bg-slate-700" />
          <div className="flex items-center gap-1.5 text-[var(--accent)] font-semibold">
            <span className="w-5 h-5 rounded-full bg-blue-50 dark:bg-blue-950/70 border border-blue-200 dark:border-blue-900/80 flex items-center justify-center text-[10px]">
              3
            </span>
            <span>Set Password</span>
          </div>
        </div>

        {/* Success notification */}
        {successMessage && (
          <div
            role="alert"
            className="p-3.5 rounded-[12px] bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-900/60 text-emerald-700 dark:text-emerald-300 text-[12px] flex items-start gap-2.5 animate-in fade-in duration-150"
          >
            <Icon name="check" size={15} className="shrink-0 mt-0.5 text-emerald-600 dark:text-emerald-400" />
            <span className="flex-1 leading-relaxed font-semibold">{successMessage}</span>
          </div>
        )}

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
            className="w-full h-11 px-3.5 rounded-[10px] bg-slate-50 dark:bg-slate-800/80 border border-slate-300 dark:border-slate-700 text-[13.5px] text-[var(--text-1)] placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/30 focus:border-[var(--accent)] transition-colors disabled:opacity-75"
          />
        </div>

        {/* Segmented 6-Box OTP Code */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label
              htmlFor="otp-box-0"
              className="text-[12px] font-semibold text-[var(--text-1)]"
            >
              6-Digit One-Time Code
            </label>
            <button
              type="button"
              onClick={handleResendOtp}
              disabled={!canResend || isLoading}
              className="text-[11.5px] font-medium text-[var(--accent)] hover:underline disabled:opacity-50 disabled:no-underline cursor-pointer"
            >
              {canResend ? 'Resend code now' : `Resend in ${resendCooldown}s`}
            </button>
          </div>

          <div className="flex items-center justify-between gap-1.5 xs:gap-2">
            {[0, 1, 2, 3, 4, 5].map((index) => (
              <input
                key={index}
                id={`otp-box-${index}`}
                ref={(el) => {
                  inputRefs.current[index] = el;
                }}
                type="text"
                inputMode="numeric"
                maxLength={1}
                pattern="\d*"
                value={otp[index]}
                onChange={(e) => handleOtpChange(index, e.target.value)}
                onKeyDown={(e) => handleOtpKeyDown(index, e)}
                onPaste={handleOtpPaste}
                disabled={isLoading}
                aria-label={`Digit ${index + 1} of 6`}
                className="flex-1 min-w-0 max-w-[48px] h-11 xs:h-12 text-center font-mono text-[18px] xs:text-[20px] font-bold rounded-[10px] bg-slate-50 dark:bg-slate-800/80 border border-slate-300 dark:border-slate-700 text-[var(--text-1)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40 focus:border-[var(--accent)] transition-colors shadow-xs"
              />
            ))}
          </div>
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
              className="w-full h-11 pl-3.5 pr-11 rounded-[10px] bg-slate-50 dark:bg-slate-800/80 border border-slate-300 dark:border-slate-700 text-[13.5px] text-[var(--text-1)] placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/30 focus:border-[var(--accent)] transition-colors"
            />
            <button
              type="button"
              onClick={() => setShowPassword((prev) => !prev)}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              aria-pressed={showPassword}
              aria-controls="reset-new-password"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-[var(--text-1)] p-2 rounded-md transition-colors cursor-pointer"
            >
              <Icon name={showPassword ? 'eye-off' : 'eye'} size={16} />
            </button>
          </div>
        </div>

        {/* Confirm New Password */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label
              htmlFor="reset-confirm-password"
              className="text-[12px] font-semibold text-[var(--text-1)]"
            >
              Confirm New Password
            </label>
            {confirmPassword && (
              <span
                className={`text-[11px] font-medium flex items-center gap-1 ${
                  passwordsMatch ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-500'
                }`}
              >
                <Icon name={passwordsMatch ? 'check' : 'x'} size={12} />
                <span>{passwordsMatch ? 'Passwords match' : 'Do not match'}</span>
              </span>
            )}
          </div>
          <input
            id="reset-confirm-password"
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

        {/* Submit Button */}
        <button
          type="submit"
          disabled={isLoading || Boolean(successMessage)}
          className="w-full h-11 mt-2 rounded-[12px] bg-[var(--accent)] hover:bg-[var(--accent-hover)] active:bg-[var(--accent-press)] text-white text-[13.5px] font-semibold flex items-center justify-center gap-2 transition-[background-color,transform,opacity] shadow-md active:scale-99 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
        >
          {isLoading ? (
            <>
              <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              <span>Verifying & Resetting...</span>
            </>
          ) : (
            <>
              <span>Update Password</span>
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