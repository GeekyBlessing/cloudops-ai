# CloudOps AI — Dashboard

React + TypeScript dashboard for CloudOps AI. For the full system overview, see the [root README](../README.md).

## Stack

- React 18.3, TypeScript 5.5, Vite 5.4
- React Router for navigation
- A small typed REST client (`src/api/client.ts`) — no state-management library; the two pages here don't need one

## Setup

```bash
cd frontend
npm install
npm run dev
```

## Authentication

The dashboard requires a `CLOUDOPS_API_KEY` to talk to the backend. Requests are gated through `src/api/apiKey.ts` / `src/components/ApiKeyControl`; without a valid key, requests fail and the UI surfaces the error state rather than silently showing empty data. This is intentionally simple — see [Known Limitations](../SECURITY.md#known-limitations) for what it doesn't cover (no per-user identity, no key rotation without a redeploy).

## Pages

- **Incident list** (`pages/IncidentListPage.tsx`) — all incidents with status, loading/error/empty states.
- **Incident detail** (`pages/IncidentDetailPage.tsx`) — a single incident's agent trace and evidence.

There are currently only these two pages. Anything beyond this (a resources view, cost dashboard, live agent feed, etc.) is aspirational and not yet built — see the [Roadmap](../README.md#roadmap) in the root README.

## Building

```bash
npm run build   # runs tsc, then vite build
npm run lint
```

## Running against the full stack

```bash
docker-compose up   # from the repo root — backend + frontend + DynamoDB Local
```
