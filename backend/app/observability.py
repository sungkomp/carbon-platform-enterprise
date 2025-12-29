from __future__ import annotations
import logging
import structlog
from prometheus_client import Counter, Histogram

REQ_COUNTER = Counter("http_requests_total", "Total HTTP requests", ["method","path","status"])
REQ_LATENCY = Histogram("http_request_latency_seconds", "HTTP request latency", ["path"])

def configure_logging():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    )

log = structlog.get_logger()
