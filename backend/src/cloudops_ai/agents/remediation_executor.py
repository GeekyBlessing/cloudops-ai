"""Remediation Executor: the only node in the graph permitted to call
mutating AWS APIs.

Everything upstream of this node -- Coordinator, Monitoring, and eventually
Security/Cost/Troubleshooting -- only ever holds an IReadOnlyAWSTools
instance. This file is where IMutatingAWSTools actually gets exercised, and
only after RemediationPlan.can_execute_live() returns True. See
/docs/ARCHITECTURE.md section 4.3 and domain/models/remediation.py for the
full safety story this node is the last link in.

This node is NOT wired into the main classify -> gather_metrics -> decide
graph (agents/graph.py). Remediation only ever happens after an out-of-band
human approval via the /remediation/{id}/approve endpoint, not as part of
the automatic investigation flow -- see services/approval_service.py, which
is what actually calls this node, once, after signing an approval.
"""

from __future__ import annotations

import uuid
from typing import Callable

from cloudops_ai.agents.state import GraphState
from cloudops_ai.domain.enums import AgentName, RemediationStatus
from cloudops_ai.domain.models.evidence import AgentStep
from cloudops_ai.domain.models.remediation import RemediationAction
from cloudops_ai.tools.interfaces import IMutatingAWSTools


def _extract_instance_id(arn: str) -> str:
    """`arn:aws:ec2:region:account:instance/i-0abc123` -> `i-0abc123`."""
    return arn.rsplit("/", 1)[-1]


def _extract_bucket_name(arn: str) -> str:
    """`arn:aws:s3:::bucket-name` -> `bucket-name` (S3 bucket ARNs have no region/account segment)."""
    return arn.split(":::", 1)[-1]


# One entry per IMutatingAWSTools method, and only those methods -- this map
# is the single place that translates a RemediationAction's (target_arn,
# parameters) into the right method call. tests/unit/agents/test_remediation_executor.py
# asserts every action_name that can ever appear in REMEDIATION_POLICY has an
# entry here, so the policy table and this map can't silently drift apart.
_ACTION_INVOKERS: dict[str, Callable[[IMutatingAWSTools, RemediationAction], None]] = {
    "reboot_instance": lambda tools, action: tools.reboot_instance(_extract_instance_id(action.target_arn)),
    "start_instance": lambda tools, action: tools.start_instance(_extract_instance_id(action.target_arn)),
    "scale_out": lambda tools, action: tools.scale_out(
        auto_scaling_group_name=action.parameters.get("auto_scaling_group_name", action.target_arn),
        increment=action.parameters.get("increment", 1),
    ),
    "revoke_public_access": lambda tools, action: tools.revoke_public_access(
        _extract_bucket_name(action.target_arn)
    ),
    "detach_overly_permissive_policy": lambda tools, action: tools.detach_overly_permissive_policy(
        role_name=action.parameters.get("role_name", action.target_arn),
        policy_arn=action.parameters.get("policy_arn", ""),
    ),
    "rollback_function_version": lambda tools, action: tools.rollback_function_version(
        function_name=action.parameters.get("function_name", action.target_arn),
        target_version=action.parameters.get("target_version", ""),
    ),
    "increase_storage_allocation": lambda tools, action: tools.increase_storage_allocation(
        db_instance_identifier=action.parameters.get("db_instance_identifier", action.target_arn),
        new_allocated_storage_gb=action.parameters.get("new_allocated_storage_gb", 100),
    ),
    "reset_desired_capacity": lambda tools, action: tools.reset_desired_capacity(
        auto_scaling_group_name=action.parameters.get("auto_scaling_group_name", action.target_arn),
        desired_capacity=action.parameters.get("desired_capacity", 1),
    ),
}


def make_remediation_executor_node(
    mutating_tools: IMutatingAWSTools, secret_key: bytes
) -> Callable[[GraphState], GraphState]:
    """Factory that closes over the mutating tool set and the HMAC secret
    used to verify approvals.
    """

    def remediation_executor_node(state: GraphState) -> GraphState:
        incident = state["incident"]
        plan = incident.proposed_remediation
        step = AgentStep(step_id=str(uuid.uuid4()), agent=AgentName.REMEDIATION_EXECUTOR, reasoning="")

        if plan is None:
            step.reasoning = "No proposed remediation plan on this incident; nothing to execute."
            step.mark_completed()
            incident.add_agent_step(step)
            return {"incident": incident}

        if not plan.can_execute_live(secret_key):
            step.reasoning = (
                f"Plan {plan.plan_id} is not executable (status={plan.status.value}, "
                f"approval={'present' if plan.approval else 'missing'}) -- refusing to execute. "
                "This should not normally be reachable outside a bug in the caller, since "
                "services/approval_service.py checks status before invoking this node."
            )
            step.mark_completed()
            incident.add_agent_step(step)
            return {"incident": incident}

        plan.status = RemediationStatus.EXECUTING
        incident.remediation_status = RemediationStatus.EXECUTING

        executed_actions: list[str] = []
        try:
            for action in plan.actions:
                invoker = _ACTION_INVOKERS.get(action.action_name)
                if invoker is None:
                    raise RuntimeError(
                        f"No executor mapping for action {action.action_name!r} -- the policy table "
                        "allows an action this node doesn't know how to run. This is a code bug, "
                        "not a runtime/environment problem."
                    )
                invoker(mutating_tools, action)
                executed_actions.append(action.action_name)
                step.tool_calls.append(f"mutating.{action.action_name}")

            plan.status = RemediationStatus.VERIFIED
            incident.remediation_status = RemediationStatus.VERIFIED
            step.reasoning = (
                f"Executed {len(executed_actions)} action(s): {', '.join(executed_actions)}. "
                "Marked VERIFIED -- note this is optimistic verification (the AWS call "
                "succeeded), not confirmation the underlying issue is resolved; that requires "
                "the Monitoring Agent to re-check the original signal on a timer, which is a "
                "follow-up step (ARCHITECTURE.md's incident lifecycle step 8) not yet built."
            )
        except Exception as exc:  # noqa: BLE001 -- deliberately broad: any failure here must
            # flip the plan to FAILED and stop, not propagate and leave state inconsistent.
            plan.status = RemediationStatus.FAILED
            incident.remediation_status = RemediationStatus.FAILED
            step.reasoning = f"Execution failed after {len(executed_actions)} action(s): {exc}"

        step.mark_completed()
        incident.add_agent_step(step)
        return {"incident": incident}

    return remediation_executor_node
