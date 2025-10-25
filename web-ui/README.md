# GRAPE Configuration UI

Web-based configuration interface for the GRAPE signal recorder.

## Features

- **User-friendly forms** - Configure your GRAPE station without editing TOML files
- **Real-time validation** - Ensures grid squares, PSWS IDs, and other fields are correct
- **Channel presets** - One-click setup for WWV and CHU frequencies
- **TOML export** - Generate configuration files compatible with signal-recorder
- **Multi-configuration support** - Manage multiple station configurations
- **PSWS integration** - Configure HamSCI PSWS upload settings

## Quick Start

### Prerequisites

- Ubuntu 20.04+ or Debian 11+
- 2 GB free disk space
- Internet connection (for installation only)

### Installation

**Option 1: Automated Installation (Recommended)**

```bash
cd web-ui
bash install.sh
```

Follow the prompts to set up the database and configure the application.

**Option 2: Manual Installation**

See [INSTALLATION_GUIDE.md](INSTALLATION_GUIDE.md) for detailed step-by-step instructions.

### Starting the Application

```bash
# Development mode
pnpm dev

# Production mode
pnpm build
pnpm start
```

Access the web interface at: `http://localhost:3000`

### Running as a Service

To configure auto-start on boot:

```bash
sudo bash setup-service.sh
```

## Documentation

- **[INSTALLATION_GUIDE.md](INSTALLATION_GUIDE.md)** - Complete installation instructions for beginners
- **[DEPENDENCIES.md](DEPENDENCIES.md)** - Full list of system and application dependencies

## Usage

1. **Create a configuration**
   - Click "New Configuration"
   - Fill in station details (callsign, grid square, PSWS credentials)
   - Save the configuration

2. **Add channels**
   - Use preset buttons to add WWV or CHU channels
   - Or manually add custom channels

3. **Export TOML**
   - Click "Export TOML" to download configuration file
   - Copy to signal-recorder config directory
   - Use with: `python -m signal_recorder.recorder --config your-config.toml`

## Architecture

- **Frontend**: React 19 + TypeScript + Tailwind CSS
- **Backend**: Express + tRPC (type-safe API)
- **Database**: MySQL 8.0
- **Build Tool**: Vite

## Configuration

Environment variables are stored in `.env` file:

```env
DATABASE_URL=mysql://user:password@localhost:3306/grape_config
JWT_SECRET=your-random-secret
VITE_APP_TITLE=GRAPE Configuration UI
```

See `.env.example` for all available options.

## Accessing from Other Computers

### Local Network

Find your server's IP address:
```bash
hostname -I
```

Access from another computer: `http://192.168.1.100:3000`

### Remote Access (SSH Tunnel)

```bash
ssh -L 3000:localhost:3000 user@server-ip
```

Then access: `http://localhost:3000`

## Troubleshooting

### Cannot connect to database

```bash
# Check MySQL is running
sudo systemctl status mysql

# Test database connection
mysql -u grape_user -p grape_config
```

### Port 3000 already in use

```bash
# Find what's using the port
sudo lsof -i :3000

# Change port in .env
PORT=8080
```

### Permission denied

```bash
# Fix file ownership
sudo chown -R $USER:$USER ~/signal-recorder/web-ui
```

See [INSTALLATION_GUIDE.md](INSTALLATION_GUIDE.md) for more troubleshooting tips.

## Development

### Project Structure

```
web-ui/
├── client/              # React frontend
│   ├── src/
│   │   ├── pages/      # Page components
│   │   ├── components/ # Reusable UI components
│   │   └── lib/        # tRPC client
├── server/              # Express backend
│   ├── routers/        # tRPC routers
│   ├── db.ts           # Database queries
│   └── _core/          # Framework code
├── drizzle/            # Database schema
├── shared/             # Shared types
└── docs/               # Documentation
```

### Adding Features

1. Update database schema in `drizzle/schema.ts`
2. Run `pnpm db:push` to apply changes
3. Add database queries in `server/db.ts`
4. Create tRPC procedures in `server/routers/`
5. Build UI in `client/src/pages/`
6. Use `trpc.*.useQuery/useMutation` hooks

## License

Same as parent project (signal-recorder)

## Support

- **Issues**: https://github.com/mijahauan/signal-recorder/issues
- **Documentation**: See parent repository README

## Related Projects

- **signal-recorder** - Python-based GRAPE signal recorder (parent project)
- **ka9q-radio** - Software-defined radio receiver
- **wsprdaemon** - WSPR daemon with GRAPE support

