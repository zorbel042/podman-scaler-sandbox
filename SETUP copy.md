# Podman Scaler Sandbox - Setup Guide

This guide will help you set up the Podman Scaler Sandbox project on Ubuntu WSL (Windows Subsystem for Linux) from scratch.

## Prerequisites

- Windows 10/11 with WSL2 enabled
- Ubuntu WSL distribution installed
- Administrative privileges on Windows

## Table of Contents

1. [WSL2 Setup](#wsl2-setup)
2. [Ubuntu Package Updates](#ubuntu-package-updates)
3. [Podman Installation](#podman-installation)
4. [Podman Configuration](#podman-configuration)
5. [Python Setup](#python-setup)
6. [Project Setup](#project-setup)
7. [Running the Application](#running-the-application)
8. [Troubleshooting](#troubleshooting)
9. [Useful Commands](#useful-commands)

## WSL2 Setup

### 1. Enable WSL2 (if not already done)

Open PowerShell as Administrator and run:

```powershell
# Enable WSL feature
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart

# Enable Virtual Machine Platform
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart

# Restart your computer
shutdown /r /t 0
```

### 2. Set WSL2 as Default

After restart, open PowerShell as Administrator:

```powershell
wsl --set-default-version 2
```

### 3. Install Ubuntu

Install Ubuntu from Microsoft Store or run:

```powershell
wsl --install -d Ubuntu
```

## Ubuntu Package Updates

Open your Ubuntu WSL terminal and update the system:

```bash
# Update package lists
sudo apt update

# Upgrade existing packages
sudo apt upgrade -y

# Install essential build tools
sudo apt install -y \
    build-essential \
    curl \
    wget \
    git \
    ca-certificates \
    gnupg \
    lsb-release \
    software-properties-common
```

## Podman Installation

### 1. Install Podman

```bash
# Update package information
sudo apt update

# Install Podman
sudo apt install -y podman

# Verify installation
podman --version
```

### 2. Install podman-compose

```bash
# Install pip if not already installed
sudo apt install -y python3-pip

# Install podman-compose
pip3 install podman-compose

# Add ~/.local/bin to PATH if not already there
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

# Verify installation
podman-compose --version
```

## Podman Configuration

### 1. Configure Podman for Rootless Operation

```bash
# Enable lingering for your user (allows services to start without login)
sudo loginctl enable-linger $USER

# Create user systemd directory
mkdir -p ~/.config/systemd/user

# Start and enable podman socket
systemctl --user enable --now podman.socket

# Verify socket is running
systemctl --user status podman.socket
```

### 2. Configure Podman Remote API (for keda-test-scaler)

```bash
# Start Podman API service on port 8888
systemctl --user enable --now podman.service

# Create a systemd service for Podman API on specific port
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/podman-api.service << 'EOF'
[Unit]
Description=Podman API Service
Documentation=man:podman-system-service(1)
Wants=network-online.target
After=network-online.target
RequiresMountsFor=%t/containers

[Service]
Type=exec
KillMode=process
Environment=LOGGING="--log-level=info"
ExecStart=/usr/bin/podman system service --time=0 tcp://0.0.0.0:8888
ExecReload=/bin/kill -HUP $MAINPID
TimeoutStopSec=70
KillSignal=SIGINT

[Install]
WantedBy=default.target
EOF

# Reload systemd and start the service
systemctl --user daemon-reload
systemctl --user enable --now podman-api.service

# Verify the service is running
systemctl --user status podman-api.service
```

### 3. Configure Subuid/Subgid (if needed)

```bash
# Check if your user has subuid/subgid entries
grep "^$(whoami):" /etc/subuid /etc/subgid

# If no entries exist, add them (replace 'username' with your actual username)
if ! grep -q "^$(whoami):" /etc/subuid; then
    echo "$(whoami):100000:65536" | sudo tee -a /etc/subuid
fi

if ! grep -q "^$(whoami):" /etc/subgid; then
    echo "$(whoami):100000:65536" | sudo tee -a /etc/subgid
fi
```

### 4. Configure Container Networks

```bash
# Enable IP forwarding for containers
echo 'net.ipv4.ip_forward = 1' | sudo tee -a /etc/sysctl.conf
sudo sysctl -p

# Install additional networking tools
sudo apt install -y netavark aardvark-dns
```

## Python Setup

Install Python dependencies for the project:

```bash
# Install Python 3 and pip (if not already installed)
sudo apt install -y python3 python3-pip python3-venv

# Install additional Python tools
pip3 install --user \
    requests \
    pika \
    azure-storage-blob \
    tenacity

# Verify Python installation
python3 --version
pip3 --version
```

## Project Setup

### 1. Clone/Access the Project

If the project is in your Windows file system, access it via WSL:

```bash
# Navigate to your Windows project directory (example)
cd /mnt/c/Users/YourUsername/Projects/podman-scaler-sandbox

# Or clone if accessing from git
# git clone <repository-url>
# cd podman-scaler-sandbox
```

### 2. Set Proper Permissions

```bash
# Ensure files have proper permissions
chmod +x **/*.py
chmod 644 *.yaml *.md
```

### 3. Environment Verification

```bash
# Verify all components are working
podman info
podman-compose --version
python3 --version

# Test Podman connectivity
podman run --rm hello-world
```

## Running the Application

### 1. Start the Services

```bash
# Navigate to project directory
cd /path/to/podman-scaler-sandbox

# Build and start all services
podman-compose up --build -d

# Verify all containers are running
podman-compose ps
```

### 2. Check Service Health

```bash
# Check container status
podman ps

# Check logs for any issues
podman-compose logs

# Check specific service logs
podman-compose logs rabbitmq
podman-compose logs azurite
podman-compose logs keda-test-scaler
podman-compose logs blob-processor
podman-compose logs blob-based-event-handler
```

### 3. Test the System

```bash
# Check RabbitMQ Management UI (if needed)
curl -u ic-tester:ic-tester http://localhost:15672/api/overview

# Check Azurite blob storage
curl http://localhost:10000/devstoreaccount1/

# Monitor logs in real-time
podman-compose logs -f blob-processor
```

## Troubleshooting

### Common Issues and Solutions

#### 1. Podman Socket Issues

```bash
# Restart Podman socket
systemctl --user restart podman.socket
systemctl --user status podman.socket
```

#### 2. Permission Denied Errors

```bash
# Check user namespaces
podman unshare cat /proc/self/uid_map

# Reset Podman storage if needed (WARNING: removes all containers/images)
podman system reset --force
```

#### 3. Network Connectivity Issues

```bash
# Check if ports are available
sudo netstat -tlnp | grep -E ':(5672|8888|10000|15672)'

# Restart networking
sudo systemctl restart systemd-networkd
```

#### 4. Container Build Failures

```bash
# Clean up build cache
podman system prune -a -f

# Rebuild specific service
podman-compose build --no-cache <service-name>
```

#### 5. WSL2 Resource Issues

Add to `/etc/wsl.conf`:

```ini
[wsl2]
memory=4GB
processors=2
swap=2GB
```

Then restart WSL:

```powershell
# In Windows PowerShell
wsl --shutdown
wsl
```

### Debugging Commands

```bash
# Check Podman system information
podman info

# Check systemd services
systemctl --user status podman.socket
systemctl --user status podman-api.service

# Check container logs
podman logs <container-id>

# Execute commands in containers
podman exec -it <container-name> /bin/bash

# Check network connectivity
podman network ls
podman network inspect <network-name>
```

## Useful Commands

### Podman Management

```bash
# List all containers
podman ps -a

# List all images
podman images

# Remove all stopped containers
podman container prune

# Remove unused images
podman image prune

# System cleanup
podman system prune -a
```

### Service Management

```bash
# Start services
podman-compose up -d

# Stop services
podman-compose down

# Restart specific service
podman-compose restart <service-name>

# Scale services
podman-compose up --scale blob-processor=3

# View logs
podman-compose logs -f <service-name>
```

### Development Commands

```bash
# Build without cache
podman-compose build --no-cache

# Rebuild and restart
podman-compose down && podman-compose up --build -d

# Check service health
podman-compose ps

# Monitor resource usage
podman stats
```

## System Architecture

This project consists of:

- **RabbitMQ**: Message broker for event-driven communication
- **Azurite**: Local Azure Storage emulator for blob operations
- **keda-test-scaler**: Monitors queue depth and scales blob-processor instances
- **blob-based-event-handler**: Publishes events for blob files every minute
- **blob-processor**: Processes blob events and moves files to processed/ folder
- **azurite-init**: Initializes blob storage containers and queues

## Next Steps

1. Monitor the logs to ensure all services are working correctly
2. Test blob file processing by uploading files to the storage
3. Observe the scaling behavior as queue depth changes
4. Customize the configuration as needed for your use case

For more detailed information about the project functionality, see the main README.md file. 