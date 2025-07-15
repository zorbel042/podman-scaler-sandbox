import os
import time
import uuid

import docker  # type: ignore
import pytest  # type: ignore
import requests
from azure.storage.blob import BlobServiceClient  # type: ignore

AZURITE_CONN_STR = os.getenv(
    "AZURITE_CONNECTION_STRING",
    "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://localhost:10000/devstoreaccount1;",
)
RABBITMQ_API = os.getenv("RABBITMQ_API", "http://localhost:15672/api/queues/%2F/blob.events")
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "ic-tester")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "ic-tester")
MAX_REPLICAS = int(os.getenv("MAX_REPLICAS", "10"))


def wait_for(condition_fn, timeout: int = 120, interval: float = 2.0):
    start = time.time()
    while time.time() - start < timeout:
        if condition_fn():
            return True
        time.sleep(interval)
    return False


@pytest.mark.integration
def test_blob_processing_flow():
    blob_service = BlobServiceClient.from_connection_string(AZURITE_CONN_STR)

    # upload unique blob
    orig_name = f"{uuid.uuid4()}.txt"
    blob_path = f"e2e/{orig_name}"
    blob_client = blob_service.get_blob_client(container="incoming", blob=blob_path)
    blob_client.upload_blob(b"hello", overwrite=True)

    # helper to check processed blob presence
    def processed_exists():
        container_client = blob_service.get_container_client("incoming")
        for blob in container_client.list_blobs(name_starts_with="processed/"):
            if blob.name.endswith(orig_name):
                return True
        return False

    assert wait_for(processed_exists), "Processed blob not found within timeout"

    # ensure queue drained
    def queue_empty():
        resp = requests.get(RABBITMQ_API, auth=(RABBITMQ_USER, RABBITMQ_PASS), timeout=5)
        resp.raise_for_status()
        return resp.json().get("messages", 0) == 0

    assert wait_for(queue_empty), "RabbitMQ queue not drained"

    # ensure scaler stayed within limits
    docker_client = docker.DockerClient(base_url="unix:///var/run/docker.sock")
    processors = docker_client.containers.list(filters={"label": ["managed-by=keda-test-scaler", "role=blob_processor"]})
    assert len(processors) <= MAX_REPLICAS, "Scaler exceeded max replicas" 