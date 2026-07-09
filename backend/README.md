# CloudOps AI — Backend

Agentic AI Cloud Engineer: a LangGraph multi-agent system, exposed over FastAPI,
that monitors AWS infrastructure, diagnoses incidents, and remediates them under
a human-gated approval workflow. See `/docs/ARCHITECTURE.md` at the repo root
for the full system design and rationale.

## Current state (build-in-progress)

- [x] **Domain layer** (`src/cloudops_ai/domain/`) — framework-free models and
      enums: `IncidentState`, `RemediationPlan`, `Evidence`, `AgentStep`,
      `IncidentReport`, `ResourceRef`, and the remediation policy allow-list.
- [x] **AWS tool interfaces + mock/dry-run adapters** (`tools/`, `adapters/mock/`)
- [ ] LangGraph skeleton (Coordinator + Monitoring agents)
- [ ] FastAPI shell + `/incidents` router
- [ ] DynamoDB repositories
- [ ] Remaining specialist agents
- [ ] Remaining incident types

## Getting started

This project uses [`uv`](https://docs.astral.sh/uv/) for dependency management.

```bash
uv sync --all-extras
uv run pytest
uv run ruff check .
uv run mypy src
```

## Design invariants worth knowing before you touch this code

1. `domain/` never imports `boto3`, `langgraph`, or `fastapi`.
2. Evidence and audit trail fields are append-only — always call
   `IncidentState.add_evidence(...)` / `.add_agent_step(...)`.
3. A `RemediationPlan` can only execute live with a verified `ApprovalToken` —
   see `RemediationPlan.can_execute_live()` and `tests/unit/domain/test_remediation.py`.
4. The remediation policy table fails closed — any `(incident_type, severity)`
   pair not explicitly listed is denied.
