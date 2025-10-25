# GRAPE Configuration UI - Dependencies (SQLite Version)

**Much simpler than MySQL version!** Only 3 core dependencies needed.

---

## System Requirements

### Operating System
- **Ubuntu 20.04+** or **Debian 11+**
- **Architecture**: x86_64 (AMD64) or ARM64

### Hardware
- **CPU**: Any modern processor (1+ core sufficient)
- **RAM**: 1 GB minimum, 2 GB recommended
- **Disk**: 500 MB free space
- **Network**: Internet access (for installation only)

---

## Core Dependencies (Only 3!)

### 1. Node.js 18+ Runtime

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

**What it does**: Runs the JavaScript application  
**Disk space**: ~100 MB

---

### 2. Build Tools (for SQLite native module)

```bash
sudo apt install -y build-essential python3
```

**What it does**: Compiles better-sqlite3 native bindings  
**Disk space**: ~200 MB

---

### 3. pnpm Package Manager

```bash
sudo npm install -g pnpm
```

**What it does**: Manages JavaScript dependencies  
**Disk space**: ~20 MB

---

## That's It!

**No MySQL/MariaDB required!** SQLite is embedded in the application.

**Total disk space**: ~500 MB (vs 1+ GB for MySQL version)

**Total installation time**: ~5-10 minutes (vs 30-45 minutes for MySQL)

---

## What Changed from MySQL Version?

| Feature | MySQL Version | SQLite Version |
|---------|--------------|----------------|
| Database server | MySQL 8.0 (~500 MB) | None (embedded) |
| Database setup | Manual user/password | Automatic |
| Configuration | DATABASE_URL with credentials | Simple file path |
| Backup | mysqldump or DB tools | Copy one file |
| Portability | Export/import required | Copy .db file |
| Multi-user | Yes (with auth) | Single user |
| Installation time | 30-45 min | 5-10 min |
| Failure points | Many (service, socket, auth) | Few (build tools) |

---

## Application Dependencies (Auto-installed)

When you run `pnpm install`, these are installed automatically:

### Frontend (~200 MB)
- React 19 + TypeScript
- Tailwind CSS + shadcn/ui components
- tRPC client for API calls

### Backend (~100 MB)
- Express web server
- tRPC server
- better-sqlite3 (embedded SQLite)
- Drizzle ORM

**Total**: ~300 MB

---

## Runtime Requirements

### Absolutely Required
1. Node.js 18+
2. Application files (from git repo)
3. pnpm (or npm)

### Optional
- systemd (for auto-start service)
- nginx/Caddy (for reverse proxy with HTTPS)

---

## Port Requirements

- **3000/tcp**: Web interface (configurable via PORT env var)

No database port needed (SQLite uses local file)!

---

## File System

### Disk Space
- Node.js: ~100 MB
- Build tools: ~200 MB
- Application code: ~5 MB
- Dependencies: ~300 MB
- Database: ~1 MB (grows with configs)

**Total**: ~600 MB

### Directory Structure
```
web-ui/
├── data/
│   └── grape-config.db    # SQLite database (backup this!)
├── node_modules/          # Dependencies
├── dist/                  # Built application
├── .env                   # Configuration
└── ...
```

---

## Backup and Restore

### Backup
```bash
# Just copy the database file!
cp data/grape-config.db ~/backups/grape-config-$(date +%Y%m%d).db
```

### Restore
```bash
# Copy it back
cp ~/backups/grape-config-20250120.db data/grape-config.db
```

**That's it!** No mysqldump, no SQL commands needed.

---

## Troubleshooting

### Installation Fails at "pnpm install"

**Problem**: better-sqlite3 compilation fails

**Solution**: Install build tools
```bash
sudo apt install -y build-essential python3
pnpm install
```

### "Cannot find module 'better-sqlite3'"

**Problem**: Native module not compiled

**Solution**: Rebuild
```bash
pnpm rebuild better-sqlite3
```

### Database File Locked

**Problem**: Another process has the database open

**Solution**: Stop the application first
```bash
# If running as service
sudo systemctl stop grape-config-ui

# If running manually
# Press Ctrl+C to stop pnpm start
```

---

## Quick Reference

```bash
# Install dependencies
sudo apt install -y nodejs build-essential python3
sudo npm install -g pnpm

# Install application
pnpm install

# Initialize database
pnpm db:push

# Start application
pnpm start

# Backup database
cp data/grape-config.db ~/backup.db
```

---

**Last Updated**: 2025-01-20  
**Version**: 2.0 (SQLite)

