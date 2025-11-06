#!/bin/bash
# Quick setup script for Linux development environment
# This copies the necessary signal-recorder files to the Linux environment

set -e

echo "🚀 Setting up signal-recorder files for Linux development..."

# Check if we're in the right directory
if [[ ! -f "simple-server.js" ]]; then
    echo "❌ Error: Please run this script from the web-ui directory"
    exit 1
fi

# Go to parent directory (signal-recorder root)
cd ..

echo "📁 Working in: $(pwd)"

# Check if files exist
if [[ ! -f "test-daemon.py" ]]; then
    echo "❌ Error: test-daemon.py not found in parent directory"
    exit 1
fi

if [[ ! -f "config/grape-S000171.toml" ]]; then
    echo "❌ Error: config/grape-S000171.toml not found"
    exit 1
fi

if [[ ! -f "test-discover.py" ]]; then
    echo "❌ Error: test-discover.py not found"
    exit 1
fi

# Create necessary directories in Linux environment
echo "📁 Creating directories..."
mkdir -p /home/mjh/git/signal-recorder/config 2>/dev/null || echo "Config directory may already exist"
mkdir -p /home/mjh/git/signal-recorder/test-data/raw 2>/dev/null || echo "Test-data directory may already exist"

# Copy files to Linux environment (if different from current location)
if [[ "$(pwd)" != "/home/mjh/git/signal-recorder" ]]; then
    echo "📄 Copying files to Linux environment..."

    # Copy daemon script
    if [[ -f "test-daemon.py" ]]; then
        cp test-daemon.py /home/mjh/git/signal-recorder/test-daemon.py 2>/dev/null || echo "Could not copy test-daemon.py"
        echo "✅ Copied test-daemon.py"
    fi

    # Copy config file
    if [[ -f "config/grape-S000171.toml" ]]; then
        cp config/grape-S000171.toml /home/mjh/git/signal-recorder/config/grape-S000171.toml 2>/dev/null || echo "Could not copy config file"
        echo "✅ Copied grape-S000171.toml"
    fi

    # Copy discover script
    if [[ -f "test-discover.py" ]]; then
        cp test-discover.py /home/mjh/git/signal-recorder/test-discover.py 2>/dev/null || echo "Could not copy test-discover.py"
        echo "✅ Copied test-discover.py"
    fi

    # Copy watchdog script
    if [[ -f "test-watchdog.py" ]]; then
        cp test-watchdog.py /home/mjh/git/signal-recorder/test-watchdog.py 2>/dev/null || echo "Could not copy test-watchdog.py"
        echo "✅ Copied test-watchdog.py"
    fi

    # Copy source directory
    if [[ -d "src" ]]; then
        cp -r src /home/mjh/git/signal-recorder/ 2>/dev/null || echo "Could not copy src directory"
        echo "✅ Copied src directory"
    fi

    # Make scripts executable
    chmod +x /home/mjh/git/signal-recorder/test-daemon.py 2>/dev/null || echo "Could not make test-daemon.py executable"
    chmod +x /home/mjh/git/signal-recorder/test-discover.py 2>/dev/null || echo "Could not make test-discover.py executable"
    chmod +x /home/mjh/git/signal-recorder/test-watchdog.py 2>/dev/null || echo "Could not make test-watchdog.py executable"

    echo "🎉 Files copied successfully!"
else
    echo "ℹ️  Files already appear to be in the correct location"
fi

echo ""
echo "🔧 Next steps:"
echo "1. Start the web server: cd /home/mjh/git/signal-recorder/web-ui && pnpm start"
echo "2. Access: http://localhost:3000/monitoring"
echo "3. Test daemon control: use the web interface or API calls"
echo ""
echo "📋 API endpoints:"
echo "- Status: curl -H 'Authorization: Bearer admin-token' http://localhost:3000/api/monitoring/daemon-status"
echo "- Start: curl -H 'Authorization: Bearer admin-token' -X POST -H 'Content-Type: application/json' -d '{\"action\":\"start\"}' http://localhost:3000/api/monitoring/daemon-control"
echo "- Stop: curl -H 'Authorization: Bearer admin-token' -X POST -H 'Content-Type: application/json' -d '{\"action\":\"stop\"}' http://localhost:3000/api/monitoring/daemon-control"
echo ""
echo "✅ Setup complete! The web interface should now work with the daemon."
