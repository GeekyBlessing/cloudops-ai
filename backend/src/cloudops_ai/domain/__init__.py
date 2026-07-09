"""Domain layer: framework-free business models and rules.

Hard rule for this package and everything under it: no imports of `boto3`,
`langgraph`, `langchain*`, or `fastapi`. This layer models "what an incident,
a remediation plan, and a piece of evidence *are*" -- not how they're stored,
fetched, or reasoned about by an LLM. Every other layer in the codebase is
allowed to depend on `domain`; `domain` is not allowed to depend on them.
"""
