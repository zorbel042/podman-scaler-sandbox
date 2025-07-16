import json
import logging
import os
import subprocess
import sys
import time
from typing import List, Any, Dict

import requests
from opentelemetry import trace  # type: ignore
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  # type: ignore
from opentelemetry.sdk.resources import SERVICE_NAME, Resource  # type: ignore
from opentelemetry.sdk.trace import TracerProvider  # type: ignore
from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore
from pythonjsonlogger import jsonlogger  # type: ignore

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
RABBITMQ_API = os.getenv("RABBITMQ_API", "http://rabbitmq:15672/api/queues/%2F/blob.events")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "ic-tester")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "ic-tester")

PROCESSOR_IMAGE = os.getenv("BLOB_PROCESSOR_IMAGE", "localhost/sandboxtest/blob-processor:latest")
MAX_REPLICAS = int(os.getenv("MAX_REPLICAS", "10"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "30"))
NETWORK_NAME = os.getenv("APP_NETWORK", "app-network")
LABEL_MANAGED_BY = "keda-test-scaler"
LABEL_ROLE = "blob_processor"
CONTAINER_LABEL = {
    "managed-by": LABEL_MANAGED_BY,
    "role": LABEL_ROLE,
}

SERVICE_NAME_VALUE = os.getenv("OTEL_SERVICE_NAME", "KedaTestScaler")

from otel_logging import init_logging  # isort: skip

logger, tracer = init_logging(SERVICE_NAME_VALUE)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_podman_command(args: List[str]) -> str:
    """Run a podman command and return the output."""
    cmd = ["podman"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout


def get_queue_length() -> int:
    resp = requests.get(RABBITMQ_API, auth=(RABBITMQ_USER, RABBITMQ_PASS), timeout=5)
    resp.raise_for_status()
    data: Dict[str, Any] = resp.json() or {}
    return int(data.get("messages_ready", 0))


def list_processor_containers() -> List[Dict[str, Any]]:
    """List containers with our labels."""
    output = run_podman_command([
        "ps", "--format", "json",
        "--filter", f"label=managed-by={LABEL_MANAGED_BY}",
        "--filter", f"label=role={LABEL_ROLE}"
    ])
    if output.strip():
        return json.loads(output)
    return []


def scale_up(count: int):
    logger.info("Scaling up", extra={"count": count})
    for _ in range(count):
        container_name = f"blob-processor-{int(time.time()*1000)}"
        run_podman_command([
            "run", "-d",
            "--network", NETWORK_NAME,
            "--label", f"managed-by={LABEL_MANAGED_BY}",
            "--label", f"role={LABEL_ROLE}",
            "-e", f"RABBITMQ_HOST=rabbitmq",
            "-e", f"RABBITMQ_USER={RABBITMQ_USER}",
            "-e", f"RABBITMQ_PASS={RABBITMQ_PASS}",
            "--name", container_name,
            PROCESSOR_IMAGE
        ])
        logger.info("Started container", extra={"name": container_name})


def scale_down(count: int):
    logger.info("Scaling down", extra={"count": count})
    containers = list_processor_containers()[:count]
    for c in containers:
        container_id = c.get("Id", c.get("ID", ""))[:12]
        if container_id:
            logger.info("Stopping container", extra={"id": container_id})
            try:
                run_podman_command(["stop", "-t", "5", container_id])
                run_podman_command(["rm", container_id])
            except subprocess.CalledProcessError as exc:
                logger.exception("Failed to stop container", extra={"error": str(exc)})

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    logger.info("Starting KedaTestScaler", extra={"event": "startup"})
    while True:
        with tracer.start_as_current_span("scale_iteration"):
            try:
                q_len = get_queue_length()
                running = len(list_processor_containers())
                target = min(q_len, MAX_REPLICAS)

                if target > running:
                    scale_up(target - running)
                elif target < running:
                    scale_down(running - target)

                logger.info("Scale iteration", extra={"queue_len": q_len, "running": running, "target": target})
            except Exception as exc:
                logger.exception("Scaler iteration failed", extra={"error": str(exc)})
            finally:
                time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main() 