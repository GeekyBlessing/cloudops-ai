"""FastAPI application factory.

`create_app()` builds the app rather than a bare module-level `app =
FastAPI()`, so tests can construct a fresh app (with overridden
dependencies) without import-order surprises, and so the ASGI lifespan
hook below (starting/stopping the SQS incident-trigger poller) has one
obvious place to live.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cloudops_ai.api.dependencies import get_aws_tools, get_chat_model, get_incident_repository
from cloudops_ai.api.routers import incidents, remediation
from cloudops_ai.core.config import get_settings
from cloudops_ai.core.logging import configure_logging
from cloudops_ai.services.sqs_incident_poller import SQSIncidentPoller


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Starts the SQS incident-trigger poller as a background task, if
    configured, and cancels it cleanly on shutdown rather than leaving it
    dangling.

    A no-op (yields immediately, nothing else happens) when
    CLOUDOPS_SQS_QUEUE_URL isn't set, which is the default -- local
    development and every existing test continue to work exactly as
    before this was added. The poller reuses the exact same dependency
    factories (get_incident_repository/get_aws_tools/get_chat_model) the
    HTTP request handlers use, so it respects whatever CLOUDOPS_USE_DYNAMODB/
    CLOUDOPS_USE_REAL_AWS/provider-key settings are already configured --
    there's no separate "background task config" to keep in sync.
    """
    settings = get_settings()
    poller_task: asyncio.Task[None] | None = None

    if settings.sqs_queue_url:
        poller = SQSIncidentPoller(
            settings=settings,
            repo=get_incident_repository(settings),
            aws_tools=get_aws_tools(settings),
            chat_model=get_chat_model(settings),
        )
        poller_task = asyncio.create_task(poller.run_forever())

    yield

    if poller_task is not None:
        poller_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await poller_task


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="CloudOps AI",
        description=(
            "Agentic AI Cloud Engineer -- monitors AWS, diagnoses incidents, and remediates "
            "them under human-gated approval."
        ),
        version="0.1.0",
        lifespan=_lifespan,
    )

    # Required for frontend/ (a separate origin, e.g. http://localhost:5173
    # in dev) to call this API from the browser at all -- without this,
    # every request from the dashboard fails at the browser's CORS
    # preflight before it ever reaches a route. allow_origins is read from
    # settings, not hardcoded, so a deployed dashboard's real origin can be
    # configured via CLOUDOPS_CORS_ORIGINS without touching code.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(incidents.router)
    app.include_router(remediation.router)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        """Liveness/readiness probe for the ECS Fargate task definition."""
        return {"status": "ok"}

    return app


app = create_app()
