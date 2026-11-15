/**
 * AccountModal.tsx — User Profile & Account Settings Dialog.
 * Displays user identity, verified badge, session controls, and secure sign-out.
 */
import React, { useEffect, useRef } from 'react';
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
  const [isSigningOut, setIsSigningOut] = React.useState(false);

  // Close on Escape key & manage focus
  useEffect(() => {
    if (!isOpen) return;
    modalRef.current?.focus();
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
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
    : 'BW';

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="User Account Settings"
      className="fixed inset-0 z-[1200] flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs select-none"
    >
      <div
        ref={modalRef}
        tabIndex={-1}
        className="w-full max-w-[420px] bg-white dark:bg-slate-900 rounded-[20px] border border-slate-200/90 dark:border-slate-800 shadow-2xl p-6 relative overflow-hidden animate-in fade-in zoom-in-95 duration-150 outline-none"
      >
        {/* Close Button */}
        <button
          type="button"
          onClick={onClose}
          aria-label="Close Account Dialog"
          className="absolute top-4 right-4 p-1.5 rounded-full text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer"
        >
          <Icon name="x" size={16} />
        </button>

        {/* Header / Avatar */}
        <div className="flex items-center gap-4 mb-6">
          <div className="w-14 h-14 rounded-full bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/30 flex items-center justify-center text-[18px] font-bold shrink-0">
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-[17px] font-bold text-[var(--text-1)] truncate">
              {isPending ? 'Loading...' : user?.name || 'Authenticated User'}
            </h2>
            <p className="text-[12px] text-[var(--text-2)] truncate">
              {isPending ? '...' : user?.email || 'No email detected'}
            </p>
            <div className="mt-1 flex items-center gap-1.5">
              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-[var(--semantic-green)]/15 text-[var(--semantic-green-ink)]">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--semantic-green)]" />
                Active Account
              </span>
            </div>
          </div>
        </div>

        {/* Account Details Box */}
        <div className="bg-slate-50 dark:bg-slate-800/60 rounded-[14px] p-4 border border-slate-200/80 dark:border-slate-700/60 space-y-3 mb-6">
          <div className="flex items-center justify-between text-[12px]">
            <span className="text-[var(--text-2)]">User Identifier</span>
            <span className="font-mono text-[11px] text-[var(--text-1)] bg-slate-200/60 dark:bg-slate-700/60 px-2 py-0.5 rounded">
              {user?.id ? `${user.id.slice(0, 10)}...` : '—'}
            </span>
          </div>

          <div className="flex items-center justify-between text-[12px]">
            <span className="text-[var(--text-2)]">Multi-User Isolation</span>
            <span className="font-medium text-[var(--semantic-green-ink)]">Private Tenant Active</span>
          </div>

          <div className="flex items-center justify-between text-[12px]">
            <span className="text-[var(--text-2)]">Session State</span>
            <span className="font-medium text-[var(--text-1)]">Persistent (7 Days)</span>
          </div>
        </div>

        {/* Actions */}
        <div className="space-y-2">
          <button
            type="button"
            onClick={handleSignOut}
            disabled={isSigningOut}
            className="w-full h-10 rounded-[12px] bg-[var(--semantic-red)]/10 hover:bg-[var(--semantic-red)]/20 active:bg-[var(--semantic-red)]/25 text-[var(--semantic-red-ink)] text-[13px] font-semibold flex items-center justify-center gap-2 transition-colors cursor-pointer disabled:opacity-50"
          >
            {isSigningOut ? (
              <>
                <span className="w-3.5 h-3.5 border-2 border-red-500/30 border-t-red-600 rounded-full animate-spin" />
                <span>Signing out...</span>
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
