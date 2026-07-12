# Architecture

This is a deeper technical dive than the root README. It walks through the backend module-by-module, the LangGraph agent graph, the tool/persistence layers, and the infrastructure topology — grounded in the actual source tree, not a planning document. If a claim here can't be traced to a real file path, it shouldn't be here.

## Table of Contents

- [Incident Lifecycle](#incident-lifecycle)
- [Backend Module Map](#backend-module-map)
- [The Agent Graph](#the-agent-graph)
- [Tool Layer and Read/Mutate Separation](#tool-layer-and-readmutate-separation)
- [Persistence Layer](#persistence-layer)
- [Remediation Safety: Policy, Approval, Execution](#remediation-safety-policy-approval-execution)
- [API Layer](#api-layer)
- [Infrastructure Topology](#infrastructure-topology)
- [CI/CD Pipeline](#cicd-pipeline)
- [Design Decisions](#design-decisions)
- [Deliberately Out of Scope](#deliberately-out-of-scope)

## Incident Lifecycle

1. A CloudWatch alarm or GuardDuty finding fires and is routed by an EventBridge rule to an SQS queue.
2. `services/sqs_incident_poller.py` — a background task started from `main.py`'s ASGI lifespan hook, running inside the same ECS Fargate task as the API — polls that queue and turns each message into an incident.
3. The incident enters the LangGraph state machine (`agents/graph.py`), starting at the coordinator node.
4. The coordinator either classifies deterministically (a known platform-health alarm shape) or defers to an LLM call to classify the incident type and severity.
5. Routing sends the incident to the relevant specialist agent(s) — monitoring, troubleshooting, security, cost, infrastructure, or deployment — which gather evidence using read-only tools.
6. If the specialist path concludes a remediation is warranted, a `RemediationPlan` is built against the deterministic policy allow-list and handed to `agents/remediation_executor.py`.
7. The executor checks `RemediationPlan.can_execute_live()`. In `dev`/`staging` (`CLOUDOPS_REMEDIATION_MODE=dry_run`) it simulates and records the result; only in `demo-live`, and only with a valid HMAC-signed approval token attached, does it call a real mutating AWS tool.
8. Incident and remediation state persist to DynamoDB (`repositories/dynamodb_incident_repository.py`), and the frontend polls the FastAPI `/incidents` and `/remediation` routers to display current state.

There is no separate trigger Lambda and no WebSocket push — ingestion is a poller inside the API process, and the dashboard reads via polling REST calls.

## Backend Module Map

| Path | Responsibility |
|---|---|
| `main.py` | FastAPI app factory; starts/stops the SQS poller via the ASGI lifespan hook. |
| `api/dependencies.py` | Dependency-injected FastAPI concerns — API-key auth, repository/service wiring. |
| `api/routers/incidents.py`, `api/routers/remediation.py` | HTTP surface. Thin — no business logic lives here. |
| `agents/graph.py` | Assembles the LangGraph `StateGraph`: nodes, conditional edges, entry point. |
| `agents/state.py` | The shared state schema threaded through every graph node. |
| `agents/coordinator.py` | Classification and routing — deterministic fast path plus LLM fallback. |
| `agents/monitoring_agent.py`, `troubleshooting_agent.py`, `security_agent.py`, `cost_agent.py`, `infrastructure_agent.py`, `deployment_agent.py` | Specialist nodes, one per incident domain, each read-only against AWS. |
| `agents/remediation_executor.py` | The only node that can call a mutating AWS tool, gated by policy + approval. |
| `domain/enums.py` | `IncidentType`, `Severity`, `RemediationStatus`, `TriggerSource`, and related enums. |
| `domain/models/incident.py`, `resource.py`, `remediation.py`, `evidence.py`, `report.py` | Pydantic domain models — the framework-free core. |
| `domain/policies/remediation_policy.py` | Static allow-list: which remediation actions are eligible per incident type/severity. |
| `tools/interfaces.py` | `IReadOnlyAWSTools` / `IMutatingAWSTools` protocols — the type-level security boundary. |
| `tools/readonly/boto3_aws_gateway.py` | Real, boto3-backed read-only AWS gateway. |
| `tools/mutating/boto3_mutating_gateway.py` | Real, boto3-backed mutating AWS gateway — the narrowest, most reviewed file in the repo. |
| `tools/dry_run/dry_run_adapter.py` | Wraps the mutating gateway so actions are logged/simulated instead of executed — the default binding outside `demo-live`. |
| `adapters/mock/mock_aws_gateway.py` | In-memory fake AWS backend used across unit tests and local dev, with no network calls at all. |
| `repositories/interfaces.py` | Repository protocol — persistence is swappable behind this. |
| `repositories/dynamodb_incident_repository.py` | Real persistence, backed by DynamoDB (or DynamoDB Local in dev). |
| `repositories/in_memory_incident_repository.py` | In-memory implementation for tests and lightweight local runs. |
| `services/approval_service.py` | Issues and validates HMAC-signed `ApprovalToken`s. |
| `services/sqs_incident_poller.py` | Background consumer turning SQS messages into incidents fed to the graph. |
| `core/config.py` | `pydantic-settings`-based configuration, reading `CLOUDOPS_*` environment variables. |
| `core/logging.py` | `structlog` configuration. |

## The Agent Graph

`agents/graph.py` builds a LangGraph `StateGraph` over the schema in `agents/state.py`. The coordinator node runs first: for a known platform-health alarm shape it classifies deterministically (no LLM round-trip, no ambiguity to introduce); everything else goes through an LLM classification call. Routing from the coordinator is conditional on the resulting incident type, fanning out to the specialist node(s) relevant to that domain. Each specialist only holds a reference to `IReadOnlyAWSTools` — it cannot mutate anything even if it wanted to, because the type it's given doesn't expose mutating methods. When a specialist path concludes remediation is warranted, control passes to `remediation_executor.py`, the single node in the entire graph wired to `IMutatingAWSTools`.

## Tool Layer and Read/Mutate Separation

`tools/interfaces.py` defines two `Protocol` classes: `IReadOnlyAWSTools` and `IMutatingAWSTools`. No concrete class implements both. Three concrete backends exist for the read/mutate pair:

- **Real AWS** (`tools/readonly/boto3_aws_gateway.py`, `tools/mutating/boto3_mutating_gateway.py`) — actual boto3 calls, used when `CLOUDOPS_USE_REAL_AWS=true`.
- **Dry-run** (`tools/dry_run/dry_run_adapter.py`) — wraps the mutating gateway so every call is logged and recorded as if it happened, without touching AWS. This is the default everywhere except `demo-live`.
- **Mock** (`adapters/mock/mock_aws_gateway.py`) — a fully in-memory fake, seeded per test, with no boto3 or network dependency at all. This is what the unit test suite runs against.

Because agent nodes are typed against the interface, not a concrete class, swapping between these three backends requires no change to any agent's code.

## Persistence Layer

`repositories/interfaces.py` defines the repository contract; `repositories/dynamodb_incident_repository.py` is the real implementation (DynamoDB or DynamoDB Local), and `repositories/in_memory_incident_repository.py` backs tests and quick local runs without a database. `list_all()`'s pagination loop (following `LastEvaluatedKey` across `scan` pages) is one of the few pieces of the DynamoDB repository that required a dedicated test using a mocked multi-page `scan` response, since no realistic local dataset spans multiple pages.

## Remediation Safety: Policy, Approval, Execution

Three independent layers have to agree before AWS is actually mutated:

1. **Policy** (`domain/policies/remediation_policy.py`) — a static table of which `RemediationAction`s are even eligible for a given incident type and severity. This is code, not a model decision, and is reviewable in a diff.
2. **Approval** (`services/approval_service.py`, `domain/models/remediation.py`) — `RemediationPlan.can_execute_live()` requires an `APPROVED` status *and* a valid, HMAC-signed `ApprovalToken` bound to that specific `plan_id`. Either missing returns `False`.
3. **Execution** (`agents/remediation_executor.py`) — a deterministic `_ACTION_INVOKERS` mapping from allow-listed actions to concrete tool calls. An action absent from this mapping raises rather than silently doing nothing.

All three checks are backed by dedicated tests, including the specific branch where a plan is `APPROVED` but has no token attached (unreachable in every other test's fixtures, since they all attach a token when marking a plan approved).

## API Layer

`main.py` builds the FastAPI app and, via the ASGI lifespan hook, starts and stops the SQS poller alongside the HTTP server — both run in the same process and the same ECS task. `api/dependencies.py` enforces `CLOUDOPS_API_KEY` on protected routes. `api/routers/incidents.py` and `api/routers/remediation.py` are intentionally thin: they call into services/repositories and shape HTTP responses, with no business logic of their own.

## Infrastructure Topology

Terraform is organized into 9 modules under `infra/modules/`: `networking` (custom VPC, private subnets, one NAT gateway per AZ), `ecs` (Fargate task + service), `alb` (public entry point for the API), `dynamodb`, `iam`, `eventbridge`, `monitoring` (CloudWatch alarms, dashboard, SNS), `ecr`, and `frontend` (S3 + CloudFront with an Origin Access Control, proxying the API through the same distribution to avoid mixed-content issues). Three environments — `dev`, `staging`, `demo-live` — each set `CLOUDOPS_REMEDIATION_MODE` as a hardcoded value in that environment's own `.tf` files rather than a shared, runtime-overridable variable, so going live requires deploying to the one environment built for it. See [`infra/README.md`](../infra/README.md) for the full module reference and the reasoning behind the three-environment split.

## CI/CD Pipeline

Four GitHub Actions workflows: `backend-ci.yml` (ruff, mypy --strict, pytest with coverage), `frontend-ci.yml` (eslint, tsc, vitest), `terraform-plan.yml` (runs `terraform plan` on PRs touching `infra/`, using a read-only OIDC role), and `deploy.yml` (`workflow_dispatch`-only — never runs on push — using a separate, more privileged OIDC role to apply Terraform, build/push images, and deploy). No workflow uses static AWS access keys.

## Design Decisions

- **Type-level protocol split over a runtime permission check.** A runtime check ("is this action allowed?") can have a bug. A type that simply doesn't expose a mutating method can't be bypassed by a bug in a specialist agent's logic — the compiler (or `mypy --strict`) catches the mismatch before the code runs.
- **In-process poller over a separate Lambda.** Simpler to develop, test, and deploy for a project this size — one process to run locally via `docker-compose`, one ECS task to reason about in production. The trade-off is coupling ingestion uptime to API uptime, which is acceptable at this scale.
- **Dry-run hardcoded per environment file, not a shared variable.** A shared variable can be flipped by mistake in a PR that touches an unrelated environment. A value hardcoded in `demo-live/`'s own files means changing it requires deliberately editing that environment.
- **CloudFront fronting both static assets and the API.** Serving the dashboard over HTTPS via CloudFront but calling an HTTP-only ALB directly would trigger mixed-content blocking in browsers. Proxying both through the same distribution avoids that without requiring a certificate on the ALB itself.

## Deliberately Out of Scope

Documented for the same reason as everything else in this repo — accuracy over aspiration:

- No JWT/OIDC user authentication (a single shared API key gates the backend).
- No WebSocket or Server-Sent-Events feed; the dashboard polls.
- No separate trigger Lambda; ingestion is in-process.
- No LangGraph checkpointer/persistence of intermediate graph state between runs.
- No custom domain or TLS certificate in front of CloudFront/the ALB yet.

See [Known Limitations](../README.md#known-limitations) and [Roadmap](../README.md#roadmap) in the root README for the current plan around these.
