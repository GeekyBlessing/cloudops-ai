"""FastAPI application factory.

`create_app()` builds the app rather than a bare module-level `app =
FastAPI()`, so tests can construct a fresh app (with overridden
dependencies) without import-order surprises, and so a future ASGI
lifespan hook (e.g. warming a DynamoDB connection pool) has one obvious
place to live.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cloudops_ai.api.routers import incidents, remediation
from cloudops_ai.core.config import get_settings
from cloudops_ai.core.logging import configure_logging


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
