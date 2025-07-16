import json
import logging
import os
import sys
import threading
import time
import uuid
from datetime import datetime
from typing import Optional

logger = None

try:
    # Initialize basic logging first
    logger = logging.getLogger("BlobProcessor")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stdout)
        
        class SimpleFormatter(logging.Formatter):
            def format(self, record):
                return json.dumps({
                    "asctime": datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S,%f')[:-3],
                    "levelname": record.levelname,
                    "name": record.name,
                    "message": record.getMessage(),
                    "taskName": None
                })
        
        handler.setFormatter(SimpleFormatter())
        logger.addHandler(handler)
    
    logger.info("=== STARTING BLOB PROCESSOR DEBUG ===")
    logger.info("Basic imports successful")
    
    # Try pika import
    logger.info("Importing pika...")
    import pika
    logger.info("Pika import successful")
    
    # Try tenacity import
    logger.info("Importing tenacity...")
    from tenacity import retry, stop_after_attempt, wait_exponential, RetryError
    logger.info("Tenacity import successful")
    
    # Try Azure imports - this is likely where the KeyError happens
    logger.info("Importing Azure Storage SDK...")
    from azure.storage.blob import BlobServiceClient, ContainerClient
    logger.info("Azure Storage SDK import successful!")
    
    # Try otel_logging import
    logger.info("Importing otel_logging...")
    from otel_logging import init_logging
    logger.info("otel_logging import successful")
    
    logger.info("All imports completed successfully")
    
except Exception as import_err:
    if logger:
        logger.error("IMPORT FAILED", extra={"error": str(import_err), "error_type": type(import_err).__name__})
    else:
        print(f"CRITICAL: Import failed before logger setup: {import_err}")
    raise


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

logger.info("Initializing Azure Storage SDK", extra={"connection_string_prefix": AZURITE_CONN_STR[:50] + "...", "container_name": CONTAINER_NAME})

try:
    blob_service = BlobServiceClient.from_connection_string(AZURITE_CONN_STR)
    logger.info("BlobServiceClient created successfully")
    
    container_client: ContainerClient = blob_service.get_container_client(CONTAINER_NAME)
    logger.info("ContainerClient created successfully", extra={"container_name": CONTAINER_NAME})
    
    # Test the connection
    logger.info("Testing container client connection...")
    try:
        # This will attempt to connect and may reveal the KeyError
        container_properties = container_client.get_container_properties()
        logger.info("Container connection test successful", extra={"properties": str(container_properties)[:100]})
    except Exception as test_err:
        logger.error("Container connection test failed", extra={"error": str(test_err), "error_type": type(test_err).__name__})
        # Don't raise here, let it continue for now
        
except Exception as init_err:
    logger.error("Azure SDK initialization failed", extra={"error": str(init_err), "error_type": type(init_err).__name__})
    # Set to None so we can detect this later
    blob_service = None
    container_client = None


# ---------------------------------------------------------------------------
# Blob processing functions
# ---------------------------------------------------------------------------

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4))
def move_blob(src_blob: str, dest_blob: str):
    """Move a blob from source to destination path with retry logic."""
    try:
        logger.info("Starting blob move operation", extra={"src": src_blob, "dest": dest_blob})
        
        # Check if container_client is properly initialized
        if not container_client:
            raise ValueError("Container client not initialized")
        
        logger.info("Getting blob clients for source and destination")
        src_client = container_client.get_blob_client(src_blob)
        dest_client = container_client.get_blob_client(dest_blob)
        
        logger.info("Blob clients created", extra={"src_url": src_client.url})

        # Start copy operation
        logger.info("Starting blob copy operation")
        try:
            copy_info = dest_client.start_copy_from_url(src_client.url)
            logger.info("Copy operation initiated", extra={"copy_id": copy_info.get("copy_id")})
            
            # Wait for copy to complete (for small files this should be instant)
            copy_status = dest_client.get_blob_properties().copy.status
            logger.info("Copy operation completed", extra={"copy_status": copy_status})
            
            if copy_status == "success":
                # Delete the source blob after successful copy
                logger.info("Deleting source blob after successful copy")
                src_client.delete_blob()
                logger.info("Blob move completed successfully", extra={"src": src_blob, "dest": dest_blob})
            else:
                raise Exception(f"Copy operation failed with status: {copy_status}")
                
        except Exception as copy_err:
            logger.error("Copy operation failed", extra={"error": str(copy_err), "error_type": type(copy_err).__name__})
            raise
            
    except Exception as move_err:
        logger.error("Blob move operation failed", extra={"src": src_blob, "dest": dest_blob, "error": str(move_err), "error_type": type(move_err).__name__})
        raise


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8))
def periodic_health_check():
    """Periodic health check to verify system components."""
    logger.info("Running periodic health check")
    
    try:
        # Check container client
        if container_client is None:
            raise ValueError("Container client is None")
            
        # Test blob operations
        logger.info("Testing blob list operation")
        blobs = list(container_client.list_blobs(name_starts_with="test-"))
        logger.info("Health check: blob list successful", extra={"blob_count": len(blobs)})

        # Test blob client creation
        logger.info("Testing blob client creation")
        test_blob_client = container_client.get_blob_client("health-check-test.txt")
        logger.info("Health check: blob client creation successful")
        
        return True
        
    except Exception as health_err:
        error_msg = f"Health check failed: {type(health_err).__name__}: {str(health_err)}"
        logger.error(error_msg)
        logger.error(f"Health check error details - Type: {type(health_err)}, Args: {health_err.args}")
        raise


# ---------------------------------------------------------------------------
# Rabbit utilities
# ---------------------------------------------------------------------------

@retry(stop=stop_after_attempt(10), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_rabbit_connection():
    logger.info("Attempting to connect to RabbitMQ", extra={"host": RABBITMQ_HOST, "port": RABBITMQ_PORT})
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
    logger.info("=== RECEIVED MESSAGE ===", extra={"body_type": type(body).__name__, "body_length": len(body) if body else 0})
    
    try:
        logger.info("Raw message body", extra={"raw_body": body.decode() if body else "empty"})
        
        msg = json.loads(body)
        logger.info("Parsed JSON message", extra={"parsed_message": msg})
        
        # Validate required message fields
        required_keys = ["path", "blob", "dest"]
        missing_keys = [key for key in required_keys if key not in msg]
        if missing_keys:
            raise KeyError(f"Missing required keys: {missing_keys}")
        
        # Build source and destination blob paths
        src_blob = os.path.join(msg["path"], msg["blob"]) if msg["path"] else msg["blob"]
        
        # Create processed path - move files to "processed/" folder
        if src_blob.startswith("sample/"):
            # Move from sample/ to processed/sample/
            dest_blob = src_blob.replace("sample/", "processed/sample/", 1)
        else:
            # For other paths, add processed/ prefix
            dest_blob = f"processed/{src_blob}"
        
        logger.info("Processing blob movement", extra={
            "src_blob": src_blob, 
            "dest_blob": dest_blob,
            "container": msg.get("container", "unknown")
        })
        
        # Perform the blob move operation
        move_blob(src_blob, dest_blob)
        
        logger.info("Blob processing completed successfully", extra={
            "src_blob": src_blob,
            "dest_blob": dest_blob
        })
        
        # Acknowledge the message only after successful processing
        ch.basic_ack(delivery_tag=method.delivery_tag)
        
    except json.JSONDecodeError as json_err:
        error_msg = f"JSON decode error: {str(json_err)}"
        logger.error(error_msg)
        publish_error(ch, ERROR_QUEUE, json_err, {"raw_body": body.decode() if body else "empty"})
        ch.basic_ack(delivery_tag=method.delivery_tag)  # Ack to avoid reprocessing bad JSON
        
    except KeyError as key_err:
        error_msg = f"Missing required message fields: {str(key_err)}"
        logger.error(error_msg)
        publish_error(ch, ERROR_QUEUE, key_err, msg if 'msg' in locals() else {})
        ch.basic_ack(delivery_tag=method.delivery_tag)  # Ack to avoid reprocessing bad messages
        
    except Exception as exc:
        error_msg = f"Exception in process_message: {type(exc).__name__}: {str(exc)}"
        logger.error(error_msg)
        logger.error(f"Exception details - Type: {type(exc)}, Args: {exc.args}")
        if hasattr(exc, '__traceback__'):
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
        
        # Publish error and decide whether to acknowledge or reject
        publish_error(ch, ERROR_QUEUE, exc, msg if 'msg' in locals() else {})
        
        # For transient errors, we might want to retry, but for now, acknowledge to prevent infinite loops
        ch.basic_ack(delivery_tag=method.delivery_tag)


def publish_error(channel, error_queue: str, error: Exception, failed_message: dict):
    """Publish error information to error queue."""
    try:
        logger.info("Publishing error to error queue", extra={"queue": error_queue, "error_type": type(error).__name__})
        
        error_msg = {
            "error": str(error),
            "error_type": type(error).__name__,
            "failed_message": failed_message,
            "failed_at": datetime.now(datetime.UTC).isoformat(),
            "processor_id": str(uuid.uuid4())
        }
        
        channel.basic_publish(
            exchange="",
            routing_key=error_queue,
            body=json.dumps(error_msg),
            properties=pika.BasicProperties(delivery_mode=2)  # persistent
        )
        logger.info("Error published to queue successfully")
        
    except Exception as pub_err:
        logger.error("Failed to publish error to queue", extra={"error": str(pub_err)})


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def run_periodic_health_checks():
    """Background thread to run periodic health checks"""
    logger.info("Starting periodic health check thread")
    
    while True:
        try:
            time.sleep(30)  # Run every 30 seconds to match the timing we see
            logger.info("Triggering scheduled health check")
            periodic_health_check()
            logger.info("Scheduled health check completed successfully")
        except Exception as health_thread_err:
            logger.error("Health check thread error", extra={"error": str(health_thread_err), "error_type": type(health_thread_err).__name__})
            # Continue running even if health check fails


def main():
    logger.info("Starting BlobProcessor", extra={"event": "startup"})

    rabbit_conn = get_rabbit_connection()
    channel = rabbit_conn.channel()
    ensure_queues(channel)

    # Start background health check thread
    logger.info("Starting background health check thread")
    health_thread = threading.Thread(target=run_periodic_health_checks, daemon=True)
    health_thread.start()

    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=EVENT_QUEUE, on_message_callback=process_message)

    logger.info("Waiting for messages", extra={"queue": EVENT_QUEUE})
    channel.start_consuming()


if __name__ == "__main__":
    main() 