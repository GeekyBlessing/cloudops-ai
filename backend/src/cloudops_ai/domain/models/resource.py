"""AWS resource inventory model, populated by the Infrastructure Agent."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ResourceRef(BaseModel):
    """A reference to a single AWS resource, plus enough metadata for agents
    to reason about it without re-fetching from AWS every time."""

    arn: str = Field(description="AWS ARN -- the natural primary key for any AWS resource")
    resource_type: str = Field(
        description="e.g. 'AWS::EC2::Instance', 'AWS::S3::Bucket' (CloudFormation-style type string)"
    )
    region: str
    account_id: str
    name: str | None = Field(default=None, description="Human-friendly name/tag, if any")
    tags: dict[str, str] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)
    last_synced_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("arn")
    @classmethod
    def _validate_arn_shape(cls, value: str) -> str:
        """Fail fast on an obviously malformed ARN."""
        if not value.startswith("arn:aws"):
            raise ValueError(f"Not a well-formed AWS ARN: {value!r}")
        return value
