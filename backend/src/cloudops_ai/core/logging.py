"""Structured logging configuration using structlog.

Every log line in the application should be structured JSON in production
-- this is what lets CloudWatch Logs Insights (or any log aggregator) query
on fields like `incident_id` or `action` directly instead of regex-parsing
a free-text message. Called once, at application startup.
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Configure both the stdlib `logging` module and structlog to emit
    structured JSON to stdout.

    Configuring stdlib logging too (not just structlog) matters because
    third-party libraries (boto3, uvicorn, langgraph) log through the
    stdlib logger, not structlog directly -- without this, half the log
    stream would be structured JSON and half would be plain text.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=numeric_level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
