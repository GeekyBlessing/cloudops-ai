"""Unit tests for the dry-run mutating adapter."""

from __future__ import annotations

from cloudops_ai.tools.dry_run.dry_run_adapter import DryRunAWSTools


def test_reboot_instance_logs_without_raising() -> None:
    adapter = DryRunAWSTools()
    adapter.reboot_instance("i-0abcd1234")
    assert adapter.actions_logged == [{"action": "reboot_instance", "instance_id": "i-0abcd1234"}]


def test_multiple_actions_accumulate_in_order() -> None:
    adapter = DryRunAWSTools()
    adapter.reboot_instance("i-1")
    adapter.scale_out("asg-1", increment=2)
    adapter.revoke_public_access("my-bucket")
    logged_actions = [entry["action"] for entry in adapter.actions_logged]
    assert logged_actions == ["reboot_instance", "scale_out", "revoke_public_access"]


def test_every_mutating_tool_method_is_covered_by_the_dry_run_adapter() -> None:
    from cloudops_ai.tools.interfaces import IMutatingAWSTools

    expected_methods = {name for name in dir(IMutatingAWSTools) if not name.startswith("_")}
    actual_methods = {name for name in dir(DryRunAWSTools) if not name.startswith("_")}
    missing = expected_methods - actual_methods
    assert not missing, f"DryRunAWSTools is missing methods required by IMutatingAWSTools: {missing}"
