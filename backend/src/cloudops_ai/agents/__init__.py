"""LangGraph agent graph + node implementations.

This package is where domain models (framework-free) meet LangGraph and the
LLM provider. Nodes are plain functions built by factory functions that
close over injected dependencies (an AWS tool set, a chat model) -- see
graph.py for how those are wired together, and coordinator.py's docstring
for why the LLM is never allowed to choose a remediation action directly.
"""
