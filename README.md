# Podman-Scaler Sandbox

This repo contains a sandbox stack that demonstrates:

* Azure Blob event polling ➝ RabbitMQ fan-out (`BlobBasedEventHandler`)
* RabbitMQ-driven blob processing workers (`BlobProcessor`)
* A simulated **KEDA** scaler that uses the Podman socket to autoscale processors (`KedaTestScaler`)
* Local Azurite storage + initialization helper (`azurite-init`)
* End-to-end integration tests powered by **pytest**

---

## 1  Prerequisites (macOS 12+)

1. **Xcode Command-line tools**  
   ```bash
   xcode-select --install
   ```
2. **Homebrew** (skip if installed)  
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```
3. **Podman 4 +**  
   ```bash
   brew install podman
   podman machine init --now  # starts the Lima VM
   ```
4. **Podman-Compose**  
   ```bash
   brew install podman-compose
   # or: pipx install podman-compose
   ```
5. **Python 3.12** (e.g. via [pyenv](https://github.com/pyenv/pyenv))

---

## 2  Bootstrap the Stack

```bash
# 1. Clone & cd
$ git clone https://github.com/your-org/podman-scaler-sandbox.git
$ cd podman-scaler-sandbox

# 2. Build all service images (first run only)
$ podman-compose build

# 3. Launch the stack (detached)
$ podman-compose up -d

# 4. Verify health
$ podman ps
# All containers should be "running" and healthy.
```

If you ever need to tear everything down:
```bash
podman-compose down -v  # removes volumes & networks
```

---

## 3  Run the Integration Tests

1. Create a Python virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
2. Install test requirements:
   ```bash
   pip install -r tests/requirements.txt
   ```
3. Execute **pytest** (this will interact with the live stack):
   ```bash
   pytest -m integration tests/
   ```
   The test will:
   * Upload a unique blob to Azurite `incoming/`
   * Wait until it is moved to `processed/…` by the processors
   * Confirm RabbitMQ queue is empty
   * Ensure the scaler never exceeds the configured replica limit

Typical runtime: ~2–3 minutes on a laptop.

> ℹ️  The test assumes the compose stack is already **running**.  If not, start it with `podman-compose up -d` first.

---

## 4  Troubleshooting

* **Podman socket permissions** – The scaler expects the Docker-compatible socket at `/run/user/$(id -u)/podman/podman.sock`.  If you hit permission errors, ensure your user owns that path and the volume mount in `podman-compose.yaml` matches.
* **RabbitMQ management API** – Accessible at [`http://localhost:15672`](http://localhost:15672) (user/pass `ic-tester`).
* **Azurite explorer** – Browse blobs at [`http://localhost:10000/devstoreaccount1`](http://localhost:10000/devstoreaccount1) with the connection string printed in `podman-compose logs azurite`.

---

## 5  Next Steps

* Adjust `MAX_REPLICAS` or polling intervals via environment variables in the compose file.
* Point OpenTelemetry exporter (`OTLP_ENDPOINT`) to your collector for full tracing.
* Extend `tests/test_integration.py` with failure-path assertions or performance checks.
