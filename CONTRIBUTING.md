# Contributing to CloudOps AI

Thanks for your interest in this project. It started as a solo portfolio build, so the workflow below reflects how it's actually developed today — if you're a real external contributor, open an issue first so we can align on scope before you invest time in a PR.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting the Project Running](#getting-the-project-running)
- [Project Layout](#project-layout)
- [Development Workflow](#development-workflow)
- [Backend Standards](#backend-standards)
- [Frontend Standards](#frontend-standards)
- [Infrastructure Changes](#infrastructure-changes)
- [Commit Message Convention](#commit-message-convention)
- [Pull Request Checklist](#pull-request-checklist)
- [Reporting Bugs](#reporting-bugs)

## Code of Conduct

Be respectful, be direct, and assume good intent. Disagreements about technical approach are fine and expected; personal attacks are not.

## Getting the Project Running

Full setup instructions live in the [root README](./README.md#getting-started) and [Local Development](./README.md#local-development) sections. In short:

```bash
# Backend
cd backend
uv sync --all-extras
uv run pytest --cov=src/cloudops_ai --cov-report=term-missing

# Frontend
cd frontend
npm install
npm run dev
```

Or bring up the full stack (backend + frontend + DynamoDB Local) with:

```bash
docker-compose up
```

## Project Layout

See [Folder Structure](./README.md#folder-structure) in the root README for the authoritative, up-to-date tree. Don't rely on any other planning document you might find in the repo's history — the README is the source of truth for what's actually built.

## Development Workflow

1. Open an issue describing the change before writing code, unless it's a trivial fix (typo, broken link, obviously dead code).
2. Branch off `main`.
3. Make your change, with tests. This repo runs at 99% backend statement coverage — new code should not lower that bar. Untested branches get flagged in review.
4. Run the full local check suite (below) before pushing.
5. Open a PR against `main`. CI (`backend-ci.yml`, `frontend-ci.yml`, and `terraform-plan.yml` if `infra/` changed) must pass.

There is no auto-merge and no direct-to-`main` push for anything beyond trivial docs fixes — everything goes through CI.

## Backend Standards

- **Python `>=3.12`**, managed with `uv`.
- **Lint:** `uv run ruff check .` — line length 110, `py312` target.
- **Types:** `uv run mypy .` — `strict = true`. No untyped defs, no implicit `Any` leaking across module boundaries.
- **Tests:** `uv run pytest --cov=src/cloudops_ai --cov-report=term-missing`. AWS calls in unit tests must go through the mock adapter (`adapters/mock/mock_aws_gateway.py`) or `moto` — never hit real AWS from a unit test.
- **Read/mutate separation:** any new AWS-touching tool must implement either `IReadOnlyAWSTools` or `IMutatingAWSTools`, not both. This split is deliberate (see [Security Model](./README.md#security-model)) — don't collapse it for convenience.
- **New remediation actions** must be added to the deterministic action allow-list (`domain/policies/remediation_policy.py`) and to `_ACTION_INVOKERS` in `remediation_executor.py`. An action that isn't in both places should be unreachable, by design.

## Frontend Standards

- **TypeScript `^5.5`**, React `^18.3`, Vite `^5.4`.
- Run `npm run lint` and `npm run build` (which runs `tsc`) before opening a PR.
- No new runtime dependencies without a reason in the PR description — this is a small dashboard, not a platform.

## Infrastructure Changes

- Any change under `infra/` triggers `terraform-plan.yml` on the PR — review the plan output in the CI logs before requesting review.
- Never hand-edit `CLOUDOPS_REMEDIATION_MODE` defaults for `dev`/`staging` away from `dry_run`. Live remediation is intentionally restricted to the `demo-live` environment — see [`infra/README.md`](./infra/README.md) for the reasoning.
- `terraform apply` only happens through the manually-triggered `deploy.yml` workflow, using a separate, more privileged OIDC role than the plan-only CI role. Don't try to widen the plan role's permissions to work around this.

## Commit Message Convention

This repo uses [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>: <short summary>

[optional body]
```

Common types used in this repo's history: `feat`, `fix`, `test`, `docs`, `refactor`, `chore`, `ci`. Check `git log` for real examples of the style before writing yours.

## Pull Request Checklist

- [ ] Tests added or updated for the change
- [ ] `ruff check` / `mypy` (backend) or `lint` / `build` (frontend) pass locally
- [ ] Coverage has not regressed
- [ ] Commit messages follow the convention above
- [ ] If `infra/` changed, the `terraform plan` output in CI has been reviewed
- [ ] Docs (README, this file, `docs/ARCHITECTURE.md`) updated if behavior or structure changed

## Reporting Bugs

Open a GitHub issue with: what you expected, what happened instead, and steps to reproduce (including whether you were running against the mock adapter, DynamoDB Local, or real AWS). For anything security-related, see [SECURITY.md](./SECURITY.md) instead of opening a public issue.
