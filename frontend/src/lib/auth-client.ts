/**
 * auth-client.ts — Better Auth React client for BuildWise.
 * Handles client-side session management, authentication state hooks, and email OTP.
 */
import { createAuthClient } from 'better-auth/react';
import { emailOTPClient } from 'better-auth/client/plugins';

export const authClient = createAuthClient({
  plugins: [emailOTPClient()],
});

export const {
  signIn,
  signUp,
  signOut,
  useSession,
  getSession,
} = authClient;
