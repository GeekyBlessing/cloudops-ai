# CloudOps AI -- Dashboard

React + TypeScript frontend for CloudOps AI. Talks to the FastAPI backend
in `../backend` over plain `fetch` calls -- see `src/api/client.ts` for the
full list of endpoints it uses.

## Setup

```bash
npm install
cp .env.example .env.local   # adjust VITE_API_BASE_URL if needed
npm run dev
```

Opens on http://localhost:5173. Make sure the backend is running first
(`uv run uvicorn cloudops_ai.main:app --reload` from `../backend`) --
without it, the incident list will show a fetch error, which is expected
and not a frontend bug.

## Scripts

- `npm run dev` -- Vite dev server with hot reload
- `npm run typecheck` -- `tsc --noEmit`, no build output
- `npm run build` -- type-checks then produces a production build in `dist/`
- `npm run preview` -- serves the production build locally

## Structure

- `src/types/domain.ts` -- hand-kept-in-sync mirror of the backend's Pydantic models
- `src/api/client.ts` -- the only file that knows the backend's URL/shapes
- `src/components/` -- small, reusable presentational pieces (StatusBadge, EvidenceList, AgentTraceList)
- `src/pages/` -- route-level components (IncidentListPage, IncidentDetailPage)

## Known limitations (by design, for this build stage)

- No auth -- `CLOUDOPS_API_KEY` exists on the backend but isn't wired into
  any request here yet.
- No polling/websockets -- the detail page only refreshes on load or when
  you click Refresh/Approve/Reject.
- `IncidentReport` is typed but always `null` today -- report generation
  isn't implemented in the backend yet.
