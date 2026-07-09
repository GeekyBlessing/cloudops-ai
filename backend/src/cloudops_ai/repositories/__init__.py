"""Repository layer: persistence access behind interfaces. Routers and
services depend on these interfaces, never on a specific backing store, so
swapping in-memory -> DynamoDB is a one-line dependency-injection change.
"""
