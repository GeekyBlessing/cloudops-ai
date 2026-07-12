# CloudOps AI — Backend

FastAPI + LangGraph backend for CloudOps AI. For the full system overview, architecture diagrams, and AWS service reference, see the [root README](../README.md) and [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).

## Stack

- Python 3.12+, managed with [`uv`](https://github.com/astral-sh/uv)
- FastAPI, Pydantic v2, pydantic-settings
- LangGraph + LangChain for the multi-agent incident graph
- boto3 for AWS access, `moto` for mocked AWS in tests
- DynamoDB for persistence (DynamoDB Local in dev via docker-compose)
- `structlog` for logging

## Setup

```bash
cd backend
uv sync --all-extras
```

## Running locally

Bring up the full stack (backend + frontend + DynamoDB Local) from the repo root:

```bash
docker-compose up
```

Or run just the backend against DynamoDB Local / the mock adapter — see `.env.example` for the relevant `CLOUDOPS_*` variables (`CLOUDOPS_USE_DYNAMODB`, `CLOUDOPS_DYNAMODB_ENDPOINT_URL`, `CLOUDOPS_USE_REAL_AWS`, `CLOUDOPS_REMEDIATION_MODE`, etc.).

```bash
uv run uvicorn cloudops_ai.main:app --reload
```

## Testing

```bash
uv run pytest --cov=src/cloudops_ai --cov-report=term-missing
```

Backend statement coverage currently sits at 99% (1,221 statements, 3 remaining, both in files already at their practical testing ceiling). Unit tests never touch real AWS — they run against `adapters/mock/mock_aws_gateway.py` or `moto`.

## Linting and type-checking

```bash
uv run ruff check .
uv run mypy .
```

`mypy` runs in `strict` mode across the package.

## Structure

See [Folder Structure](../README.md#folder-structure) in the root README, and [Backend Module Map](../docs/ARCHITECTURE.md#backend-module-map) in the architecture doc for a directory-by-directory breakdown.

## Security-relevant conventions

- AWS-touching code is split into read-only and mutating tool interfaces (`tools/interfaces.py`) — see [Security Model](../README.md#security-model) and [SECURITY.md](../SECURITY.md).
- New remediation actions must be added to both the policy allow-list (`domain/policies/remediation_policy.py`) and the executor's action mapping (`agents/remediation_executor.py`), or they're unreachable by design.
