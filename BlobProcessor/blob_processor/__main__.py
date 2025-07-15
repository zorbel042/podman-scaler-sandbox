import json
import logging
import os
import sys
import uuid
from datetime import datetime

import pika
from azure.storage.blob import BlobServiceClient, ContainerClient  # type: ignore
from opentelemetry import trace  # type: ignore
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  # type: ignore
from opentelemetry.sdk.resources import SERVICE_NAME, Resource  # type: ignore
from opentelemetry.sdk.trace import TracerProvider  # type: ignore
from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore
from pythonjsonlogger import jsonlogger  # type: ignore
from tenacity import retry, stop_after_attempt, wait_exponential, RetryError  # type: ignore
from otel_logging import init_logging

SERVICE_NAME_VALUE = os.getenv("OTEL_SERVICE_NAME", "BlobProcessor")

logger, tracer = init_logging(SERVICE_NAME_VALUE)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
AZURITE_CONN_STR = os.getenv(
    "AZURITE_CONNECTION_STRING",
    "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://azurite:10000/devstoreaccount1;",
)
CONTAINER_NAME = os.getenv("BLOB_CONTAINER", "incoming")

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "rabbitmq")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "ic-tester")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "ic-tester")
EVENT_QUEUE = os.getenv("RABBITMQ_QUEUE", "blob.events")
ERROR_QUEUE = os.getenv("RABBITMQ_DLQ", "blob.error")


# ---------------------------------------------------------------------------
# Blob helpers
# ---------------------------------------------------------------------------

blob_service = BlobServiceClient.from_connection_string(AZURITE_CONN_STR)
container_client: ContainerClient = blob_service.get_container_client(CONTAINER_NAME)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4))
def move_blob(src_blob: str, dest_blob: str):
    src_client = container_client.get_blob_client(src_blob)
    dest_client = container_client.get_blob_client(dest_blob)

    # Start copy
    copy = dest_client.start_copy_from_url(src_client.url)
    logger.info("Copy initiated", extra={"src": src_blob, "dest": dest_blob, "copy_id": copy[1]})

    # Delete source after copy (simplified – immediate)
    src_client.delete_blob()


# ---------------------------------------------------------------------------
# Rabbit utilities
# ---------------------------------------------------------------------------

def get_rabbit_connection():
    creds = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)
    params = pika.ConnectionParameters(host=RABBITMQ_HOST, port=RABBITMQ_PORT, credentials=creds)
    return pika.BlockingConnection(params)


def ensure_queues(channel):
    channel.queue_declare(queue=EVENT_QUEUE, durable=True)
    channel.queue_declare(queue=ERROR_QUEUE, durable=True)


# ---------------------------------------------------------------------------
# Message processing
# ---------------------------------------------------------------------------

def process_message(ch, method, properties, body):  # noqa: N803 – pika naming
    with tracer.start_as_current_span("process_blob"):
        try:
            msg = json.loads(body)
            src_blob = os.path.join(msg["path"], msg["blob"]) if msg["path"] else msg["blob"]
            dest_blob = msg["dest"]
            move_blob(src_blob, dest_blob)
            logger.info("Blob processed", extra={"src": src_blob, "dest": dest_blob})
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except RetryError as rexc:
            logger.error("Retries exhausted", extra={"error": str(rexc)})
            publish_error(ch, body, str(rexc))
            ch.basic_ack(delivery_tag=method.delivery_tag)
        except Exception as exc:
            logger.exception("Processing failed", extra={"error": str(exc)})
            publish_error(ch, body, str(exc))
            ch.basic_ack(delivery_tag=method.delivery_tag)


def publish_error(ch, original_body: bytes, error: str):
    try:
        error_msg = json.loads(original_body)
    except json.JSONDecodeError:
        error_msg = {"raw": original_body.decode()}
    error_msg.update({"error": error, "failed_at": datetime.utcnow().isoformat() + "Z"})
    ch.basic_publish(exchange="", routing_key=ERROR_QUEUE, body=json.dumps(error_msg), properties=pika.BasicProperties(delivery_mode=2))


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def main():
    logger.info("Starting BlobProcessor", extra={"event": "startup"})

    rabbit_conn = get_rabbit_connection()
    channel = rabbit_conn.channel()
    ensure_queues(channel)

    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=EVENT_QUEUE, on_message_callback=process_message)

    logger.info("Waiting for messages", extra={"queue": EVENT_QUEUE})
    channel.start_consuming()


if __name__ == "__main__":
    main() 