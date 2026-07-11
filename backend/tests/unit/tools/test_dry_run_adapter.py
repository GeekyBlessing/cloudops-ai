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


def test_start_instance_logs_without_raising() -> None:
    adapter = DryRunAWSTools()
    adapter.start_instance("i-0abcd1234")
    assert adapter.actions_logged == [{"action": "start_instance", "instance_id": "i-0abcd1234"}]


def test_detach_overly_permissive_policy_logs_without_raising() -> None:
    adapter = DryRunAWSTools()
    adapter.detach_overly_permissive_policy("my-role", "arn:aws:iam::123456789012:policy/too-broad")
    assert adapter.actions_logged == [
        {
            "action": "detach_overly_permissive_policy",
            "role_name": "my-role",
            "policy_arn": "arn:aws:iam::123456789012:policy/too-broad",
        }
    ]


def test_rollback_function_version_logs_without_raising() -> None:
    adapter = DryRunAWSTools()
    adapter.rollback_function_version("my-function", "3")
    assert adapter.actions_logged == [
        {"action": "rollback_function_version", "function_name": "my-function", "target_version": "3"}
    ]


def test_increase_storage_allocation_logs_without_raising() -> None:
    adapter = DryRunAWSTools()
    adapter.increase_storage_allocation("my-db-instance", 200)
    assert adapter.actions_logged == [
        {
            "action": "increase_storage_allocation",
            "db_instance_identifier": "my-db-instance",
            "new_allocated_storage_gb": 200,
        }
    ]


def test_reset_desired_capacity_logs_without_raising() -> None:
    adapter = DryRunAWSTools()
    adapter.reset_desired_capacity("my-asg", 3)
    assert adapter.actions_logged == [
        {"action": "reset_desired_capacity", "auto_scaling_group_name": "my-asg", "desired_capacity": 3}
    ]
