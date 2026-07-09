"""Real, boto3-backed implementation of IReadOnlyAWSTools.

This is the read-only half of the "real AWS" story -- the mutating half
(tools/mutating/) is deliberately not built yet, per /docs/ARCHITECTURE.md's
safety design: read access comes first and alone, mutating access is added
later, behind its own gated executor, once the dry-run/approval machinery
around it is airtight.
"""
