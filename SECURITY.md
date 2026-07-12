# Security Policy

CloudOps AI is a portfolio project, not a production service handling real customer data or real AWS accounts by default. Even so, it's built the way a production remediation system should be: every path that can mutate infrastructure is deliberately narrow, typed, and fails closed. This document describes that model and how to report a concern.

## Table of Contents

- [Reporting a Vulnerability](#reporting-a-vulnerability)
- [Security Model](#security-model)
- [Scope](#scope)
- [Known Limitations](#known-limitations)

## Reporting a Vulnerability

Please do **not** open a public GitHub issue for a security concern. Instead, email **toriolabarakat@gmail.com** with:

- A description of the issue and its potential impact.
- Steps to reproduce, if applicable.
- Which component is affected (backend, frontend, or Terraform/infra).

This is a single-maintainer project, so there's no formal SLA, but reports will be acknowledged and triaged as soon as possible.

## Security Model

### Type-level read/mutate separation

AWS-touching code is split at the interface level into `IReadOnlyAWSTools` and `IMutatingAWSTools` (`backend/src/cloudops_ai/tools/interfaces.py`). No single class implements both. This means a node in the LangGraph agent graph that only needs to *look at* AWS (monitoring, troubleshooting, cost, security investigation) is physically incapable of calling a mutating method — the type doesn't expose one — regardless of what an LLM decides to do.

### A single, narrow mutation surface

All actual AWS mutations funnel through one place: `remediation_executor.py`, via a deterministic `_ACTION_INVOKERS` mapping from allow-listed `RemediationAction` values to concrete tool calls. There is no general-purpose "run arbitrary AWS call" path anywhere in the codebase. If an action isn't in the mapping, it isn't executable — it raises rather than silently no-op'ing.

### Deterministic policy allow-list, not LLM discretion

Which remediation actions are even eligible for a given incident type and severity is defined in `domain/policies/remediation_policy.py` — a static table, not a model decision. The LLM-driven agents can *propose* a plan, but the set of actions they can choose from is fixed in code and reviewable in a diff.

### Fail-closed approval gate

`RemediationPlan.can_execute_live()` requires both an `APPROVED` status *and* a valid `ApprovalToken` attached to the plan. Missing either one returns `False` — there is no code path where an unapproved or partially-approved plan can execute. Approval tokens are HMAC-signed (`hmac.compare_digest`, not `==`, to avoid timing attacks) and bound to the specific `plan_id` they approve, so a token can't be replayed against a different plan.

### Dry-run by default, live only where explicitly configured

`CLOUDOPS_REMEDIATION_MODE` is hardcoded per Terraform environment file, not exposed as a runtime-overridable shared variable. It is `dry_run` in `dev` and `staging`, and only `live` in `demo-live`. Getting a remediation to actually touch AWS requires deploying to the one environment built for that, not flipping a flag.

### No long-lived cloud credentials in CI

GitHub Actions authenticates to AWS via OIDC, using two distinct IAM roles: a read-only plan role for the PR-triggered `terraform-plan.yml`, and a broader, manually-triggered deploy role for `deploy.yml` (`workflow_dispatch` only — never runs automatically on push). There are no static AWS access keys stored as GitHub secrets.

### API authentication

The backend API is protected by a shared `CLOUDOPS_API_KEY`, checked via a FastAPI dependency (`api/dependencies.py`). This is intentionally simple — see [Known Limitations](#known-limitations) below for what it doesn't cover.

## Scope

This policy covers:

- `backend/` — the FastAPI application, LangGraph agents, and AWS tool adapters.
- `frontend/` — the React dashboard.
- `infra/` — the Terraform configuration and GitHub Actions workflows.

## Known Limitations

Documented here in the same spirit as the rest of this repo's docs — no invented guarantees:

- **API-key auth, not OAuth/JWT.** A single shared key authenticates all requests; there's no per-user identity, and the key isn't scoped or rotatable without a redeploy.
- **No TLS/custom domain yet.** The CloudFront distribution and ALB are not currently fronted by a custom domain with an ACM certificate — see the [Roadmap](./README.md#roadmap) in the root README.
- **Single-region.** No cross-region failover or multi-region data residency.
- **`demo-live` is still a demo.** Its IAM role scope should be reviewed before pointing it at anything beyond disposable AWS resources.
