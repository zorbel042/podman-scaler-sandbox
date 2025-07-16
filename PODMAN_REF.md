# Podman Scaler Sandbox - Setup Guide

Quick setup guide for Ubuntu WSL environments. Most configuration is automated via the setup script.

## Prerequisites

- **WSL2** with Ubuntu distribution installed and running
- **Administrative privileges** on Windows for initial setup steps

## Quick Setup (Recommended)

### 1. Run the Automated Setup Script

```bash
# Navigate to project directory
cd /path/to/podman-scaler-sandbox

# Make the setup script executable and run it
chmod +x setup-automated.sh
./setup-automated.sh
```

The script will automatically:
- Install Podman and podman-compose
- Configure rootless Podman operation  
- Set up Podman API service on port 8888 (required for keda-test-scaler)
- Install Python dependencies
- Configure container networking
- Verify the complete setup

### 2. Start the Application

After successful setup:

```bash
# Build and start all services
podman-compose up --build -d

# Verify all containers are healthy
podman-compose ps
```

## Manual Setup (If Automation Fails)

### Essential Requirements

Only these components are truly required for the project to function:

#### 1. Podman Installation
```bash
sudo apt update
sudo apt install -y podman
```

#### 2. podman-compose Installation  
```bash
pip3 install --user podman-compose
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

#### 3. Podman API Service (CRITICAL)
The keda-test-scaler requires the Podman API to be accessible on port 8888:

```bash
# Create systemd service for Podman API
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/podman-api.service << 'EOF'
[Unit]
Description=Podman API Service
After=network-online.target

[Service]
Type=exec
ExecStart=/usr/bin/podman system service --time=0 tcp://0.0.0.0:8888
KillSignal=SIGINT

[Install]
WantedBy=default.target
EOF

# Enable and start the service
systemctl --user daemon-reload
systemctl --user enable --now podman-api.service
```

#### 4. Basic Python Dependencies
```bash
pip3 install --user requests pika azure-storage-blob tenacity
```

#### 5. Network Configuration
```bash
# Enable IP forwarding for containers
echo 'net.ipv4.ip_forward = 1' | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

## Verification

Test that everything works:

```bash
# Test Podman
podman run --rm hello-world

# Test Podman API (should return version info)
curl http://localhost:8888/version

# Test podman-compose
podman-compose --version
```

## Running the Application

```bash
# Start services (builds images on first run)
podman-compose up --build -d

# Check status
podman-compose ps

# View logs
podman-compose logs -f
```

## Architecture Overview

- **RabbitMQ**: Message broker (ports 5672, 15672)
- **Azurite**: Local Azure Storage emulator (port 10000)
- **keda-test-scaler**: Monitors queue and scales blob-processor instances via Podman API
- **blob-based-event-handler**: Publishes blob events every minute
- **blob-processor**: Processes blob events and moves files
- **azurite-init**: Initializes storage containers

## Troubleshooting

### Common Issues

**Podman API not accessible:**
```bash
systemctl --user restart podman-api.service
systemctl --user status podman-api.service
```

**Permission errors:**
```bash
# Check subuid/subgid
grep "^$(whoami):" /etc/subuid /etc/subgid

# Add if missing
echo "$(whoami):100000:65536" | sudo tee -a /etc/subuid /etc/subgid
```

**Container networking issues:**
```bash
# Verify networking tools
sudo apt install -y netavark aardvark-dns

# Check IP forwarding
cat /proc/sys/net/ipv4/ip_forward  # Should output: 1
```

**Services not starting:**
```bash
# Check logs
podman-compose logs <service-name>

# Restart specific service
podman-compose restart <service-name>
```

## Service Access

- **RabbitMQ Management**: http://localhost:15672 (ic-tester / ic-tester)
- **Azurite Storage**: http://localhost:10000/devstoreaccount1
- **Podman API**: http://localhost:8888/version

For detailed troubleshooting and development commands, see the original comprehensive SETUP.md or check the project logs. 