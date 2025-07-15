import json
import logging
import os
import sys
import time
from typing import List, Any, Dict

import docker  # type: ignore
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

docker_client = docker.DockerClient(base_url="unix:///var/run/docker.sock")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_queue_length() -> int:
    resp = requests.get(RABBITMQ_API, auth=(RABBITMQ_USER, RABBITMQ_PASS), timeout=5)
    resp.raise_for_status()
    data: Dict[str, Any] = resp.json() or {}
    return int(data.get("messages_ready", 0))


def list_processor_containers() -> List[docker.models.containers.Container]:  # type: ignore
    return docker_client.containers.list(filters={"label": [f"managed-by={LABEL_MANAGED_BY}", f"role={LABEL_ROLE}"]})  # type: ignore[arg-type]


def scale_up(count: int):
    logger.info("Scaling up", extra={"count": count})
    for _ in range(count):
        container = docker_client.containers.run(
            PROCESSOR_IMAGE,
            detach=True,
            network=NETWORK_NAME,
            labels={"managed-by": LABEL_MANAGED_BY, "role": LABEL_ROLE},
            environment={
                "RABBITMQ_HOST": "rabbitmq",
                "RABBITMQ_USER": RABBITMQ_USER,
                "RABBITMQ_PASS": RABBITMQ_PASS,
            },
            name=f"blob-processor-{int(time.time()*1000)}",
        )
        logger.info("Started container", extra={"id": container.id[:12]})


def scale_down(count: int):
    logger.info("Scaling down", extra={"count": count})
    containers = list_processor_containers()[:count]
    for c in containers:
        logger.info("Stopping container", extra={"id": c.id[:12]})
        try:
            c.stop(timeout=5)
            c.remove()
        except Exception as exc:
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