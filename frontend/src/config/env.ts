export const env = {
  get VITE_API_URL(): string {
    if (import.meta.env.VITE_API_URL) {
      return import.meta.env.VITE_API_URL;
    }
    if (typeof window !== 'undefined' && window.location.hostname.endsWith('.vercel.app')) {
      return 'https://buildwise-ai-gbva.onrender.com';
    }
    return 'http://localhost:8000';
  },
};
