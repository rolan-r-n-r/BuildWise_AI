const rawApiUrl = (import.meta.env.VITE_API_URL as string | undefined) || 'http://localhost:8000';
const rawWakeupUrl = (import.meta.env.VITE_WAKEUP_URL as string | undefined) || '';

export const env = {
  VITE_API_URL: rawApiUrl.replace(/\/+$/, ''),
  VITE_WAKEUP_URL: rawWakeupUrl.replace(/\/+$/, ''),
};
