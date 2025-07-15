import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime
from typing import List

import pika
from azure.storage.blob import BlobServiceClient, ContainerClient, BlobProperties  # type: ignore
from opentelemetry import trace  # type: ignore
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  # type: ignore
from opentelemetry.sdk.resources import SERVICE_NAME, Resource  # type: ignore
from opentelemetry.sdk.trace import TracerProvider  # type: ignore
from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore
from pythonjsonlogger import jsonlogger  # type: ignore
from otel_logging import init_logging

# ---------------------------------------------------------------------------
# Configuration via environment variables (with sensible defaults)
# ---------------------------------------------------------------------------
AZURITE_CONN_STR = os.getenv(
    "AZURITE_CONNECTION_STRING",
    "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://azurite:10000/devstoreaccount1;",
)
CONTAINER_NAME = os.getenv("BLOB_CONTAINER", "incoming")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "60"))  # seconds

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "ic-tester")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "ic-tester")
RABBITMQ_QUEUE = os.getenv("RABBITMQ_QUEUE", "blob.events")

SERVICE_NAME_VALUE = os.getenv("OTEL_SERVICE_NAME", "BlobBasedEventHandler")

# ---------------------------------------------------------------------------
# Logging & Tracing setup
# ---------------------------------------------------------------------------
# initialize logging and tracing
logger, tracer = init_logging(SERVICE_NAME_VALUE)

# ---------------------------------------------------------------------------
# RabbitMQ utilities
# ---------------------------------------------------------------------------

def get_rabbit_connection():
    creds = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    parameters = pika.ConnectionParameters(host=RABBITMQ_HOST, port=RABBITMQ_PORT, credentials=creds)
    return pika.BlockingConnection(parameters)


def ensure_queue(channel):
    channel.queue_declare(queue=RABBITMQ_QUEUE, durable=True)

# ---------------------------------------------------------------------------
# Blob utilities
# ---------------------------------------------------------------------------

def list_blobs(container_client: ContainerClient) -> List[BlobProperties]:
    return [blob for blob in container_client.list_blobs()]  # type: ignore


def build_message(container: str, blob_path: str, blob_name: str) -> dict:
    dest_path = f"processed/{uuid.uuid4()}-{blob_name}"
    return {
        "container": container,
        "path": blob_path,
        "blob": blob_name,
        "dest": dest_path,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

# ---------------------------------------------------------------------------
# Main polling loop
# ---------------------------------------------------------------------------

def main():
    logger.info("Starting BlobBasedEventHandler", extra={"event": "startup"})

    # Connect to Azurite
    blob_service = BlobServiceClient.from_connection_string(AZURITE_CONN_STR)
    container_client = blob_service.get_container_client(CONTAINER_NAME)

    # Connect to RabbitMQ once at startup; recreate if closed
    rabbit_conn = get_rabbit_connection()
    channel = rabbit_conn.channel()
    ensure_queue(channel)

    while True:
        with tracer.start_as_current_span("poll_iteration"):
            try:
                blobs = list_blobs(container_client)
                logger.info("Polled container", extra={"blob_count": len(blobs)})

                for blob in blobs:
                    # Skip blobs already processed (simple heuristic)
                    if blob.name.startswith("processed/"):
                        continue

                    path, _, name = blob.name.rpartition("/")
                    msg_body = build_message(CONTAINER_NAME, path + "/" if path else "", name)

                    channel.basic_publish(
                        exchange="",
                        routing_key=RABBITMQ_QUEUE,
                        body=json.dumps(msg_body),
                        properties=pika.BasicProperties(delivery_mode=2),  # persistent
                    )
                    logger.info("Published blob event", extra={"blob": blob.name})
            except Exception as exc:
                logger.exception("Error during poll iteration", extra={"error": str(exc)})
                # Attempt to recreate RabbitMQ connection if necessary
                if rabbit_conn.is_closed:
                    try:
                        rabbit_conn = get_rabbit_connection()
                        channel = rabbit_conn.channel()
                        ensure_queue(channel)
                    except Exception:
                        logger.exception("Failed to reconnect to RabbitMQ")
            finally:
                time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main() 