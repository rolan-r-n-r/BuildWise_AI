/**
 * AccountModal.tsx — User Profile & Tenant Settings Inspector.
 * Displays user identity, verified tenant badge, session security parameters,
 * and secure multi-user session sign-out with complete memory/cache teardown.
 */
import React, { useEffect, useRef, useState } from 'react';
import { signOut, useSession } from '../lib/auth-client';
import { SIGN_IN_PATH } from '../landing/router';
import { clearSessionDataStorage } from '../services/sessionReset';
import { Icon } from '../components/Icon';

interface AccountModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const AccountModal: React.FC<AccountModalProps> = ({ isOpen, onClose }) => {
  const { data: session, isPending } = useSession();
  const modalRef = useRef<HTMLDivElement>(null);
  const [isSigningOut, setIsSigningOut] = useState(false);
  const [copiedId, setCopiedId] = useState(false);

  // Close on Escape key & trap focus
  useEffect(() => {
    if (!isOpen) return;
    modalRef.current?.focus();
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
        return;
      }
      if (e.key === 'Tab' && modalRef.current) {
        const focusables = modalRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        );
        if (focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  // Lock body scroll while modal is active
  useEffect(() => {
    if (!isOpen) return;
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = originalOverflow;
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const handleCopyId = (id: string) => {
    if (!navigator.clipboard) return;
    navigator.clipboard
      .writeText(id)
      .then(() => {
        setCopiedId(true);
        setTimeout(() => setCopiedId(false), 2000);
      })
      .catch(() => {
        // clipboard permission denied or not supported in context
      });
  };

  const handleSignOut = async () => {
    setIsSigningOut(true);
    try {
      // Clear all cached feasibility study data and active session keys
      // to guarantee zero data bleed across accounts
      clearSessionDataStorage();
      await signOut();
      onClose();
      // Redirect to sign-in with full runtime and memory teardown
      window.location.replace(SIGN_IN_PATH);
    } catch (err) {
      console.error('Logout error:', err);
      setIsSigningOut(false);
    }
  };

  const user = session?.user;
  const initials = user?.name
    ? user.name
        .split(' ')
        .map((p) => p[0])
        .slice(0, 2)
        .join('')
        .toUpperCase()
    : (user?.email?.charAt(0).toUpperCase() || 'BW');

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="User Account Settings"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      className="fixed inset-0 z-[1200] flex items-center justify-center p-4 bg-slate-900/60 dark:bg-black/75 select-none"
    >
      <div
        ref={modalRef}
        tabIndex={-1}
        className="w-full max-w-[440px] bg-white dark:bg-slate-900 rounded-[20px] border border-slate-200/90 dark:border-slate-800 shadow-2xl p-6 relative overflow-hidden animate-in fade-in zoom-in-95 duration-150 outline-none"
      >
        {/* Close Button */}
        <button
          type="button"
          onClick={onClose}
          aria-label="Close Account Dialog"
          className="absolute top-4 right-4 w-8 h-8 rounded-full text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 flex items-center justify-center transition-colors cursor-pointer"
        >
          <Icon name="x" size={16} />
        </button>

        {/* User Identity Header */}
        <div className="flex items-center gap-4 mb-6">
          <div className="w-14 h-14 rounded-full bg-blue-50 dark:bg-blue-950/70 text-[var(--accent)] border border-blue-200 dark:border-blue-900/80 flex items-center justify-center text-[18px] font-bold shrink-0 shadow-xs">
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-[17px] font-bold text-[var(--text-1)] truncate">
              {isPending ? 'Loading profile...' : user?.name || 'Authenticated User'}
            </h2>
            <p className="text-[12px] text-[var(--text-2)] truncate">
              {isPending ? '...' : user?.email || 'No email detected'}
            </p>
            <div className="mt-1 flex items-center gap-1.5">
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-900/60">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                Verified Active Tenant
              </span>
            </div>
          </div>
        </div>

        {/* Account Details Box */}
        <div className="bg-slate-50 dark:bg-slate-800/60 rounded-[14px] p-4 border border-slate-200/80 dark:border-slate-700/60 space-y-3 mb-6">
          {/* User ID with Copy Action */}
          <div className="flex items-center justify-between text-[12px]">
            <span className="text-[var(--text-2)] font-medium">Tenant ID</span>
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-[11px] text-[var(--text-1)] bg-slate-200/60 dark:bg-slate-700/60 px-2 py-0.5 rounded">
                {user?.id ? `${user.id.slice(0, 10)}...` : '—'}
              </span>
              {user?.id && (
                <button
                  type="button"
                  onClick={() => handleCopyId(user.id)}
                  title="Copy full User ID"
                  aria-label="Copy full User ID"
                  className="p-1 rounded text-slate-400 hover:text-[var(--text-1)] hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
                >
                  <Icon name={copiedId ? 'check' : 'copy'} size={13} />
                </button>
              )}
            </div>
          </div>

          <div className="flex items-center justify-between text-[12px]">
            <span className="text-[var(--text-2)] font-medium">Multi-User Isolation</span>
            <span className="font-semibold text-emerald-600 dark:text-emerald-400">
              Private Tenant Active
            </span>
          </div>

          <div className="flex items-center justify-between text-[12px]">
            <span className="text-[var(--text-2)] font-medium">Cryptographic Standard</span>
            <span className="font-mono text-[11px] text-[var(--text-1)]">
              Argon2id + scrypt
            </span>
          </div>

          <div className="flex items-center justify-between text-[12px]">
            <span className="text-[var(--text-2)] font-medium">Session Longevity</span>
            <span className="font-medium text-[var(--text-1)]">7-Day Persistent Rolling TTL</span>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="space-y-2.5">
          <button
            type="button"
            onClick={handleSignOut}
            disabled={isSigningOut}
            className="w-full h-11 rounded-[12px] bg-red-50 hover:bg-red-100 active:bg-red-150 dark:bg-red-950/40 dark:hover:bg-red-900/60 text-red-600 dark:text-red-300 border border-red-200 dark:border-red-900/50 text-[13px] font-semibold flex items-center justify-center gap-2 transition-colors cursor-pointer disabled:opacity-50"
          >
            {isSigningOut ? (
              <>
                <span className="w-3.5 h-3.5 border-2 border-red-500/30 border-t-red-600 rounded-full animate-spin" />
                <span>Signing out and clearing session...</span>
              </>
            ) : (
              <>
                <Icon name="log-out" size={14} />
                <span>Sign Out of BuildWise</span>
              </>
            )}
          </button>

          <button
            type="button"
            onClick={onClose}
            className="w-full h-10 rounded-[12px] bg-slate-100 hover:bg-slate-200/80 dark:bg-slate-800 dark:hover:bg-slate-700 text-[var(--text-1)] text-[13px] font-medium transition-colors cursor-pointer"
          >
            Close Settings
          </button>
        </div>
      </div>
    </div>
  );
};