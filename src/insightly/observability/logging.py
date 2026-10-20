"""Structured logging and CloudWatch Embedded Metric Format (EMF).

EMF lets the service publish CloudWatch metrics by writing one JSON log line, with no
PutMetricData API calls (cheaper, no extra IAM, no latency on the request path).
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

import structlog

from insightly.config import get_settings


def configure_logging() -> None:
    s = get_settings()
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    processors.append(structlog.processors.JSONRenderer() if s.log_json else structlog.dev.ConsoleRenderer())
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(s.log_level.upper(), logging.INFO)
        ),
    )


log = structlog.get_logger("insightly")


def emit_metrics(dimensions: dict[str, str], metrics: dict[str, tuple[float, str]]) -> None:
    """Write one EMF record. ``metrics`` maps name -> (value, unit)."""
    s = get_settings()
    if not s.emit_cloudwatch_emf:
        return
    record: dict[str, Any] = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": s.metrics_namespace,
                    "Dimensions": [list(dimensions.keys())],
                    "Metrics": [{"Name": k, "Unit": u} for k, (_, u) in metrics.items()],
                }
            ],
        },
        **dimensions,
        **{k: v for k, (v, _) in metrics.items()},
    }
    sys.stdout.write(json.dumps(record) + "\n")
    sys.stdout.flush()
