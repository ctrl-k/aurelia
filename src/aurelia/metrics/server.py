"""HTTP server for Prometheus metrics endpoint."""

from __future__ import annotations

import logging

from prometheus_client import start_http_server

logger = logging.getLogger(__name__)


def start_metrics_server(port: int = 9090) -> None:
    """Start Prometheus metrics HTTP server.

    This starts a background thread that serves the /metrics endpoint.

    Args:
        port: Port to listen on. Default is 9090.
    """
    start_http_server(port)
    logger.info("Prometheus metrics server started on port %d", port)
