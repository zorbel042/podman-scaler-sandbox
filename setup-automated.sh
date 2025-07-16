#!/bin/bash

# Podman Scaler Sandbox - Automated Setup Script
# This script automates the essential setup for the project on Ubuntu WSL
# Prerequisites: WSL2 with Ubuntu installed, Podman NOT yet installed

set -e  # Exit on any error

echo "🚀 Starting automated setup for Podman Scaler Sandbox..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running in WSL
check_wsl() {
    if ! grep -q Microsoft /proc/version; then
        print_error "This script is designed for WSL2 Ubuntu. Please run in WSL environment."
        exit 1
    fi
    print_status "Running in WSL environment ✓"
}

# Update system packages
update_system() {
    print_status "Updating system packages..."
    sudo apt update
    sudo apt upgrade -y
    
    print_status "Installing essential packages..."
    sudo apt install -y \
        curl \
        wget \
        git \
        python3 \
        python3-pip \
        netcat-openbsd \
        ca-certificates
}

# Install Podman
install_podman() {
    print_status "Installing Podman..."
    sudo apt install -y podman
    
    # Verify installation
    if ! command -v podman &> /dev/null; then
        print_error "Podman installation failed"
        exit 1
    fi
    print_status "Podman installed successfully: $(podman --version)"
}

# Install podman-compose
install_podman_compose() {
    print_status "Installing podman-compose..."
    pip3 install --user podman-compose
    
    # Add to PATH if not already there
    if ! echo "$PATH" | grep -q "$HOME/.local/bin"; then
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
        export PATH="$HOME/.local/bin:$PATH"
    fi
    
    # Verify installation
    if ! command -v podman-compose &> /dev/null; then
        print_error "podman-compose installation failed"
        exit 1
    fi
    print_status "podman-compose installed successfully"
}

# Configure Podman for rootless operation
configure_podman_rootless() {
    print_status "Configuring Podman for rootless operation..."
    
    # Enable lingering for user
    sudo loginctl enable-linger $USER
    
    # Create systemd user directory
    mkdir -p ~/.config/systemd/user
    
    # Configure subuid/subgid if needed
    if ! grep -q "^$(whoami):" /etc/subuid; then
        print_status "Adding subuid entry..."
        echo "$(whoami):100000:65536" | sudo tee -a /etc/subuid
    fi
    
    if ! grep -q "^$(whoami):" /etc/subgid; then
        print_status "Adding subgid entry..."
        echo "$(whoami):100000:65536" | sudo tee -a /etc/subgid
    fi
    
    # Enable IP forwarding for containers
    if ! grep -q "net.ipv4.ip_forward = 1" /etc/sysctl.conf; then
        echo 'net.ipv4.ip_forward = 1' | sudo tee -a /etc/sysctl.conf
        sudo sysctl -p
    fi
    
    # Install networking tools
    sudo apt install -y netavark aardvark-dns
}

# Setup Podman API service (CRITICAL for keda-test-scaler)
setup_podman_api() {
    print_status "Setting up Podman API service on port 8888..."
    
    # Create systemd service file for Podman API
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

    # Reload systemd and start services
    systemctl --user daemon-reload
    systemctl --user enable --now podman.socket
    systemctl --user enable --now podman-api.service
    
    # Wait a moment for services to start
    sleep 3
    
    # Verify services are running
    if ! systemctl --user is-active --quiet podman.socket; then
        print_error "Podman socket failed to start"
        exit 1
    fi
    
    if ! systemctl --user is-active --quiet podman-api.service; then
        print_error "Podman API service failed to start"
        exit 1
    fi
    
    print_status "Podman services started successfully ✓"
}

# Test Podman functionality
test_podman() {
    print_status "Testing Podman functionality..."
    
    # Test basic podman command
    if ! podman run --rm hello-world >/dev/null 2>&1; then
        print_error "Basic Podman test failed"
        exit 1
    fi
    
    # Test API connectivity
    if ! curl -s http://localhost:8888/version >/dev/null; then
        print_error "Podman API not accessible on port 8888"
        exit 1
    fi
    
    print_status "Podman functionality verified ✓"
}

# Install Python dependencies
install_python_deps() {
    print_status "Installing Python dependencies..."
    
    # Install commonly needed packages for the project
    pip3 install --user \
        requests \
        pika \
        azure-storage-blob \
        tenacity \
        pythonjsonlogger \
        opentelemetry-api \
        opentelemetry-sdk \
        opentelemetry-exporter-otlp-proto-grpc
}

# Setup project environment
setup_project() {
    print_status "Setting up project environment..."
    
    # Ensure proper permissions for project files
    if [ -f "podman-compose.yaml" ]; then
        chmod 644 *.yaml *.md 2>/dev/null || true
        find . -name "*.py" -exec chmod +x {} \; 2>/dev/null || true
        print_status "Project file permissions set ✓"
    else
        print_warning "podman-compose.yaml not found in current directory"
        print_warning "Make sure you're running this script from the project root"
    fi
}

# Verify setup
verify_setup() {
    print_status "Verifying complete setup..."
    
    local errors=0
    
    # Check Podman
    if ! command -v podman &> /dev/null; then
        print_error "Podman not found in PATH"
        ((errors++))
    fi
    
    # Check podman-compose
    if ! command -v podman-compose &> /dev/null; then
        print_error "podman-compose not found in PATH"
        ((errors++))
    fi
    
    # Check Podman API
    if ! curl -s http://localhost:8888/version >/dev/null; then
        print_error "Podman API not responding on port 8888"
        ((errors++))
    fi
    
    # Check Python
    if ! python3 -c "import requests, pika, azure.storage.blob" 2>/dev/null; then
        print_error "Required Python packages not available"
        ((errors++))
    fi
    
    if [ $errors -eq 0 ]; then
        print_status "✅ Setup verification successful!"
        return 0
    else
        print_error "❌ Setup verification failed with $errors errors"
        return 1
    fi
}

# Main execution flow
main() {
    echo "================================================="
    echo "  Podman Scaler Sandbox - Automated Setup"
    echo "================================================="
    echo
    
    check_wsl
    update_system
    install_podman
    install_podman_compose
    configure_podman_rootless
    setup_podman_api
    test_podman
    install_python_deps
    setup_project
    
    echo
    echo "================================================="
    
    if verify_setup; then
        echo
        print_status "🎉 Setup completed successfully!"
        echo
        echo "Next steps:"
        echo "1. Build and start the services:"
        echo "   podman-compose up --build -d"
        echo
        echo "2. Check service status:"
        echo "   podman-compose ps"
        echo
        echo "3. View logs:"
        echo "   podman-compose logs -f"
        echo
        echo "4. Access RabbitMQ Management UI:"
        echo "   http://localhost:15672 (user: ic-tester, pass: ic-tester)"
        echo
    else
        print_error "Setup failed. Please check the errors above."
        exit 1
    fi
}

# Run main function
main "$@" 