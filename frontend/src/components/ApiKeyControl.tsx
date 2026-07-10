/**
 * Small header control for setting the API key the backend's
 * require_api_key dependency checks (see api/apiKey.ts and
 * api/dependencies.py on the backend). Collapsed by default so it doesn't
 * clutter the header when no auth is configured (the common case for
 * local development, where CLOUDOPS_API_KEY is unset and every request
 * succeeds with no key at all).
 */

import { useState, type FormEvent } from "react";
import { clearApiKey, getApiKey, setApiKey } from "../api/apiKey";

export function ApiKeyControl() {
  const [isOpen, setIsOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [hasKey, setHasKey] = useState(() => getApiKey() !== null);

  function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = draft.trim();
    if (!trimmed) return;
    setApiKey(trimmed);
    setHasKey(true);
    setDraft("");
    setIsOpen(false);
  }

  function handleClear() {
    clearApiKey();
    setHasKey(false);
  }

  return (
    <div className="api-key-control">
      <button
        type="button"
        className="link-button"
        onClick={() => setIsOpen((open) => !open)}
        title="Only needed if the backend has CLOUDOPS_API_KEY set"
      >
        {hasKey ? "API key: set" : "API key: not set"}
      </button>

      {isOpen && (
        <form className="api-key-control__form" onSubmit={handleSave}>
          <input
            type="password"
            placeholder="Paste CLOUDOPS_API_KEY"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            autoComplete="off"
          />
          <button type="submit">Save</button>
          {hasKey && (
            <button type="button" className="button--danger" onClick={handleClear}>
              Clear
            </button>
          )}
        </form>
      )}
    </div>
  );
}
