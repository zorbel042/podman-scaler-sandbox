# CMS Admin – Blob Processing Demo

## 1. Overview
This document captures the high-level design and implementation plan for the demo stack that ingests Azure Blob Storage events, enqueues them in RabbitMQ, processes every blob, and dynamically scales processing containers using Podman.

Services:
1. **Azurite** – Local Azure Storage emulator (pre-built image).
2. **azurite-init** – One-shot container that seeds blob containers & optional demo data.
3. **rabbitmq (management)** – Message broker for fan-out & scaling metrics.
4. **BlobBasedEventHandler** – Python 3.12 microservice polling Azurite every minute for new blobs; publishes an event per new blob.
5. **BlobProcessor** – Python 3.12 worker that moves blobs to a `processed/` folder; one replica per message (max 10).
6. **KedaTestScaler** – Simulated KEDA scaler watching RabbitMQ queue length and creating/destroying `blob-processor` containers through the Podman socket.

---

## 2. Message Schema (RabbitMQ)
Messages are JSON objects with the following fields:
```json
{
  "container": "incoming",          // Blob container name
  "path": "2024/07/15/",            // Virtual directory (optional)
  "blob": "invoice.pdf",            // Actual blob name
  "dest": "processed/{uuid}-invoice.pdf", // Pre-computed destination
  "timestamp": "2025-07-15T12:00:00Z"     // ISO-8601 for traceability
}
```
Additional headers:
* `trace_id` – OpenTelemetry trace identifier
* `retries`  – current retry count (added by processor)

Dead-letter queue (`blob.error`) copies the original message plus `error` and `stacktrace` fields.

---

## 3. Scaling Strategy
* **Metric** – Queue length (`messages_ready`) from RabbitMQ management API.
* **Algorithm** – `replicas = min(queue_length, 10)`; when queue is empty, scale back to 1.
* **Frequency** – Evaluate every 30 seconds.
* **Provisioning** – Interact with Podman via Docker-compatible socket at `/var/run/docker.sock` (rootless user), using the Python `docker` SDK.

---

## 4. Error Handling
1. **Retry** – Processor retries failed moves up to **3** times with exponential back-off (1 s, 2 s, 4 s).
2. **Dead-Letter** – After retries, message is published to `blob.error`.
3. **Alerting** – Error queue length is logged; hook for external alerting (e.g., Prometheus → Alertmanager).

---

## 5. Logging & Observability
* **OpenTelemetry** for traces and structured JSON logs (stdout).
* Unified logger configuration shared by all Python services.
* Context propagation: Event handler injects trace context into each RabbitMQ message header.

---

## 6. Security Considerations
* Podman socket exposure allows container lifecycle control; restrict to non-root UID, consider read-only volume or REST API + limited scope.
* No secrets persisted in images; Azurite connection string and RabbitMQ creds passed via environment variables / `.env` file during development.

---

## 7. Testing Plan
1. **Pytest** integration suite spins up full compose stack.
2. Upload sample blob to `incoming/` → verify:  
   a. Event handler emits message  
   b. Scaler scales processors (≤ 10)  
   c. Blob moved to `processed/` path  
   d. Processor containers scale back down.

---

## 8. Roadmap / Next Steps
* Implement services (see TODO.md).  
* Add Containerfiles.  
* Configure CI job to run integration tests. 