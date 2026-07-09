"""Service layer: orchestration logic that sits between API routers and the
domain/agents/repositories underneath. Routers should stay thin -- HTTP
concerns only -- and call into here, so the same workflow (e.g. approving a
remediation plan) could later be triggered from a Slack bot or CLI without
duplicating the logic.
"""
