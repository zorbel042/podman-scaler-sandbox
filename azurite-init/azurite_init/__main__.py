import logging
import os
import sys
from pathlib import Path

from azure.storage.blob import BlobServiceClient  # type: ignore
from opentelemetry import trace  # type: ignore
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  # type: ignore
from opentelemetry.sdk.resources import SERVICE_NAME, Resource  # type: ignore
from opentelemetry.sdk.trace import TracerProvider  # type: ignore
from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore
from pythonjsonlogger import jsonlogger  # type: ignore

SERVICE_NAME_VALUE = os.getenv("OTEL_SERVICE_NAME", "azurite-init")

from otel_logging import init_logging  # isort: skip

logger, tracer = init_logging(SERVICE_NAME_VALUE)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
AZURITE_CONN_STR = os.getenv(
    "AZURITE_CONNECTION_STRING",
    "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://azurite:10000/devstoreaccount1;",
)
CONTAINERS = os.getenv("INIT_CONTAINERS", "incoming,processed").split(",")
SEED_SAMPLE = os.getenv("SEED_SAMPLE", "true").lower() == "true"
SAMPLE_FILE = os.getenv("SAMPLE_FILE", "sample.txt")

# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def main():
    logger.info("Initializing Azurite containers", extra={"containers": CONTAINERS})
    blob_service = BlobServiceClient.from_connection_string(AZURITE_CONN_STR)

    for name in CONTAINERS:
        name = name.strip()
        if not name:
            continue
        container_client = blob_service.get_container_client(name)
        try:
            container_client.create_container()
            logger.info("Created container", extra={"container": name})
        except Exception:
            logger.info("Container exists", extra={"container": name})

    if SEED_SAMPLE:
        with tracer.start_as_current_span("seed_sample"):
            incoming_client = blob_service.get_blob_client(container="incoming", blob="sample/" + SAMPLE_FILE)
            # Create sample content
            data = f"Hello – seeded at {os.getenv('INIT_TIMESTAMP', 'startup')}".encode()
            incoming_client.upload_blob(data, overwrite=True)
            logger.info("Uploaded sample blob", extra={"blob": incoming_client.blob_name})

    logger.info("Azurite initialization complete")


if __name__ == "__main__":
    main() 