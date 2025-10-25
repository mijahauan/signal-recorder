#!/bin/bash

# GRAPE Configuration UI - Service Setup Script
# Creates systemd service for auto-start on boot
# Run with: sudo bash setup-service.sh

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}GRAPE Configuration UI - Service Setup${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Error: This script must be run with sudo${NC}"
  echo "Run: sudo bash setup-service.sh"
  exit 1
fi

# Get the actual user (not root)
ACTUAL_USER=${SUDO_USER:-$USER}
ACTUAL_HOME=$(eval echo ~$ACTUAL_USER)

# Detect installation directory
INSTALL_DIR="$ACTUAL_HOME/signal-recorder/grape-config-ui"

if [ ! -d "$INSTALL_DIR" ]; then
  # Try alternative location
  INSTALL_DIR="$ACTUAL_HOME/grape-config-ui"
fi

if [ ! -d "$INSTALL_DIR" ]; then
  echo -e "${RED}Error: Cannot find installation directory${NC}"
  echo "Searched in:"
  echo "  - $ACTUAL_HOME/signal-recorder/grape-config-ui"
  echo "  - $ACTUAL_HOME/grape-config-ui"
  echo ""
  echo "Please specify the installation directory:"
  read -p "Path: " INSTALL_DIR
  
  if [ ! -d "$INSTALL_DIR" ]; then
    echo -e "${RED}Error: Directory does not exist: $INSTALL_DIR${NC}"
    exit 1
  fi
fi

echo -e "${GREEN}Found installation at: $INSTALL_DIR${NC}"
echo ""

# Find pnpm path
PNPM_PATH=$(which pnpm)
if [ -z "$PNPM_PATH" ]; then
  echo -e "${RED}Error: pnpm not found in PATH${NC}"
  exit 1
fi

echo "Creating systemd service file..."

# Create service file
cat > /etc/systemd/system/grape-config-ui.service <<EOF
[Unit]
Description=GRAPE Configuration UI
Documentation=https://github.com/mijahauan/signal-recorder
After=network.target mysql.service
Requires=mysql.service

[Service]
Type=simple
User=$ACTUAL_USER
WorkingDirectory=$INSTALL_DIR
Environment="NODE_ENV=production"
Environment="PATH=/usr/local/bin:/usr/bin:/bin"
ExecStart=$PNPM_PATH start
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=grape-config-ui

# Security settings
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$INSTALL_DIR

[Install]
WantedBy=multi-user.target
EOF

echo -e "${GREEN}Service file created${NC}"
echo ""

# Reload systemd
echo "Reloading systemd daemon..."
systemctl daemon-reload

# Enable service
echo "Enabling service to start on boot..."
systemctl enable grape-config-ui

# Start service
echo "Starting service..."
systemctl start grape-config-ui

# Wait a moment for service to start
sleep 2

# Check status
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Service Status${NC}"
echo -e "${GREEN}========================================${NC}"
systemctl status grape-config-ui --no-pager

echo ""
echo -e "${GREEN}Service setup complete!${NC}"
echo ""
echo "Useful commands:"
echo ""
echo "  Check status:    sudo systemctl status grape-config-ui"
echo "  Stop service:    sudo systemctl stop grape-config-ui"
echo "  Start service:   sudo systemctl start grape-config-ui"
echo "  Restart service: sudo systemctl restart grape-config-ui"
echo "  View logs:       sudo journalctl -u grape-config-ui -f"
echo "  Disable service: sudo systemctl disable grape-config-ui"
echo ""
echo "The service will now start automatically on system boot."
echo ""

