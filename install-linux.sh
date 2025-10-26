#!/bin/bash
# Signal Recorder Installation Script for Linux
# This script installs signal-recorder as a systemd service

set -e

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (sudo)"
   exit 1
fi

echo "🚀 Installing Signal Recorder as systemd service..."

# Create signal-recorder user
if ! id -u signal-recorder > /dev/null 2>&1; then
    useradd --system --shell /bin/false signal-recorder
    echo "✅ Created signal-recorder system user"
fi

# Create directories
mkdir -p /usr/local/bin
mkdir -p /usr/local/lib/signal-recorder/{src,web-ui}
mkdir -p /etc/signal-recorder
mkdir -p /var/lib/signal-recorder/test-data/raw
mkdir -p /var/log/signal-recorder

# Set ownership
chown -R signal-recorder:signal-recorder /usr/local/lib/signal-recorder
chown -R signal-recorder:signal-recorder /var/lib/signal-recorder
chown -R signal-recorder:signal-recorder /var/log/signal-recorder

# Copy daemon script and make executable
cp test-daemon.py /usr/local/bin/signal-recorder-daemon
chmod +x /usr/local/bin/signal-recorder-daemon

# Copy watchdog script and make executable
cp test-watchdog.py /usr/local/bin/signal-recorder-watchdog
chmod +x /usr/local/bin/signal-recorder-watchdog

# Copy web server (we'll create a simple launcher script)
cat > /usr/local/bin/signal-recorder-web << EOF
#!/bin/bash
cd /usr/local/lib/signal-recorder/web-ui
exec node simple-server.js "\$@"
EOF
chmod +x /usr/local/bin/signal-recorder-web

# Copy config file
cp config/grape-S000171.toml /etc/signal-recorder/config.toml

# Copy web UI files
cp -r web-ui/* /usr/local/lib/signal-recorder/web-ui/

# Copy source files
cp -r src/* /usr/local/lib/signal-recorder/src/

# Set ownership of installed files
chown -R signal-recorder:signal-recorder /usr/local/bin/signal-recorder-*
chown -R signal-recorder:signal-recorder /usr/local/lib/signal-recorder
chown -R signal-recorder:signal-recorder /etc/signal-recorder

# Install systemd services
cp signal-recorder-daemon.service /etc/systemd/system/
cp signal-recorder-web.service /etc/systemd/system/

# Reload systemd
systemctl daemon-reload

# Enable services (but don't start yet)
systemctl enable signal-recorder-daemon
systemctl enable signal-recorder-web

echo "✅ Installation completed!"
echo ""
echo "📋 Next steps:"
echo "1. Start the daemon: sudo systemctl start signal-recorder-daemon"
echo "2. Start the web UI: sudo systemctl start signal-recorder-web"
echo "3. Check status: sudo systemctl status signal-recorder-daemon"
echo "4. Access web UI: http://localhost:3000/monitoring"
echo ""
echo "🔧 Management commands:"
echo "- Start: sudo systemctl start signal-recorder-daemon"
echo "- Stop: sudo systemctl stop signal-recorder-daemon"
echo "- Restart: sudo systemctl restart signal-recorder-daemon"
echo "- Logs: sudo journalctl -f -u signal-recorder-daemon"
echo ""
echo "🛠️  Configuration:"
echo "- Config file: /etc/signal-recorder/config.toml"
echo "- Data directory: /var/lib/signal-recorder/test-data/"
echo "- Log files: /var/log/signal-recorder/"
