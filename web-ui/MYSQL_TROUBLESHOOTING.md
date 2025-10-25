# MySQL/MariaDB Installation Troubleshooting

This guide helps resolve common MySQL/MariaDB installation issues on Ubuntu/Debian.

---

## Problem: "Unit mysql.service not found"

### Cause
MySQL server package is not installed, or the service has a different name (e.g., `mariadb`).

### Solution 1: Install MySQL Server

```bash
# Update package list
sudo apt update

# Install MySQL server
sudo DEBIAN_FRONTEND=noninteractive apt install -y mysql-server

# Start the service
sudo systemctl start mysql
sudo systemctl enable mysql

# Verify it's running
sudo systemctl status mysql
```

### Solution 2: Check for MariaDB Instead

```bash
# Check if MariaDB is installed
systemctl list-unit-files | grep mariadb

# If MariaDB is present, use it instead
sudo systemctl start mariadb
sudo systemctl enable mariadb
```

---

## Problem: "Can't connect to local server through socket '/run/mysqld/mysqld.sock'"

### Cause
MySQL server is not running, or the socket file doesn't exist.

### Solution 1: Start MySQL Service

```bash
# Check service status
sudo systemctl status mysql

# If not running, start it
sudo systemctl start mysql

# If it fails, check logs
sudo journalctl -u mysql -n 50
```

### Solution 2: Initialize MySQL Data Directory

If MySQL was never initialized:

```bash
# Create data directory
sudo mkdir -p /var/lib/mysql
sudo chown mysql:mysql /var/lib/mysql

# Initialize MySQL
sudo mysqld --initialize-insecure --user=mysql

# Start the service
sudo systemctl start mysql
```

### Solution 3: Check Socket File Location

```bash
# Find where MySQL expects the socket
grep socket /etc/mysql/mysql.conf.d/mysqld.cnf

# Create directory if missing
sudo mkdir -p /run/mysqld
sudo chown mysql:mysql /run/mysqld

# Restart MySQL
sudo systemctl restart mysql
```

---

## Problem: "ERROR 1698 (28000): Access denied for user 'root'@'localhost'"

### Cause
MySQL 8.0+ uses `auth_socket` plugin for root by default, requiring sudo.

### Solution: Use sudo for root access

```bash
# Connect as root (requires sudo)
sudo mysql -u root

# Or set a password for root
sudo mysql -u root <<EOF
ALTER USER 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY 'your_password';
FLUSH PRIVILEGES;
EOF
```

---

## Problem: Installation Script Fails at Database Creation

### Manual Database Setup

If the automated script fails, create the database manually:

```bash
# 1. Connect to MySQL as root
sudo mysql -u root

# 2. Run these SQL commands:
CREATE DATABASE IF NOT EXISTS grape_config;
CREATE USER IF NOT EXISTS 'grape_user'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON grape_config.* TO 'grape_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;

# 3. Test the connection
mysql -u grape_user -p grape_config
# Enter the password you set above
```

---

## Problem: "Package mysql-server is not available"

### Cause
Package repositories are not updated or MySQL is not in the default repos.

### Solution: Add MySQL APT Repository

```bash
# Download MySQL APT config
wget https://dev.mysql.com/get/mysql-apt-config_0.8.29-1_all.deb

# Install it
sudo dpkg -i mysql-apt-config_0.8.29-1_all.deb

# Update package list
sudo apt update

# Install MySQL server
sudo apt install -y mysql-server
```

---

## Problem: "Job for mysql.service failed"

### Cause
MySQL service failed to start due to configuration or permission issues.

### Solution: Check Logs and Fix

```bash
# View detailed error logs
sudo journalctl -u mysql -n 100 --no-pager

# Common fixes:

# 1. Fix permissions
sudo chown -R mysql:mysql /var/lib/mysql
sudo chown -R mysql:mysql /var/log/mysql
sudo chown -R mysql:mysql /run/mysqld

# 2. Remove old PID file
sudo rm -f /var/run/mysqld/mysqld.pid

# 3. Check disk space
df -h

# 4. Try starting manually to see errors
sudo mysqld --user=mysql --console

# 5. Restart the service
sudo systemctl restart mysql
```

---

## Alternative: Use MariaDB Instead of MySQL

MariaDB is a drop-in replacement for MySQL and often works better on some systems.

### Install MariaDB

```bash
# Install MariaDB
sudo apt install -y mariadb-server

# Start the service
sudo systemctl start mariadb
sudo systemctl enable mariadb

# Secure the installation
sudo mysql_secure_installation
```

### Update .env File

Change the DATABASE_URL in your `.env` file (MariaDB uses the same protocol):

```env
DATABASE_URL=mysql://grape_user:your_password@localhost:3306/grape_config
```

---

## Verification Steps

After fixing MySQL issues, verify everything works:

```bash
# 1. Check service is running
sudo systemctl status mysql
# Should show "active (running)"

# 2. Test connection
mysql -u root -p
# Should connect without errors

# 3. Test database user
mysql -u grape_user -p grape_config
# Should connect to grape_config database

# 4. Check socket file exists
ls -la /run/mysqld/mysqld.sock
# Should show the socket file

# 5. Test from application
cd ~/signal-recorder/web-ui
pnpm db:push
# Should succeed without errors
```

---

## Complete Fresh Install (Nuclear Option)

If nothing else works, completely remove and reinstall MySQL:

```bash
# 1. Stop MySQL
sudo systemctl stop mysql

# 2. Remove MySQL completely
sudo apt remove --purge mysql-server mysql-client mysql-common
sudo apt autoremove
sudo apt autoclean

# 3. Remove data directories (WARNING: This deletes all databases!)
sudo rm -rf /var/lib/mysql
sudo rm -rf /etc/mysql

# 4. Reinstall
sudo apt update
sudo DEBIAN_FRONTEND=noninteractive apt install -y mysql-server

# 5. Start service
sudo systemctl start mysql
sudo systemctl enable mysql

# 6. Verify
sudo systemctl status mysql
```

---

## Getting Help

If you're still having issues:

1. **Check MySQL version**:
   ```bash
   mysql --version
   ```

2. **Check Ubuntu/Debian version**:
   ```bash
   lsb_release -a
   ```

3. **Collect error logs**:
   ```bash
   sudo journalctl -u mysql -n 200 > mysql_errors.log
   ```

4. **Report the issue** at: https://github.com/mijahauan/signal-recorder/issues

Include:
- Your OS version
- MySQL version
- Error messages
- Output of `sudo systemctl status mysql`

---

## Quick Reference Commands

```bash
# Start MySQL
sudo systemctl start mysql

# Stop MySQL
sudo systemctl stop mysql

# Restart MySQL
sudo systemctl restart mysql

# Check status
sudo systemctl status mysql

# View logs
sudo journalctl -u mysql -f

# Connect as root
sudo mysql -u root

# Test connection
mysqladmin ping -h localhost

# Check MySQL is listening
sudo netstat -tlnp | grep mysql
```

---

**Last Updated**: 2025-01-20

