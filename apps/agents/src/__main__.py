"""Standalone runtime entrypoint for the RISE agents (LangGraph orchestrator).

HONEST SCOPE: the compiled orchestrator graph is a *library* that the API and
the Celery worker execute in-process (see apps/api importing apps.agents). It
has no request/queue server of its own. This module exists only so the agents
package can be built and run as its own container image and health-checked in
Kubernetes: on start it compiles the orchestrator graph (which validates that
every engine, node, and route imports and the StateGraph assembles), then holds
the process open behind a stdlib liveness endpoint. It does NOT accept incident
traffic over the network. Run with: ``python -m apps.agents.src``.
"""
from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from apps.agents.src.orchestrator.graph import create_orchestrator_graph

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("rise.agents")

# Compile at import/start so a broken graph fails the container immediately
# (fail-loud) rather than passing health checks with a graph that cannot build.
_GRAPH = create_orchestrator_graph()


class _LivenessHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        if self.path.rstrip("/") in ("/healthz", "/health", ""):
            body = json.dumps({"status": "ok", "graph": "compiled"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *_args) -> None:  # silence per-request access logs
        return


def main() -> None:
    port = int(os.getenv("AGENTS_HEALTH_PORT", "8000"))
    logger.info("RISE agents graph compiled; serving liveness on :%d", port)
    ThreadingHTTPServer(("0.0.0.0", port), _LivenessHandler).serve_forever()


if __name__ == "__main__":
    main()
