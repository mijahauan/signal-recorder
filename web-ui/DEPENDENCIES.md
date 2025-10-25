# GRAPE Configuration UI - Complete Dependency List

This document lists **every single dependency** required to run the GRAPE Configuration UI on Ubuntu/Debian Linux.

---

## System Requirements

### Operating System
- **Ubuntu 20.04 LTS** or newer (recommended: 22.04 LTS or 24.04 LTS)
- **Debian 11 (Bullseye)** or newer (recommended: Debian 12 Bookworm)
- **Architecture**: x86_64 (AMD64) or ARM64

### Hardware
- **CPU**: 2+ cores (any modern Intel/AMD/ARM processor)
- **RAM**: 2 GB minimum, 4 GB recommended
- **Disk**: 2 GB free space minimum
- **Network**: Ethernet or WiFi with internet access (for installation only)

---

## Core System Dependencies

### 1. System Utilities (Usually Pre-installed)

```bash
sudo apt install -y \
  curl \
  ca-certificates \
  gnupg \
  git \
  wget \
  build-essential
```

**What each does:**
- `curl`: Downloads files from URLs
- `ca-certificates`: SSL/TLS certificates for HTTPS
- `gnupg`: Encryption and signing tools
- `git`: Version control system
- `wget`: Alternative file downloader
- `build-essential`: C/C++ compiler and build tools (for native Node.js modules)

---

### 2. Node.js Runtime

**Version Required**: 18.x or newer (20.x recommended)

```bash
# Install from NodeSource repository
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

**What it provides:**
- `node`: JavaScript runtime
- `npm`: Node Package Manager (bundled with Node.js)

**Disk space**: ~100 MB

---

### 3. pnpm Package Manager

**Version Required**: 8.x or newer

```bash
sudo npm install -g pnpm
```

**What it does**: Faster, more efficient alternative to npm for managing JavaScript dependencies

**Disk space**: ~20 MB

**Why not npm?** pnpm is faster and uses less disk space (symlinks shared dependencies)

---

### 4. MySQL Database Server

**Version Required**: 5.7 or newer (8.0 recommended)

```bash
sudo apt install -y mysql-server
```

**What it provides:**
- `mysql`: MySQL command-line client
- `mysqld`: MySQL server daemon
- Database storage for configurations

**Disk space**: ~500 MB

**Alternative**: MariaDB (compatible drop-in replacement)

```bash
sudo apt install -y mariadb-server
```

---

## Application Dependencies (Installed Automatically)

When you run `pnpm install`, the following packages are installed:

### Frontend Dependencies (Client-side)

#### Core Framework
- **react** (19.x): UI library
- **react-dom** (19.x): React rendering for web browsers
- **wouter** (3.x): Lightweight routing

#### UI Components
- **@radix-ui/react-*** (multiple packages): Accessible UI primitives
- **tailwindcss** (4.x): Utility-first CSS framework
- **lucide-react** (0.x): Icon library

#### API Client
- **@trpc/client** (11.x): Type-safe API client
- **@trpc/react-query** (11.x): React hooks for tRPC
- **@tanstack/react-query** (5.x): Data fetching and caching

#### Form Handling
- **react-hook-form** (7.x): Form state management
- **zod** (3.x): Schema validation

#### Utilities
- **clsx** (2.x): Conditional CSS classes
- **tailwind-merge** (2.x): Merge Tailwind classes
- **sonner** (1.x): Toast notifications

**Total frontend dependencies**: ~50 packages
**Disk space**: ~200 MB

---

### Backend Dependencies (Server-side)

#### Core Server
- **express** (4.x): Web server framework
- **@trpc/server** (11.x): Type-safe API server

#### Database
- **drizzle-orm** (0.x): TypeScript ORM
- **drizzle-kit** (0.x): Database migrations
- **mysql2** (3.x): MySQL client for Node.js

#### Authentication
- **jsonwebtoken** (9.x): JWT token handling
- **cookie-parser** (1.x): Parse HTTP cookies

#### Utilities
- **dotenv** (16.x): Environment variable loading
- **cors** (2.x): Cross-Origin Resource Sharing
- **superjson** (2.x): JSON serialization with Date/Map/Set support

**Total backend dependencies**: ~30 packages
**Disk space**: ~100 MB

---

### Development Dependencies (Optional - Only for Development)

- **vite** (7.x): Build tool and dev server
- **typescript** (5.x): TypeScript compiler
- **@types/*** (multiple): TypeScript type definitions
- **eslint** (9.x): Code linting
- **prettier** (3.x): Code formatting

**Total dev dependencies**: ~100 packages
**Disk space**: ~300 MB

**Note**: These are only needed during development, not for running the production build.

---

## Runtime Dependencies Summary

### Absolutely Required (Cannot Run Without)
1. **Node.js 18+** (JavaScript runtime)
2. **MySQL 5.7+** (Database server)
3. **Application code** (from GitHub)
4. **Application dependencies** (installed via `pnpm install`)

### Recommended
1. **pnpm** (faster than npm, but npm works too)
2. **systemd** (for auto-start service - usually pre-installed)

### Optional
1. **nginx/Caddy** (for reverse proxy with HTTPS)
2. **UFW/iptables** (firewall management)
3. **fail2ban** (security - prevent brute force attacks)

---

## Network Requirements

### During Installation
- **Internet access** required to download:
  - Node.js packages from npmjs.com
  - System packages from Ubuntu/Debian repositories
  - Application code from GitHub

**Bandwidth needed**: ~500 MB download

### During Operation
- **No internet required** for basic operation
- **Internet required** for:
  - PSWS uploads (if enabled)
  - OAuth authentication (if using Manus Auth)
  - Software updates

---

## Port Requirements

### Required Ports
- **3000/tcp**: Web interface (default, can be changed)
- **3306/tcp**: MySQL (localhost only, not exposed externally)

### Firewall Configuration

```bash
# Allow web interface from local network
sudo ufw allow 3000/tcp

# MySQL should NOT be exposed externally (security risk)
# It only needs to accept connections from localhost
```

---

## File System Requirements

### Disk Space Breakdown
- Node.js: ~100 MB
- MySQL: ~500 MB
- Application code: ~5 MB
- Application dependencies: ~300 MB
- Database data: ~10 MB (grows with configurations)
- Logs: ~50 MB (rotated automatically)

**Total**: ~1 GB minimum, 2 GB recommended

### Required Directories
```
/home/username/
├── signal-recorder/
│   └── grape-config-ui/
│       ├── node_modules/        (dependencies)
│       ├── dist/                (built application)
│       ├── .env                 (configuration)
│       └── ...
```

### Permissions
- Application directory: Read/write for user
- `.env` file: Read-only for user (chmod 600)
- Service file: Root-owned (systemd)

---

## Environment Variables

### Required
```env
DATABASE_URL=mysql://user:password@localhost:3306/database
JWT_SECRET=random-secret-key
```

### Optional (with defaults)
```env
NODE_ENV=production
PORT=3000
VITE_APP_TITLE=GRAPE Configuration UI
```

---

## Security Dependencies

### SSL/TLS Certificates
- **ca-certificates** package (for HTTPS connections)
- **openssl** (for generating secrets)

### User Permissions
- Application runs as **non-root user** (security best practice)
- MySQL runs as **mysql user** (isolated)
- Service runs with **restricted permissions** (NoNewPrivileges=true)

---

## Compatibility Matrix

| Component | Ubuntu 20.04 | Ubuntu 22.04 | Ubuntu 24.04 | Debian 11 | Debian 12 |
|-----------|--------------|--------------|--------------|-----------|-----------|
| Node.js 20.x | ✅ | ✅ | ✅ | ✅ | ✅ |
| MySQL 8.0 | ✅ | ✅ | ✅ | ✅ | ✅ |
| pnpm 8.x | ✅ | ✅ | ✅ | ✅ | ✅ |
| systemd | ✅ | ✅ | ✅ | ✅ | ✅ |

**Legend**: ✅ = Fully supported

---

## Alternative Configurations

### Using MariaDB Instead of MySQL
```bash
sudo apt install -y mariadb-server
# Configuration is identical, just change DATABASE_URL to use mariadb://
```

### Using npm Instead of pnpm
```bash
# Replace all 'pnpm' commands with 'npm'
npm install
npm run build
npm start
```

### Using Different Port
```env
# In .env file
PORT=8080
```

Then access at `http://localhost:8080`

---

## Troubleshooting Dependencies

### Check Installed Versions

```bash
# Node.js
node --version        # Should be v18.x or v20.x

# npm
npm --version         # Should be 9.x or 10.x

# pnpm
pnpm --version        # Should be 8.x or newer

# MySQL
mysql --version       # Should be 5.7.x or 8.0.x

# Git
git --version         # Any recent version

# System info
lsb_release -a        # Ubuntu/Debian version
uname -m              # Architecture (x86_64 or aarch64)
```

### Missing Dependencies

If you get errors about missing packages:

```bash
# Update package list
sudo apt update

# Install missing build tools
sudo apt install -y build-essential python3

# Reinstall Node.js native modules
cd ~/signal-recorder/grape-config-ui
rm -rf node_modules
pnpm install
```

---

## Minimal Installation (No Development Tools)

For production servers, you can skip development dependencies:

```bash
# Install only production dependencies
pnpm install --prod

# Build on another machine, copy dist/ folder
# Then only need: Node.js + MySQL + .env file
```

This reduces disk usage by ~300 MB.

---

## Dependency Update Policy

### Security Updates
- **Critical**: Applied immediately
- **High**: Applied within 7 days
- **Medium/Low**: Applied during regular maintenance

### Version Updates
- **Node.js**: LTS versions only (18.x, 20.x)
- **MySQL**: Stable releases (8.0.x)
- **npm packages**: Semantic versioning (^major.minor.patch)

### Checking for Updates

```bash
# Check outdated packages
pnpm outdated

# Update all packages (carefully!)
pnpm update

# Update specific package
pnpm update package-name
```

---

## Summary Checklist

- [ ] Ubuntu/Debian 20.04+ installed
- [ ] 2 GB free disk space
- [ ] Internet connection available
- [ ] Non-root user account
- [ ] sudo privileges
- [ ] Node.js 18+ installed
- [ ] pnpm installed
- [ ] MySQL 5.7+ installed
- [ ] Git installed
- [ ] Port 3000 available
- [ ] Firewall configured (if applicable)

---

**Last Updated**: 2025-01-20
**Version**: 1.0

