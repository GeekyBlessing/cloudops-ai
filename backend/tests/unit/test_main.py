"""Tests for main.py's ASGI lifespan hook (_lifespan).

create_app()'s synchronous body (middleware, routers, /health) is already
exercised indirectly by every router test that builds a TestClient via
create_app() (see test_auth.py). This file targets _lifespan directly --
the one part of main.py no existing test ever actually triggers, since
none of them enter the ASGI lifespan context manager.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI

from cloudops_ai.core.config import Settings
from cloudops_ai.services.sqs_incident_poller import SQSIncidentPoller


async def _fake_run_forever(self: SQSIncidentPoller) -> None:
    """Stands in for the real polling loop -- sleeps until cancelled, so
    the cancellation path below has something real to cancel without
    depending on the poller's actual AWS-facing behavior.
    """
    await asyncio.sleep(3600)


@pytest.mark.asyncio
async def test_lifespan_is_a_noop_without_sqs_queue_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default (no CLOUDOPS_SQS_QUEUE_URL set) -- every existing test
    relies on this being side-effect-free.
    """
    import cloudops_ai.main as main_module

    monkeypatch.setattr(main_module, "get_settings", lambda: Settings(sqs_queue_url=None))

    app = FastAPI()
    async with main_module._lifespan(app):
        pass


@pytest.mark.asyncio
async def test_lifespan_starts_and_cleanly_cancels_poller(monkeypatch: pytest.MonkeyPatch) -> None:
    """When CLOUDOPS_SQS_QUEUE_URL is set, the poller must be started as a
    background task on entry and cancelled -- not left dangling, and not
    letting asyncio.CancelledError escape -- on exit.
    """
    import cloudops_ai.main as main_module

    settings = Settings(sqs_queue_url="https://sqs.us-east-1.amazonaws.com/123456789012/test-queue")
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(SQSIncidentPoller, "run_forever", _fake_run_forever)

    app = FastAPI()
    async with main_module._lifespan(app):
        # Give the background task a chance to actually start running
        # before the context manager exits and cancels it.
        await asyncio.sleep(0)
    # If we get here without an unhandled asyncio.CancelledError or a hung
    # test, the cancel-and-suppress logic in _lifespan worked correctly.
