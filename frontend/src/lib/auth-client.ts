/**
 * auth-client.ts — Better Auth React client for BuildWise.
 * Handles client-side session management, authentication state hooks, and email OTP.
 */
import { createAuthClient } from 'better-auth/react';
import { emailOTPClient } from 'better-auth/client/plugins';
import { API_BASE_URL } from '../services/api';

export const authClient = createAuthClient({
  baseURL: API_BASE_URL,
  plugins: [emailOTPClient()],
});

export const {
  signIn,
  signUp,
  signOut,
  useSession,
  getSession,
} = authClient;
