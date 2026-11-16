/**
 * VerifyEmailPage.tsx — Dedicated 6-Digit Email OTP Verification Screen.
 * Enforces server-side email ownership verification before granting access to the protected workspace.
 * Features auto-advancing segmented OTP inputs, clipboard paste support, resend countdown,
 * and seamless session establishment.
 */
import React, { useState, useEffect, useRef, useMemo } from 'react';
import { AuthLayout } from './AuthLayout';
import { APP_PATH, SIGN_IN_PATH, SIGN_UP_PATH, navigate } from '../landing/router';
import { authClient, getSession } from '../lib/auth-client';
import { Icon } from '../components/Icon';

export const VerifyEmailPage: React.FC = () => {
  // Read email from URL query param (?email=...) or fallback to active session
  const queryEmail = new URLSearchParams(window.location.search).get('email') || '';
  const [email, setEmail] = useState(queryEmail);
  const [isEditingEmail, setIsEditingEmail] = useState(!queryEmail);
  const [otp, setOtp] = useState<string[]>(['', '', '', '', '', '']);
  const [isLoading, setIsLoading] = useState(false);
  const [isResending, setIsResending] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [resendSuccess, setResendSuccess] = useState<string | null>(null);
  const [isVerified, setIsVerified] = useState(false);

  // Resend cooldown timer (60 seconds)
  const [resendCooldown, setResendCooldown] = useState(60);
  const [canResend, setCanResend] = useState(false);
  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);

  // Focus the first empty digit box on mount
  useEffect(() => {
    if (!isEditingEmail) {
      inputRefs.current[0]?.focus();
    }
  }, [isEditingEmail]);

  // Resend countdown timer interval
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

  // Safe email masking for privacy (e.g., a***e@b***e.ai)
  const maskedEmail = useMemo(() => {
    const clean = email.trim();
    if (!clean || !clean.includes('@')) return clean || 'your work email';
    try {
      const [user, domain] = clean.split('@');
      const maskedUser =
        user.length <= 2
          ? user[0] + '***'
          : user[0] + '***' + user[user.length - 1];
      if (domain.includes('.')) {
        const dParts = domain.split('.');
        const dName = dParts[0];
        const maskedDomain =
          (dName.length <= 2
            ? dName[0] + '***'
            : dName[0] + '***' + dName[dName.length - 1]) +
          '.' +
          dParts.slice(1).join('.');
        return `${maskedUser}@${maskedDomain}`;
      }
      return `${maskedUser}@***`;
    } catch {
      return clean;
    }
  }, [email]);

  const handleOtpChange = (index: number, value: string) => {
    const digit = value.replace(/\D/g, '').slice(-1);
    const newOtp = [...otp];
    newOtp[index] = digit;
    setOtp(newOtp);

    // Auto-advance to subsequent input box
    if (digit && index < 5) {
      inputRefs.current[index + 1]?.focus();
    }
  };

  const handleOtpKeyDown = (index: number, e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Backspace') {
      if (!otp[index] && index > 0) {
        inputRefs.current[index - 1]?.focus();
      }
    } else if (e.key === 'ArrowLeft' && index > 0) {
      e.preventDefault();
      inputRefs.current[index - 1]?.focus();
    } else if (e.key === 'ArrowRight' && index < 5) {
      e.preventDefault();
      inputRefs.current[index + 1]?.focus();
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

    const nextIdx = Math.min(pasted.length, 5);
    inputRefs.current[nextIdx]?.focus();
  };

  const handleResendOtp = async () => {
    if (!email.trim() || !canResend || isResending) return;
    setIsResending(true);
    setErrorMessage(null);
    setResendSuccess(null);

    try {
      const res = await authClient.emailOtp.sendVerificationOtp({
        email: email.trim().toLowerCase(),
        type: 'email-verification',
      });

      if (res?.error) {
        setErrorMessage(
          res.error.message || 'Unable to dispatch verification code. Please wait a moment and try again.'
        );
      } else {
        setResendSuccess('A fresh 6-digit verification code has been dispatched to your email.');
        setResendCooldown(60);
        setCanResend(false);
      }
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Failed to resend code. Please try again.';
      setErrorMessage(message);
    } finally {
      setIsResending(false);
    }
  };

  const fullOtp = otp.join('');
  const isComplete = fullOtp.length === 6;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) {
      setErrorMessage('Please provide your registered email address.');
      setIsEditingEmail(true);
      return;
    }

    if (!isComplete) {
      setErrorMessage('Please enter the complete 6-digit verification code.');
      return;
    }

    setIsLoading(true);
    setErrorMessage(null);
    setResendSuccess(null);

    try {
      const res = await authClient.emailOtp.verifyEmail({
        email: email.trim().toLowerCase(),
        otp: fullOtp,
      });

      if (res.error) {
        setErrorMessage(
          res.error.message || 'The verification code entered is invalid or has expired.'
        );
        setIsLoading(false);
        return;
      }

      setIsVerified(true);
      // Synchronize in-memory auth state immediately
      await getSession().catch(() => {});

      // Short delay for visual verification feedback before entering workspace
      setTimeout(() => {
        window.location.replace(APP_PATH);
      }, 700);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'An error occurred during verification. Please try again.';
      setErrorMessage(message);
      setIsLoading(false);
    }
  };

  return (
    <AuthLayout
      title="Verify your email"
      subtitle="Enter the 6-digit verification code sent to your registered work email to activate your account."
      badge="Account Verification"
    >
      <form onSubmit={handleSubmit} className="space-y-5" noValidate>
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

        {/* Resend Success notification */}
        {resendSuccess && (
          <div
            role="status"
            className="p-3.5 rounded-[12px] bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-900/60 text-emerald-700 dark:text-emerald-300 text-[12px] flex items-start gap-2.5 animate-in fade-in duration-150"
          >
            <Icon name="check" size={15} className="shrink-0 mt-0.5 text-emerald-600 dark:text-emerald-400" />
            <span className="flex-1 leading-relaxed font-medium">{resendSuccess}</span>
          </div>
        )}

        {/* Successful verification notification */}
        {isVerified && (
          <div
            role="status"
            className="p-3.5 rounded-[12px] bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-900/60 text-emerald-700 dark:text-emerald-300 text-[12px] flex items-center gap-2.5 animate-in fade-in duration-150"
          >
            <span className="w-4 h-4 border-2 border-emerald-600 border-t-transparent rounded-full animate-spin shrink-0" />
            <span className="flex-1 leading-relaxed font-medium">
              Email verified successfully! Establishing authenticated session...
            </span>
          </div>
        )}

        {/* Masked Email Banner with Change Email Option */}
        <div className="p-3.5 rounded-[12px] bg-slate-50 dark:bg-slate-800/60 border border-slate-200/80 dark:border-slate-700/60">
          <div className="flex items-center justify-between text-[11.5px] text-[var(--text-3)] mb-1">
            <span>Code sent to:</span>
            {!isEditingEmail && (
              <button
                type="button"
                onClick={() => setIsEditingEmail(true)}
                className="text-[var(--accent)] hover:underline font-medium cursor-pointer"
              >
                Change email
              </button>
            )}
          </div>
          {isEditingEmail ? (
            <div className="flex items-center gap-2 mt-1.5">
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@company.com"
                className="flex-1 h-9 px-3 rounded-[8px] bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 text-[13px] text-[var(--text-1)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/30"
              />
              <button
                type="button"
                onClick={() => setIsEditingEmail(false)}
                className="h-9 px-3 rounded-[8px] bg-slate-200 dark:bg-slate-700 text-[12px] font-semibold text-[var(--text-1)] hover:bg-slate-300 dark:hover:bg-slate-600 transition-colors cursor-pointer"
              >
                Done
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <span className="font-mono text-[13.5px] font-semibold text-[var(--text-1)] tracking-tight">
                {maskedEmail}
              </span>
              <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
            </div>
          )}
        </div>

        {/* 6-Digit Segmented OTP Input */}
        <div>
          <label className="block text-[12px] font-semibold text-[var(--text-1)] mb-2.5 text-center sm:text-left">
            Security Verification Code
          </label>
          <div className="flex justify-between items-center gap-1.5 sm:gap-2.5">
            {otp.map((digit, idx) => (
              <input
                key={idx}
                ref={(el) => {
                  inputRefs.current[idx] = el;
                }}
                type="text"
                inputMode="numeric"
                pattern="[0-9]*"
                maxLength={1}
                autoComplete="one-time-code"
                aria-label={`Verification code digit ${idx + 1}`}
                value={digit}
                disabled={isLoading || isVerified}
                onChange={(e) => handleOtpChange(idx, e.target.value)}
                onKeyDown={(e) => handleOtpKeyDown(idx, e)}
                onPaste={handleOtpPaste}
                className="w-11 h-13 sm:w-12 sm:h-14 text-center font-mono text-[20px] font-bold rounded-[12px] bg-slate-50 dark:bg-slate-800/80 border border-slate-300 dark:border-slate-700 text-[var(--text-1)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40 focus:border-[var(--accent)] transition-all shadow-2xs"
              />
            ))}
          </div>
          <p className="mt-2 text-[11px] text-[var(--text-3)] text-center sm:text-left flex items-center justify-between">
            <span>Single-use code valid for 5 minutes</span>
            <span className="font-mono">{fullOtp.length}/6 digits</span>
          </p>
        </div>

        {/* Submit Verification Button */}
        <button
          type="submit"
          disabled={!isComplete || isLoading || isVerified}
          className="w-full h-11 mt-2 rounded-[12px] bg-[var(--accent)] hover:bg-[var(--accent-hover)] active:bg-[var(--accent-press)] text-white text-[13.5px] font-semibold flex items-center justify-center gap-2 transition-[background-color,transform,opacity] shadow-md active:scale-99 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
        >
          {isLoading ? (
            <>
              <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              <span>Verifying Code...</span>
            </>
          ) : (
            <>
              <span>Verify & Continue</span>
              <Icon name="chevron-right" size={14} />
            </>
          )}
        </button>

        {/* Resend Code Section with Countdown Timer */}
        <div className="pt-2 text-center text-[12.5px] text-[var(--text-2)]">
          {canResend ? (
            <button
              type="button"
              disabled={isResending || isLoading}
              onClick={handleResendOtp}
              className="font-semibold text-[var(--accent)] hover:underline cursor-pointer disabled:opacity-50"
            >
              {isResending ? 'Transmitting code...' : 'Didn\'t receive code? Resend now'}
            </button>
          ) : (
            <p className="text-[var(--text-3)]">
              Resend verification code in{' '}
              <span className="font-mono font-semibold text-[var(--text-2)]">{resendCooldown}s</span>
            </p>
          )}
        </div>

        {/* Return to Sign Up / Sign In Links */}
        <div className="pt-4 text-center border-t border-slate-200/80 dark:border-slate-800/80 space-y-1.5">
          <p className="text-[12px] text-[var(--text-3)]">
            Wrong email address?{' '}
            <button
              type="button"
              onClick={() => navigate(SIGN_UP_PATH)}
              className="font-medium text-[var(--accent)] hover:underline cursor-pointer"
            >
              Register with a different address
            </button>
          </p>
          <p className="text-[12px] text-[var(--text-3)]">
            Already verified?{' '}
            <button
              type="button"
              onClick={() => navigate(SIGN_IN_PATH)}
              className="font-medium text-[var(--accent)] hover:underline cursor-pointer"
            >
              Return to sign in
            </button>
          </p>
        </div>
      </form>
    </AuthLayout>
  );
};
