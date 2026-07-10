/**
 * Storage for the shared-secret API key the backend's require_api_key
 * dependency checks (backend/src/cloudops_ai/api/dependencies.py).
 *
 * Persisted to localStorage, not just in-memory React state, so the user
 * doesn't have to re-enter it on every page reload -- this is a
 * shared-secret convenience key for a small internal tool, not a session
 * token with real expiry semantics, so there's no meaningful security
 * downside to persisting it client-side that isn't already true of typing
 * it into this app at all.
 */

const STORAGE_KEY = "cloudops_ai_api_key";

export function getApiKey(): string | null {
  return window.localStorage.getItem(STORAGE_KEY);
}

export function setApiKey(key: string): void {
  window.localStorage.setItem(STORAGE_KEY, key);
}

export function clearApiKey(): void {
  window.localStorage.removeItem(STORAGE_KEY);
}
