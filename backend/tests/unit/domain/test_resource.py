"""Unit tests for ResourceRef, in particular the ARN sanity check."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cloudops_ai.domain.models.resource import ResourceRef


def test_valid_arn_is_accepted() -> None:
    ref = ResourceRef(
        arn="arn:aws:ec2:us-east-1:123456789012:instance/i-0abcd1234",
        resource_type="AWS::EC2::Instance",
        region="us-east-1",
        account_id="123456789012",
    )
    assert ref.arn.startswith("arn:aws")


def test_malformed_arn_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ResourceRef(
            arn="not-an-arn",
            resource_type="AWS::EC2::Instance",
            region="us-east-1",
            account_id="123456789012",
        )
