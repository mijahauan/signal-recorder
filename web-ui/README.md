# GRAPE Configuration UI

**Lightweight JSON-based configuration interface for the GRAPE signal recorder.**

## ✨ Features

- **No Database Required** - Uses simple JSON files for storage
- **Zero Configuration** - Works out of the box with default admin/admin login
- **TOML Export** - Generate configuration files compatible with signal-recorder
- **Channel Presets** - One-click setup for WWV and CHU frequencies
- **Simple Installation** - Single command to start

## 🚀 Quick Start

### Installation

1. **Install Node.js 18+** (if not already installed):
   ```bash
   # On Ubuntu/Debian
   curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
   sudo apt install -y nodejs

   # On macOS with Homebrew
   brew install node@20

   # On Windows
   # Download from https://nodejs.org/
   ```

2. **Clone and start**:
   ```bash
   cd web-ui
   npm install
   npm start
   ```

3. **Access the interface**:
   - Open http://localhost:3000
   - Login with: `admin` / `admin`

## 🔧 Usage

1. **Login** with default credentials (admin/admin)
2. **Create Configuration** - Fill in station details
3. **Add Channels** - Use presets or add custom frequencies
4. **Export TOML** - Download configuration file
5. **Copy to signal-recorder** config directory

## 🗂️ Project Structure

```
web-ui/
├── index.html          # Main web interface
├── simple-server.js    # Express server with JSON API
├── data/              # JSON database files (created automatically)
│   ├── users.json
│   ├── configurations.json
│   └── channels.json
└── package.json
```

## 🔒 Security

- **Default Credentials**: admin/admin (change in production)
- **Local Access**: Designed for local network use
- **No External Dependencies**: All data stored locally

## 🛠️ Development

### Available Commands

```bash
npm start    # Start the server
npm run dev  # Same as start (development mode)
npm run format # Format code with Prettier
```

### Adding Features

The server provides a REST API:

- `GET /api/configurations` - List all configurations
- `POST /api/configurations` - Create new configuration
- `GET /api/configurations/:id/export` - Export TOML file
- `GET /api/presets/wwv` - WWV frequency presets
- `GET /api/presets/chu` - CHU frequency presets

## 📊 Database Schema

Configurations are stored as JSON with this structure:

```json
{
  "id": "unique-id",
  "name": "My Station",
  "callsign": "W1AW",
  "gridSquare": "EM10",
  "stationId": "station_001",
  "instrumentId": "instrument_001",
  "description": "Primary monitoring station",
  "dataDir": "/data/grape",
  "archiveDir": "/archive/grape",
  "pswsEnabled": "yes",
  "pswsServer": "pswsnetwork.eng.ua.edu",
  "createdAt": "2025-01-20T10:30:00.000Z",
  "updatedAt": "2025-01-20T10:30:00.000Z"
}
```

## 🚨 Troubleshooting

### Server Won't Start
```bash
# Check if port 3000 is available
lsof -i :3000

# Or use a different port
PORT=8080 npm start
```

### Cannot Login
- Username: `admin`
- Password: `admin`
- Check browser console for errors

### Data Not Saving
- Ensure write permissions in the web-ui directory
- Check server logs for errors

## 🔄 Migration from Complex Version

If you have the old version with MySQL/SQLite:

1. Export your configurations as TOML files
2. Delete the old installation
3. Use this simplified version
4. Import TOML files if needed (or recreate configurations)

## 📝 License

Same as parent project (signal-recorder)

## 🆘 Support

- **Issues**: https://github.com/mijahauan/signal-recorder/issues
- **Documentation**: See parent repository README

---

**This simplified version prioritizes ease of use and reliability over complex features.**

