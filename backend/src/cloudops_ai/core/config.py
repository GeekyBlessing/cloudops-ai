"""Application configuration.

A single Settings object, populated from environment variables (prefixed
CLOUDOPS_) and optionally a .env file for local development. This is the
one place secrets and mode flags are read from -- nothing else in the
codebase should call `os.environ` directly.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from cloudops_ai.domain.enums import RemediationMode


class Settings(BaseSettings):
    """Environment-driven configuration.

    `remediation_mode` defaults to DRY_RUN -- see /docs/ARCHITECTURE.md
    section 7. Flipping it to LIVE is meant to be a deliberate, reviewed
    action (e.g. only set in the `demo-live` Terraform environment's task
    definition), never a default anywhere else.
    """

    model_config = SettingsConfigDict(env_prefix="CLOUDOPS_", env_file=".env", extra="ignore")

    remediation_mode: RemediationMode = RemediationMode.DRY_RUN
    approval_secret_key: str = Field(
        default="dev-only-insecure-secret-change-me",
        description=(
            "HMAC key for ApprovalToken signing/verification. MUST be overridden via a real "
            "secret manager outside local development."
        ),
    )

    anthropic_api_key: str | None = None
    anthropic_model: str = Field(
        default="claude-sonnet-4-5",
        description=(
            "Verify against Anthropic's current model catalogue before deploying -- model "
            "slugs change over time and this default may drift."
        ),
    )
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"

    aws_region: str = "us-east-1"
    log_level: str = "INFO"

    use_dynamodb: bool = Field(
        default=False,
        description=(
            "False (default) uses the in-memory repository -- zero setup, data lost on "
            "restart. True switches to DynamoDBIncidentRepository; pair with "
            "dynamodb_endpoint_url pointing at DynamoDB Local for development, or leave "
            "endpoint_url unset in a real AWS environment."
        ),
    )
    dynamodb_endpoint_url: str | None = Field(
        default=None,
        description="e.g. http://localhost:8001 for DynamoDB Local. None means real AWS DynamoDB.",
    )
    dynamodb_table_incidents: str = "cloudops-ai-incidents"

    use_real_aws: bool = Field(
        default=False,
        description=(
            "False (default) uses the mock AWS gateway -- zero setup, zero AWS cost, zero "
            "blast radius. True switches to Boto3AWSGateway, which makes real read-only calls "
            "against the account the process's credentials resolve to. There is no equivalent "
            "flag for mutating calls -- see /docs/ARCHITECTURE.md section 7."
        ),
    )

    api_key: str | None = Field(
        default=None,
        description=(
            "Simple shared-secret API key for dashboard auth. None disables auth entirely -- "
            "acceptable for local dev only, never for a deployed environment."
        ),
    )

    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"],
        description=(
            "Origins allowed to call this API via CORS -- defaults to the Vite dev server's "
            "default port so `frontend/` works against a local backend with zero config. "
            "Override via CLOUDOPS_CORS_ORIGINS (a JSON array string, e.g. "
            '\'["https://dashboard.example.com"]\') in any deployed environment.'
        ),
    )


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton -- environment variables are read once per
    process, not re-parsed on every request.
    """
    return Settings()
