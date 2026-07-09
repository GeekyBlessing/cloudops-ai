"""Shared pytest fixtures for the backend test suite."""

from __future__ import annotations

import pytest


@pytest.fixture
def approval_secret_key() -> bytes:
    """A fixed HMAC secret for tests only -- real environments read this
    from core/config.py, backed by a secret manager."""
    return b"test-secret-key-do-not-use-outside-tests"
