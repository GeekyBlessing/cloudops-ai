"""Unit tests for the remediation policy allow-list."""

from __future__ import annotations

from cloudops_ai.domain.enums import IncidentType, Severity
from cloudops_ai.domain.policies.remediation_policy import is_action_allowed


def test_allowed_action_for_known_combination() -> None:
    assert is_action_allowed(IncidentType.EC2_HIGH_CPU, Severity.HIGH, "reboot_instance") is True


def test_disallowed_action_for_known_combination() -> None:
    assert is_action_allowed(IncidentType.EC2_HIGH_CPU, Severity.HIGH, "terminate_instance") is False


def test_unknown_combination_fails_closed() -> None:
    assert is_action_allowed(IncidentType.HIGH_BILLING, Severity.CRITICAL, "terminate_instance") is False
