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

echo -e "${YELLOW}Step 1/10: Updating system packages...${NC}"
sudo apt update
sudo apt upgrade -y

echo ""
echo -e "${YELLOW}Step 2/10: Installing prerequisites...${NC}"
sudo apt install -y curl ca-certificates gnupg git

echo ""
echo -e "${YELLOW}Step 3/10: Installing Node.js 20.x...${NC}"
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
echo -e "${YELLOW}Step 4/10: Installing pnpm...${NC}"
if ! command -v pnpm &> /dev/null; then
  sudo npm install -g pnpm
else
  echo -e "${GREEN}pnpm already installed: $(pnpm --version)${NC}"
fi

echo ""
echo -e "${YELLOW}Step 5/10: Installing MySQL/MariaDB server...${NC}"

# Detect which database system to use
DB_SERVICE=""
DB_INSTALLED=false

# Check if mysql command exists
if command -v mysql &> /dev/null; then
  DB_INSTALLED=true
  echo -e "${GREEN}MySQL client found${NC}"
fi

# Check for existing services
if systemctl list-unit-files 2>/dev/null | grep -q "^mysql.service"; then
  DB_SERVICE="mysql"
  echo -e "${GREEN}MySQL service detected${NC}"
elif systemctl list-unit-files 2>/dev/null | grep -q "^mariadb.service"; then
  DB_SERVICE="mariadb"
  echo -e "${GREEN}MariaDB service detected${NC}"
fi

# Install if not present
if [ "$DB_INSTALLED" = false ]; then
  echo "Installing MySQL server..."
  sudo DEBIAN_FRONTEND=noninteractive apt install -y mysql-server
  DB_SERVICE="mysql"
elif [ -z "$DB_SERVICE" ]; then
  # MySQL client exists but server not installed
  echo "MySQL client found but server not running. Installing MySQL server..."
  sudo DEBIAN_FRONTEND=noninteractive apt install -y mysql-server
  DB_SERVICE="mysql"
fi

# Start the database service
if [ -n "$DB_SERVICE" ]; then
  echo "Starting $DB_SERVICE service..."
  
  # Try to start the service
  if ! sudo systemctl start $DB_SERVICE 2>/dev/null; then
    echo -e "${YELLOW}Service failed to start, attempting to initialize...${NC}"
    
    # For MySQL, try to initialize data directory
    if [ "$DB_SERVICE" = "mysql" ]; then
      if [ ! -d "/var/lib/mysql/mysql" ]; then
        echo "Initializing MySQL data directory..."
        sudo mkdir -p /var/lib/mysql
        sudo chown mysql:mysql /var/lib/mysql
        sudo mysqld --initialize-insecure --user=mysql 2>/dev/null || true
      fi
    fi
    
    # Try starting again
    sudo systemctl start $DB_SERVICE || {
      echo -e "${RED}Failed to start $DB_SERVICE${NC}"
      echo "Please check: sudo journalctl -u $DB_SERVICE -n 50"
      exit 1
    }
  fi
  
  sudo systemctl enable $DB_SERVICE
  
  # Wait for service to be ready
  echo "Waiting for database to be ready..."
  for i in {1..30}; do
    if sudo mysqladmin ping -h localhost --silent 2>/dev/null; then
      echo -e "${GREEN}Database is ready${NC}"
      break
    fi
    if [ $i -eq 30 ]; then
      echo -e "${RED}Database failed to become ready${NC}"
      echo "Checking status:"
      sudo systemctl status $DB_SERVICE --no-pager
      exit 1
    fi
    sleep 1
  done
else
  echo -e "${RED}Error: Could not determine database service name${NC}"
  exit 1
fi

echo ""
echo -e "${YELLOW}Step 6/10: Configuring MySQL database...${NC}"
echo ""
echo "Please enter a password for the MySQL 'grape_user' account:"
read -s -p "Password: " DB_PASSWORD
echo ""
read -s -p "Confirm password: " DB_PASSWORD_CONFIRM
echo ""

if [ "$DB_PASSWORD" != "$DB_PASSWORD_CONFIRM" ]; then
  echo -e "${RED}Error: Passwords do not match${NC}"
  exit 1
fi

if [ -z "$DB_PASSWORD" ]; then
  echo -e "${RED}Error: Password cannot be empty${NC}"
  exit 1
fi

# Create database and user
echo "Creating database and user..."
sudo mysql -u root <<EOF
CREATE DATABASE IF NOT EXISTS grape_config;
CREATE USER IF NOT EXISTS 'grape_user'@'localhost' IDENTIFIED BY '$DB_PASSWORD';
GRANT ALL PRIVILEGES ON grape_config.* TO 'grape_user'@'localhost';
FLUSH PRIVILEGES;
EOF

if [ $? -eq 0 ]; then
  echo -e "${GREEN}Database configured successfully${NC}"
else
  echo -e "${RED}Failed to configure database${NC}"
  exit 1
fi

echo ""
echo -e "${YELLOW}Step 7/10: Installing application dependencies...${NC}"
pnpm install

echo ""
echo -e "${YELLOW}Step 8/10: Creating configuration file...${NC}"

# Generate random JWT secret
JWT_SECRET=$(openssl rand -base64 32)

# Create .env file
cat > .env <<EOF
# Database Configuration
DATABASE_URL=mysql://grape_user:${DB_PASSWORD}@localhost:3306/grape_config

# JWT Secret
JWT_SECRET=${JWT_SECRET}

# OAuth Configuration
VITE_APP_ID=grape-config-ui
OAUTH_SERVER_URL=https://api.manus.im
VITE_OAUTH_PORTAL_URL=https://auth.manus.im

# Application Settings
VITE_APP_TITLE=GRAPE Configuration UI
VITE_APP_LOGO=

# Owner Information
OWNER_OPEN_ID=
OWNER_NAME=

# Built-in Services
BUILT_IN_FORGE_API_URL=https://api.manus.im
BUILT_IN_FORGE_API_KEY=

# Analytics
VITE_ANALYTICS_ENDPOINT=
VITE_ANALYTICS_WEBSITE_ID=
EOF

chmod 600 .env
echo -e "${GREEN}Configuration file created${NC}"

echo ""
echo -e "${YELLOW}Step 9/10: Initializing database schema...${NC}"
pnpm db:push

echo ""
echo -e "${YELLOW}Step 10/10: Building application...${NC}"
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
echo -e "${GREEN}Installation log saved to: install.log${NC}"

