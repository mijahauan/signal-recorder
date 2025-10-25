#!/bin/bash

# GRAPE Configuration UI - Automated Installation Script
# For Ubuntu/Debian Linux
# Run with: bash install.sh

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}GRAPE Configuration UI - Installation${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then
  echo -e "${RED}Error: Do not run this script as root (with sudo)${NC}"
  echo "Run as a regular user: bash install.sh"
  exit 1
fi

# Check OS
if ! grep -q -E "Ubuntu|Debian" /etc/os-release; then
  echo -e "${RED}Error: This script is for Ubuntu/Debian only${NC}"
  exit 1
fi

echo -e "${YELLOW}Step 1/7: Updating system packages...${NC}"
sudo apt update
sudo apt upgrade -y

echo ""
echo -e "${YELLOW}Step 2/7: Installing prerequisites...${NC}"
sudo apt install -y curl ca-certificates gnupg git build-essential python3

echo ""
echo -e "${YELLOW}Step 3/7: Installing Node.js 20.x...${NC}"
if ! command -v node &> /dev/null; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt install -y nodejs
else
  NODE_VERSION=$(node --version | cut -d'v' -f2 | cut -d'.' -f1)
  if [ "$NODE_VERSION" -lt 18 ]; then
    echo -e "${YELLOW}Upgrading Node.js to version 20...${NC}"
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt install -y nodejs
  else
    echo -e "${GREEN}Node.js already installed: $(node --version)${NC}"
  fi
fi

echo ""
echo -e "${YELLOW}Step 4/7: Installing pnpm...${NC}"
if ! command -v pnpm &> /dev/null; then
  sudo npm install -g pnpm
else
  echo -e "${GREEN}pnpm already installed: $(pnpm --version)${NC}"
fi

echo ""
echo -e "${YELLOW}Step 5/7: Installing application dependencies...${NC}"
pnpm install

echo ""
echo -e "${YELLOW}Step 6/7: Creating configuration file...${NC}"

# Generate random JWT secret
JWT_SECRET=$(openssl rand -base64 32)

# Create .env file
cat > .env <<EOF
# Database Configuration (SQLite - no setup required!)
DATABASE_URL=file:./data/grape-config.db

# JWT Secret
JWT_SECRET=${JWT_SECRET}

# OAuth Configuration (optional)
VITE_APP_ID=grape-config-ui
OAUTH_SERVER_URL=https://api.manus.im
VITE_OAUTH_PORTAL_URL=https://auth.manus.im

# Application Settings
VITE_APP_TITLE=GRAPE Configuration UI
VITE_APP_LOGO=

# Server Port
PORT=3000

# Node Environment
NODE_ENV=production
EOF

chmod 600 .env
echo -e "${GREEN}Configuration file created${NC}"

echo ""
echo -e "${YELLOW}Step 7/7: Initializing database and building application...${NC}"

# Create data directory
mkdir -p data

# Initialize database schema
pnpm db:push

# Build application
pnpm build

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Installation Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Next steps:"
echo ""
echo "1. Start the application:"
echo -e "   ${YELLOW}pnpm start${NC}"
echo ""
echo "2. Access the web interface:"
echo -e "   ${YELLOW}http://localhost:3000${NC}"
echo ""
echo "3. To run as a service (auto-start on boot):"
echo -e "   ${YELLOW}sudo bash setup-service.sh${NC}"
echo ""
echo "For remote access from other computers:"
echo "   Find your IP: hostname -I"
echo "   Access from browser: http://YOUR_IP:3000"
echo ""
echo -e "${GREEN}Database location: ./data/grape-config.db${NC}"
echo -e "${GREEN}Backup this file to preserve your configurations!${NC}"

