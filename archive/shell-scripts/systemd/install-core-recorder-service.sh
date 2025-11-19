#!/bin/bash
# Install GRAPE Core Recorder as systemd service
# Run this once to set up persistent core recorder

set -e

SERVICE_FILE="systemd/grape-core-recorder.service"
SERVICE_NAME="grape-core-recorder"

echo "🚀 Installing GRAPE Core Recorder as systemd service"
echo "===================================================="
echo ""

# Check if service file exists
if [ ! -f "$SERVICE_FILE" ]; then
    echo "❌ Service file not found: $SERVICE_FILE"
    exit 1
fi

# Check if running as root (needed for systemctl --system)
if [ "$EUID" -ne 0 ]; then
    echo "⚠️  This script needs sudo to install system service"
    echo ""
    echo "Installing for current user (no sudo required)..."
    
    # User service installation (survives logout but not reboot)
    USER_SERVICE_DIR="$HOME/.config/systemd/user"
    mkdir -p "$USER_SERVICE_DIR"
    
    cp "$SERVICE_FILE" "$USER_SERVICE_DIR/"
    
    systemctl --user daemon-reload
    systemctl --user enable "$SERVICE_NAME"
    
    echo ""
    echo "✅ Service installed (user mode)"
    echo ""
    echo "To start:"
    echo "  systemctl --user start $SERVICE_NAME"
    echo ""
    echo "To check status:"
    echo "  systemctl --user status $SERVICE_NAME"
    echo ""
    echo "To view logs:"
    echo "  journalctl --user -u $SERVICE_NAME -f"
    echo ""
    echo "To stop:"
    echo "  systemctl --user stop $SERVICE_NAME"
    echo ""
    echo "⚠️  Note: User services stop at logout. For persistent service,"
    echo "    run: 'sudo ./install-core-recorder-service.sh'"
    
else
    # System service installation (survives reboot)
    SYSTEM_SERVICE_DIR="/etc/systemd/system"
    
    cp "$SERVICE_FILE" "$SYSTEM_SERVICE_DIR/"
    
    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"
    
    echo ""
    echo "✅ Service installed (system mode - persistent)"
    echo ""
    echo "To start:"
    echo "  sudo systemctl start $SERVICE_NAME"
    echo ""
    echo "To check status:"
    echo "  sudo systemctl status $SERVICE_NAME"
    echo ""
    echo "To view logs:"
    echo "  sudo journalctl -u $SERVICE_NAME -f"
    echo ""
    echo "To stop:"
    echo "  sudo systemctl stop $SERVICE_NAME"
fi

echo ""
echo "Analytics services can still be started/stopped independently:"
echo "  ./start-dual-service.sh"
