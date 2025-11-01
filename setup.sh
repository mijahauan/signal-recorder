#!/bin/bash
# Quick setup script for GRAPE Signal Recorder

set -e  # Exit on error

echo "🚀 GRAPE Signal Recorder Setup"
echo "================================"
echo ""

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | grep -oP '\d+\.\d+')
REQUIRED_VERSION="3.9"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then 
    echo "❌ Python 3.9+ required. Found: Python $PYTHON_VERSION"
    exit 1
fi
echo "✅ Python $PYTHON_VERSION found"

# Check Node.js version
if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version | grep -oP '\d+' | head -1)
    if [ "$NODE_VERSION" -ge 18 ]; then
        echo "✅ Node.js $(node --version) found"
    else
        echo "⚠️  Node.js 18+ recommended. Found: v$(node --version)"
    fi
else
    echo "⚠️  Node.js not found. Web UI won't work."
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check for avahi-browse
if ! command -v avahi-browse &> /dev/null; then
    echo "⚠️  avahi-utils not found (needed for channel discovery)"
    read -p "Install avahi-utils? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        sudo apt-get update
        sudo apt-get install -y avahi-utils
    fi
fi

# Setup Python virtual environment
echo ""
echo "📦 Setting up Python environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✅ Created virtual environment"
else
    echo "✅ Virtual environment exists"
fi

# Activate venv
source venv/bin/activate

# Install Python dependencies
echo ""
echo "📦 Installing Python dependencies..."
pip install --upgrade pip > /dev/null
pip install -r requirements.txt

# Check if visualization tools needed
echo ""
read -p "Install WWV timing visualization tools (pandas, matplotlib)? (Y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    pip install pandas matplotlib
    echo "✅ Visualization tools installed"
fi

# Setup Web UI
if command -v node &> /dev/null; then
    echo ""
    echo "📦 Setting up Web UI..."
    cd web-ui
    
    # Check for npm or pnpm
    if command -v pnpm &> /dev/null; then
        echo "Using pnpm..."
        pnpm install
    else
        echo "Using npm..."
        npm install
    fi
    cd ..
    echo "✅ Web UI dependencies installed"
fi

# Create directories
echo ""
echo "📁 Creating directories..."
mkdir -p logs data config
echo "✅ Directories created"

# Summary
echo ""
echo "================================"
echo "✅ Setup Complete!"
echo ""
echo "Next steps:"
echo "1. Configure: cp config/grape-S000171.toml config/my-station.toml"
echo "2. Edit: nano config/my-station.toml"
echo "3. Start daemon: source venv/bin/activate && python -m signal_recorder.cli daemon"
echo "4. Start web UI: cd web-ui && node simple-server.js"
echo "5. Open browser: http://localhost:3000/monitoring.html"
echo ""
echo "Documentation:"
echo "  - INSTALL.md: Installation guide"
echo "  - DEPENDENCIES.md: Full dependency list"
echo "  - WWV-TIMING-ANALYSIS.md: Timing analysis guide"
echo ""
