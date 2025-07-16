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
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "2"))  # Check every 2 seconds for responsive scaling
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
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        logger.error("Podman command failed", extra={
            "command": " ".join(cmd),
            "return_code": e.returncode,
            "stdout": e.stdout,
            "stderr": e.stderr
        })
        raise


def get_queue_length() -> int:
    resp = requests.get(RABBITMQ_API, auth=(RABBITMQ_USER, RABBITMQ_PASS), timeout=5)
    resp.raise_for_status()
    data: Dict[str, Any] = resp.json() or {}
    return int(data.get("messages_ready", 0))


def list_processor_containers() -> List[Dict[str, Any]]:
    """List containers with our labels."""
    try:
        output = run_podman_command([
            "ps", "--format", "json",
            "--filter", f"label=managed-by={LABEL_MANAGED_BY}",
            "--filter", f"label=role={LABEL_ROLE}"
        ])
        if output.strip():
            return json.loads(output)
        return []
    except subprocess.CalledProcessError as e:
        logger.error("Failed to list processor containers", extra={"error": str(e)})
        return []  # Return empty list if we can't list containers


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
        logger.info("Started container", extra={"container_name": container_name})


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


def cleanup_stale_containers():
    """Clean up containers that may have failed to auto-terminate."""
    try:
        containers = list_processor_containers()
        for c in containers:
            container_id = c.get("Id", c.get("ID", ""))[:12]
            if container_id:
                # Check if container has been running too long (more than 5 minutes is suspicious)
                created_str = c.get("CreatedAt", "")
                if created_str:
                    try:
                        # Parse creation time and check age
                        from datetime import datetime, timezone
                        import re
                        
                        # Handle different timestamp formats
                        if "ago" in created_str:
                            # Skip parsing "X minutes ago" format for now
                            continue
                            
                        # Remove timezone info for parsing
                        clean_time = re.sub(r'\s+[A-Z]{3,4}$', '', created_str)
                        created_time = datetime.strptime(clean_time, "%Y-%m-%d %H:%M:%S")
                        age_seconds = (datetime.now() - created_time).total_seconds()
                        
                        if age_seconds > 300:  # 5 minutes
                            logger.info("Cleaning up stale container", extra={
                                "container_id": container_id,
                                "age_seconds": age_seconds
                            })
                            run_podman_command(["stop", "-t", "5", container_id])
                            run_podman_command(["rm", container_id])
                    except Exception as parse_err:
                        logger.debug("Could not parse container creation time", extra={
                            "container_id": container_id,
                            "created_str": created_str,
                            "error": str(parse_err)
                        })
    except Exception as cleanup_err:
        logger.error("Error during container cleanup", extra={"error": str(cleanup_err)})

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    logger.info("Starting KedaTestScaler for single-job containers", extra={"event": "startup", "mode": "single_job"})
    while True:
        with tracer.start_as_current_span("scale_iteration"):
            try:
                q_len = get_queue_length()
                running = len(list_processor_containers())
                
                # Maintain a constant pool of active containers up to MAX_REPLICAS
                # as long as there are messages in the queue
                if q_len > 0:
                    # We want to maintain MAX_REPLICAS active containers
                    target_containers = MAX_REPLICAS
                    containers_to_create = target_containers - running
                    
                    if containers_to_create > 0:
                        scale_up(containers_to_create)
                        logger.info("Scaling up to maintain active pool", extra={
                            "containers_created": containers_to_create,
                            "queue_messages": q_len,
                            "running_containers": running,
                            "target_containers": target_containers
                        })
                elif running > 0:
                    # No messages in queue, but we still have running containers
                    # Let them finish naturally (don't force stop since they'll exit soon)
                    logger.info("Queue empty, letting containers finish naturally", extra={
                        "running_containers": running,
                        "queue_messages": q_len
                    })

                # Clean up any containers that may have failed to auto-terminate
                # (This is a safety measure - containers should exit on their own)
                cleanup_stale_containers()

                logger.info("Scale iteration", extra={
                    "queue_len": q_len, 
                    "running": running, 
                    "target": MAX_REPLICAS if q_len > 0 else 0,
                    "mode": "single_job"
                })
            except Exception as exc:
                logger.exception("Scaler iteration failed", extra={"error": str(exc)})
            finally:
                time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main() 