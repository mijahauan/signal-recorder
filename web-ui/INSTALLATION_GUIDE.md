# GRAPE Configuration UI - Complete Installation Guide

**For Ubuntu/Debian Linux Users**

This guide assumes you are starting from a fresh Ubuntu or Debian installation and have no prior experience with web servers or databases. Every step is explained in detail.

---

## Table of Contents

1. [System Requirements](#system-requirements)
2. [Pre-Installation Checklist](#pre-installation-checklist)
3. [Step-by-Step Installation](#step-by-step-installation)
4. [Starting the Application](#starting-the-application)
5. [Accessing the Web Interface](#accessing-the-web-interface)
6. [Running as a Service (Auto-Start)](#running-as-a-service-auto-start)
7. [Troubleshooting](#troubleshooting)
8. [Uninstalling](#uninstalling)

---

## System Requirements

### Minimum Hardware
- **CPU**: Any modern processor (Intel/AMD, 2+ cores recommended)
- **RAM**: 2 GB minimum, 4 GB recommended
- **Disk Space**: 2 GB free space
- **Network**: Ethernet or WiFi connection

### Supported Operating Systems
- Ubuntu 20.04 LTS or newer
- Ubuntu 22.04 LTS (recommended)
- Ubuntu 24.04 LTS
- Debian 11 (Bullseye) or newer
- Debian 12 (Bookworm)

### What You Need Before Starting
- Root/sudo access (administrator privileges)
- Internet connection (for downloading packages)
- Terminal/command line access

---

## Pre-Installation Checklist

Before installing, check your system:

```bash
# Check Ubuntu/Debian version
lsb_release -a

# Check available disk space (need at least 2 GB free)
df -h

# Check available memory
free -h

# Check internet connectivity
ping -c 3 google.com
```

---

## Step-by-Step Installation

### Step 1: Update System Packages

Open a terminal and run:

```bash
sudo apt update
sudo apt upgrade -y
```

**What this does**: Updates the list of available software and upgrades installed packages to their latest versions.

**Time required**: 2-10 minutes depending on internet speed.

---

### Step 2: Install Node.js 20.x

Node.js is the runtime that powers the web server.

```bash
# Install prerequisites
sudo apt install -y curl ca-certificates gnupg

# Add NodeSource repository for Node.js 20.x
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -

# Install Node.js
sudo apt install -y nodejs

# Verify installation
node --version    # Should show v20.x.x
npm --version     # Should show 10.x.x
```

**What this does**: Installs Node.js version 20 (the JavaScript runtime) and npm (the package manager).

**Time required**: 2-5 minutes.

**Expected output**:
```
v20.11.0
10.2.4
```

---

### Step 3: Install pnpm Package Manager

pnpm is a faster, more efficient alternative to npm.

```bash
# Install pnpm globally
sudo npm install -g pnpm

# Verify installation
pnpm --version    # Should show 8.x.x or newer
```

**What this does**: Installs pnpm, which manages JavaScript dependencies more efficiently than npm.

**Time required**: 1 minute.

---

### Step 4: Install MySQL Database Server

The application stores configurations in a MySQL database.

```bash
# Install MySQL server
sudo apt install -y mysql-server

# Start MySQL service
sudo systemctl start mysql
sudo systemctl enable mysql

# Verify MySQL is running
sudo systemctl status mysql
```

**What this does**: Installs and starts the MySQL database server.

**Time required**: 3-5 minutes.

**Expected output**: You should see "active (running)" in green.

---

### Step 5: Secure MySQL Installation

```bash
# Run security script
sudo mysql_secure_installation
```

**Answer the prompts as follows:**

1. **Set root password?** → Yes → Enter a strong password (write it down!)
2. **Remove anonymous users?** → Yes
3. **Disallow root login remotely?** → Yes
4. **Remove test database?** → Yes
5. **Reload privilege tables?** → Yes

**What this does**: Secures your MySQL installation by removing default insecure settings.

**Time required**: 2 minutes.

---

### Step 6: Create Database and User

```bash
# Log into MySQL as root
sudo mysql -u root -p
```

Enter the root password you just created. Then run these SQL commands:

```sql
-- Create database
CREATE DATABASE grape_config;

-- Create user (replace 'your_password' with a strong password)
CREATE USER 'grape_user'@'localhost' IDENTIFIED BY 'your_password';

-- Grant permissions
GRANT ALL PRIVILEGES ON grape_config.* TO 'grape_user'@'localhost';

-- Apply changes
FLUSH PRIVILEGES;

-- Exit MySQL
EXIT;
```

**What this does**: Creates a dedicated database and user account for the GRAPE Configuration UI.

**Time required**: 1 minute.

**Important**: Write down the password you used for `grape_user` - you'll need it later!

---

### Step 7: Install Git (Version Control)

```bash
# Install Git
sudo apt install -y git

# Verify installation
git --version
```

**What this does**: Installs Git, which is needed to download the application code.

**Time required**: 1 minute.

---

### Step 8: Download the Application

```bash
# Navigate to your home directory
cd ~

# Clone the repository
git clone https://github.com/mijahauan/signal-recorder.git

# Navigate to the config UI directory
cd signal-recorder/grape-config-ui
```

**What this does**: Downloads the GRAPE Configuration UI source code from GitHub.

**Time required**: 1 minute.

**Note**: If the repository structure is different, adjust the path accordingly.

---

### Step 9: Install Application Dependencies

```bash
# Install all required packages
pnpm install
```

**What this does**: Downloads and installs all JavaScript libraries the application needs.

**Time required**: 3-5 minutes.

**Expected output**: You'll see a progress bar and eventually "Dependencies installed successfully" or similar message.

---

### Step 10: Configure Database Connection

Create a `.env` file with your database credentials:

```bash
# Create environment file
nano .env
```

Add the following content (replace `your_password` with the password you set in Step 6):

```env
# Database Configuration
DATABASE_URL=mysql://grape_user:your_password@localhost:3306/grape_config

# JWT Secret (generate a random string)
JWT_SECRET=your-random-secret-key-here-make-it-long-and-random

# OAuth Configuration (for Manus Auth - use defaults for now)
VITE_APP_ID=grape-config-ui
OAUTH_SERVER_URL=https://api.manus.im
VITE_OAUTH_PORTAL_URL=https://auth.manus.im

# Application Settings
VITE_APP_TITLE=GRAPE Configuration UI
VITE_APP_LOGO=

# Owner Information (optional)
OWNER_OPEN_ID=
OWNER_NAME=

# Built-in Services (use defaults)
BUILT_IN_FORGE_API_URL=https://api.manus.im
BUILT_IN_FORGE_API_KEY=
```

**Save the file**: Press `Ctrl+X`, then `Y`, then `Enter`.

**What this does**: Configures the application with your database credentials and other settings.

**Time required**: 2 minutes.

**Security Note**: Keep this file private! It contains sensitive credentials.

---

### Step 11: Initialize Database Schema

```bash
# Push database schema
pnpm db:push
```

**What this does**: Creates all necessary database tables and structures.

**Time required**: 30 seconds.

**Expected output**: You should see "migrations applied successfully!"

---

### Step 12: Build the Application

```bash
# Build for production
pnpm build
```

**What this does**: Compiles the application into optimized production-ready files.

**Time required**: 1-2 minutes.

**Expected output**: You'll see build progress and eventually "Build completed successfully" or similar.

---

## Starting the Application

### Option A: Manual Start (Testing)

```bash
# Start the server
pnpm start
```

**What this does**: Starts the web server on port 3000.

**Expected output**:
```
Server running on http://localhost:3000/
```

**To stop**: Press `Ctrl+C`

---

### Option B: Run as Background Service (Recommended)

Create a systemd service file:

```bash
# Create service file
sudo nano /etc/systemd/system/grape-config-ui.service
```

Add this content (replace `/home/YOUR_USERNAME` with your actual home directory path):

```ini
[Unit]
Description=GRAPE Configuration UI
After=network.target mysql.service
Requires=mysql.service

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/signal-recorder/grape-config-ui
Environment="NODE_ENV=production"
ExecStart=/usr/bin/pnpm start
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Save the file**: Press `Ctrl+X`, then `Y`, then `Enter`.

**Enable and start the service**:

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable grape-config-ui

# Start the service now
sudo systemctl start grape-config-ui

# Check status
sudo systemctl status grape-config-ui
```

**What this does**: Configures the application to start automatically when your computer boots.

**Expected output**: You should see "active (running)" in green.

---

## Accessing the Web Interface

### From the Same Computer

1. Open a web browser (Firefox, Chrome, etc.)
2. Navigate to: `http://localhost:3000`
3. You should see the GRAPE Configuration UI home page

### From Another Computer on Your Network

1. Find your server's IP address:
   ```bash
   hostname -I
   ```
   Example output: `192.168.1.100`

2. On another computer, open a web browser
3. Navigate to: `http://192.168.1.100:3000` (use your actual IP)

### From the Internet (Advanced)

**Option 1: SSH Tunnel** (Recommended for security)

From your remote computer:
```bash
ssh -L 3000:localhost:3000 username@your-server-ip
```

Then access `http://localhost:3000` in your browser.

**Option 2: Reverse Proxy** (Requires additional setup)

Install nginx or Caddy to expose the application with HTTPS and a domain name. (See separate guide for this advanced setup.)

---

## Running as a Service (Auto-Start)

If you followed **Option B** in the "Starting the Application" section, the service is already configured to start automatically.

### Useful Service Commands

```bash
# Check if service is running
sudo systemctl status grape-config-ui

# Stop the service
sudo systemctl stop grape-config-ui

# Start the service
sudo systemctl start grape-config-ui

# Restart the service
sudo systemctl restart grape-config-ui

# View logs
sudo journalctl -u grape-config-ui -f

# Disable auto-start
sudo systemctl disable grape-config-ui
```

---

## Troubleshooting

### Problem: "Cannot connect to database"

**Solution**:
1. Check MySQL is running: `sudo systemctl status mysql`
2. Verify database credentials in `.env` file
3. Test database connection:
   ```bash
   mysql -u grape_user -p grape_config
   ```

### Problem: "Port 3000 already in use"

**Solution**:
1. Find what's using port 3000:
   ```bash
   sudo lsof -i :3000
   ```
2. Stop that process or change the port in the application

### Problem: "Permission denied"

**Solution**:
1. Check file ownership:
   ```bash
   ls -la ~/signal-recorder/grape-config-ui
   ```
2. Fix permissions:
   ```bash
   sudo chown -R $USER:$USER ~/signal-recorder/grape-config-ui
   ```

### Problem: "Module not found" errors

**Solution**:
1. Reinstall dependencies:
   ```bash
   cd ~/signal-recorder/grape-config-ui
   rm -rf node_modules
   pnpm install
   ```

### Problem: "Cannot access from another computer"

**Solution**:
1. Check firewall:
   ```bash
   sudo ufw allow 3000/tcp
   ```
2. Verify the server is listening on all interfaces (not just localhost)

### Problem: "Build fails"

**Solution**:
1. Check Node.js version: `node --version` (should be 20.x)
2. Clear cache and rebuild:
   ```bash
   pnpm store prune
   rm -rf node_modules .next
   pnpm install
   pnpm build
   ```

### Getting Help

If you encounter issues not covered here:

1. Check the logs:
   ```bash
   sudo journalctl -u grape-config-ui -n 100
   ```

2. Report issues at: https://github.com/mijahauan/signal-recorder/issues

---

## Uninstalling

To completely remove the application:

```bash
# Stop the service
sudo systemctl stop grape-config-ui
sudo systemctl disable grape-config-ui

# Remove service file
sudo rm /etc/systemd/system/grape-config-ui.service
sudo systemctl daemon-reload

# Remove application files
rm -rf ~/signal-recorder/grape-config-ui

# Remove database (optional - only if you want to delete all configurations)
mysql -u root -p -e "DROP DATABASE grape_config; DROP USER 'grape_user'@'localhost';"

# Uninstall Node.js (optional)
sudo apt remove --purge nodejs
sudo apt autoremove

# Uninstall MySQL (optional)
sudo apt remove --purge mysql-server mysql-client mysql-common
sudo apt autoremove
```

---

## Quick Reference: Complete Installation Script

For experienced users, here's a one-shot installation script:

```bash
#!/bin/bash
set -e

# Update system
sudo apt update && sudo apt upgrade -y

# Install Node.js 20.x
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Install pnpm
sudo npm install -g pnpm

# Install MySQL
sudo apt install -y mysql-server git
sudo systemctl start mysql
sudo systemctl enable mysql

# Clone repository
cd ~
git clone https://github.com/mijahauan/signal-recorder.git
cd signal-recorder/grape-config-ui

# Install dependencies
pnpm install

# Create .env file (YOU MUST EDIT THIS FILE MANUALLY!)
cat > .env << 'EOF'
DATABASE_URL=mysql://grape_user:CHANGE_THIS_PASSWORD@localhost:3306/grape_config
JWT_SECRET=CHANGE_THIS_TO_RANDOM_STRING
VITE_APP_ID=grape-config-ui
OAUTH_SERVER_URL=https://api.manus.im
VITE_OAUTH_PORTAL_URL=https://auth.manus.im
VITE_APP_TITLE=GRAPE Configuration UI
BUILT_IN_FORGE_API_URL=https://api.manus.im
EOF

echo "Installation complete! Next steps:"
echo "1. Run: sudo mysql_secure_installation"
echo "2. Create database and user (see Step 6 in guide)"
echo "3. Edit .env file with your database password"
echo "4. Run: pnpm db:push"
echo "5. Run: pnpm build"
echo "6. Run: pnpm start"
```

**Warning**: This script still requires manual steps for security. Do not skip the manual configuration!

---

## Summary Checklist

- [ ] System updated (`sudo apt update && upgrade`)
- [ ] Node.js 20.x installed
- [ ] pnpm installed
- [ ] MySQL installed and secured
- [ ] Database and user created
- [ ] Application code downloaded
- [ ] Dependencies installed (`pnpm install`)
- [ ] `.env` file configured
- [ ] Database schema initialized (`pnpm db:push`)
- [ ] Application built (`pnpm build`)
- [ ] Service configured and started
- [ ] Web interface accessible

---

## Estimated Total Installation Time

- **Experienced users**: 15-20 minutes
- **Beginners**: 30-45 minutes

---

## Support

For questions or issues:
- GitHub Issues: https://github.com/mijahauan/signal-recorder/issues
- Documentation: See README.md in the repository

---

**Last Updated**: 2025-01-20
**Version**: 1.0

