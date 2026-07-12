# Changelog

All notable changes to this project are documented in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project does not yet use tagged releases, so changes not part of a version bump are listed under **Unreleased**.

## [Unreleased]

### Added

- Root `README.md` with architecture and AI-agent-workflow diagrams (Mermaid), AWS services reference, security model, and full setup instructions.
- `LICENSE` (MIT).
- `CONTRIBUTING.md` covering the real dev workflow, coding standards, and commit convention.

These are documentation additions only; no application behavior changed.

## [0.1.0] - 2026-07-11

Initial working version of the system: LangGraph multi-agent backend, FastAPI, a React dashboard, Terraform-managed infrastructure across three environments, and GitHub Actions CI/CD, with backend test coverage brought to 99%.

### Added

- Core domain models (`IncidentState`, `RemediationPlan`, `ApprovalToken`, evidence/audit trail) and the LangGraph agent graph — coordinator, specialist agents, and the remediation executor.
- EventBridge → SQS → in-process poller pipeline for incident ingestion (no separate trigger Lambda).
- Mock AWS adapter and a real boto3-backed gateway, split into read-only and mutating tool interfaces.
- DynamoDB-backed incident repository, FastAPI routers for incidents and remediation, and API-key authentication.
- React dashboard (incident list and detail pages) with API-key-gated requests and loading/error/empty states.
- Terraform modules: `networking` (custom VPC), `ecs` + `alb`, `dynamodb`, `iam`, `eventbridge`, `monitoring` (CloudWatch alarms, dashboard, SNS), `ecr`, and `frontend` (S3 + CloudFront).
- Three Terraform environments — `dev`, `staging`, `demo-live` — with `CLOUDOPS_REMEDIATION_MODE` hardcoded per environment (`dry_run` everywhere except `demo-live`).
- GitHub Actions workflows: `backend-ci.yml`, `frontend-ci.yml`, `terraform-plan.yml` (all PR-triggered), and `deploy.yml` (`workflow_dispatch`-only, using two distinct OIDC IAM roles for plan vs. apply).

### Changed

- Introduced a deterministic classification path for platform-health alarms, bypassing the LLM for a known, unambiguous alarm class.
- Moved the ECS task into private subnets behind an Application Load Balancer.
- Switched from a single shared NAT gateway to one NAT gateway per availability zone.
- Dashboard hosting moved to S3 + CloudFront, with the API proxied through the same distribution to avoid mixed-content issues.

### Testing

- Closed backend statement coverage from its initial state up to **99%** (1,221 statements, 3 remaining), including full coverage of `api/dependencies.py`, the `main.py` ASGI lifespan hook, `boto3_aws_gateway.py`, `dry_run_adapter.py`, `sqs_incident_poller.py`, `remediation_executor.py`, `mock_aws_gateway.py`, `monitoring_agent.py`, `dynamodb_incident_repository.py`, `coordinator.py`, and `domain/models/remediation.py`.
