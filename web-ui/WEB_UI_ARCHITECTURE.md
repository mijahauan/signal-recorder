# Web UI Architecture - GRAPE Signal Recorder

**Last Updated**: Nov 18, 2025  
**Status**: Production

---

## Design Principle: Separation of Concerns

**Core Principle**: The web UI is a **presentation layer only**.

### What the Web UI Knows
✅ **WHERE** data files are located (via `grape-paths.js`)  
✅ **HOW** to display data effectively (charts, tables, visualizations)  
✅ **WHEN** to refresh/update displays

### What the Web UI Does NOT Know
❌ **WHAT** the data represents scientifically  
❌ **HOW** data is generated or processed  
❌ **WHY** specific values occur

**Rationale**: All domain logic resides in the analytics service (operational app). The web UI is replaceable without affecting data processing.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│ Analytics Service (Python)                                       │
│ ├─ Data generation logic                                         │
│ ├─ Scientific algorithms                                         │
│ └─ Writes to standard locations                                  │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          │ File System
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│ grape-paths.js (Node.js)                                         │
│ ├─ Definitive data location reference                            │
│ ├─ Synchronized with Python PathConfig                           │
│ └─ Single source of truth for file locations                     │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          │ Import/Require
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│ monitoring-server-v3.js (Express.js)                             │
│ ├─ REST API endpoints                                            │
│ ├─ Reads data from paths                                         │
│ ├─ Aggregates/formats for display                                │
│ └─ Serves static HTML/JS/CSS                                     │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          │ HTTP
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│ HTML Dashboards (Browser)                                        │
│ ├─ summary.html       - Main system status                       │
│ ├─ carrier.html       - Carrier analysis & spectrograms          │
│ ├─ discrimination.html - WWV/WWVH differential delays            │
│ └─ timing-dashboard.html - Timing quality metrics                │
└─────────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. grape-paths.js (Data Location Authority)

**Purpose**: Single source of truth for all data file locations

**Synchronization**: Must stay in sync with Python `PathConfig` class

**Key Paths**:
```javascript
{
  dataRoot: "/path/to/data",
  archives: "/path/to/data/archives/{channel}/",
  decimated: "/path/to/data/decimated/{channel}/",
  spectrograms: "/path/to/data/spectrograms/{date}/",
  discrimination: "/path/to/data/discrimination/{channel}/{date}.csv",
  status: {
    core: "/path/to/data/status/core_recorder_status.json",
    analytics: "/path/to/data/status/analytics_status.json"
  }
}
```

**Usage**:
```javascript
const paths = require('./grape-paths.js');
const archivePath = paths.getArchiveDir('WWV_5.0_MHz');
```

**Critical**: When Python PathConfig changes, `grape-paths.js` must be updated.

### 2. monitoring-server-v3.js (API Server)

**Purpose**: REST API and static file server

**Responsibilities**:
- Serve HTML/JS/CSS static files
- Provide JSON API endpoints
- Read data files (using grape-paths.js)
- Format data for display (no domain logic)
- Health checks and system status

**Does NOT**:
- Generate data
- Perform scientific calculations
- Understand data meaning

**Key Endpoints**:
```
GET /api/v1/summary              - All dashboard data
GET /api/v1/system/status        - System processes
GET /api/v1/channels/status      - Per-channel status
GET /api/v1/carrier/quality      - Carrier metrics
GET /api/v1/channels/:name/discrimination/:date - Discrimination data
GET /spectrograms/:date/:subdirectory/:filename - Image files
```

### 3. HTML Dashboards

#### summary.html
- **Purpose**: System overview and health
- **Data**: System status, channel health, completeness
- **Updates**: Real-time polling (5s interval)

#### carrier.html
- **Purpose**: Carrier analysis and spectrograms
- **Data**: Spectrograms (PNG), quality metrics (JSON)
- **Features**: Date navigation, frequency selection

#### discrimination.html
- **Purpose**: WWV/WWVH differential delays
- **Data**: CSV time series (timestamp, WWV timing, WWVH timing, differential delay)
- **Visualization**: Time series charts, statistics

#### timing-dashboard.html
- **Purpose**: Timing quality monitoring
- **Data**: time_snap events, timing quality annotations
- **Status**: Needs work (per user)

---

## Data Flow

### Production Flow

```
1. Analytics Service (Python)
   ↓ Writes NPZ/CSV/JSON
   
2. File System
   ├─ /data/archives/{channel}/YYYYMMDD_HHMMSS_iq.npz
   ├─ /data/decimated/{channel}/YYYYMMDD_HHMMSS_10hz.npz
   ├─ /data/spectrograms/{date}/{type}/{frequency}.png
   └─ /data/discrimination/{channel}/YYYYMMDD.csv
   
3. grape-paths.js
   ↓ Provides file paths
   
4. monitoring-server-v3.js
   ↓ Reads files, formats JSON
   
5. Browser (HTML/JS)
   ↓ Fetches via API, renders charts
```

### Path Configuration Sync

**Python** (`src/signal_recorder/path_config.py`):
```python
class PathConfig:
    def __init__(self, data_root):
        self.data_root = data_root
        self.archives = os.path.join(data_root, "archives")
        self.decimated = os.path.join(data_root, "decimated")
        # ... etc
```

**JavaScript** (`web-ui/grape-paths.js`):
```javascript
module.exports = {
  getDataRoot: () => dataRoot,
  getArchiveRoot: () => path.join(dataRoot, "archives"),
  getDecimatedRoot: () => path.join(dataRoot, "decimated"),
  // ... must mirror Python structure
};
```

**Validation**: Run `scripts/validate-paths-sync.sh` to check consistency.

---

## Startup

### Production Start (Recommended)

From project root:
```bash
./start-dual-service.sh
```

This starts:
1. Core recorder (Python)
2. Analytics service (Python)
3. Monitoring server (Node.js) → `web-ui/monitoring-server-v3.js`

### Manual Web UI Start

From `web-ui/` directory:
```bash
./start-monitoring.sh
```

Or directly:
```bash
node monitoring-server-v3.js
# With custom data root:
node monitoring-server-v3.js /path/to/data
```

### Test Mode Start

```bash
./start-summary-test.sh
# Reads config from ../config/grape-config.toml
# Uses test_data_root or production_data_root
```

---

## File Organization

### Active Production Files

```
web-ui/
├── monitoring-server-v3.js      # ⭐ Production API server
├── grape-paths.js               # ⭐ Data location authority
│
├── index.html                   # Entry point (redirects to summary)
├── summary.html                 # ⭐ Main dashboard
├── carrier.html                 # ⭐ Carrier analysis
├── discrimination.html          # ⭐ WWV/WWVH discrimination
├── timing-dashboard.html        # ⭐ Timing quality (needs work)
├── discrimination.js            # Chart logic for discrimination
│
├── utils/                       # Server utilities
│   ├── audit.js                 # Audit logging
│   ├── auth.js                  # Authentication
│   ├── config-sync.js           # Config synchronization
│   └── radiod.js                # Radiod status queries
│
├── middleware/                  # Express middleware
│   └── validation.js            # Input validation
│
├── scripts/                     # Admin scripts
│   └── create-admin.js          # User management
│
├── data/                        # Runtime data
│   ├── users.json               # User accounts
│   ├── jwt-secret.txt           # Auth secret
│   └── .gitignore
│
├── start-monitoring.sh          # Startup script
├── start-audio-proxy.sh         # Audio streaming
├── start-summary-test.sh        # Test mode startup
├── check-dashboard-status.sh    # Health check
│
├── package.json                 # Dependencies
├── pnpm-lock.yaml              # Lock file
└── README.md                    # Documentation
```

### Archived (Legacy)

```
web-ui/archive/legacy-pages/
├── simple-dashboard.html        # Superseded by summary.html
├── analysis.html                # Linked but useless
├── live-status.html             # Not used
├── channels.html                # Not used
├── quality-dashboard-addon.html # Component (unclear usage)
├── timing-analysis.html         # Superseded by timing-dashboard.html
└── simple-server.js.ARCHIVED-config-ui  # Old config UI
```

---

## Development Guidelines

### Adding New Dashboards

1. **Create HTML file** with standard header/nav
2. **Add API endpoint** in `monitoring-server-v3.js`
3. **Use grape-paths.js** for all file locations
4. **No domain logic** in JavaScript
5. **Update** this documentation

### Modifying Data Locations

1. **Update Python** `PathConfig` first
2. **Update** `grape-paths.js` to match
3. **Run** `scripts/validate-paths-sync.sh`
4. **Test** all dashboards
5. **Document** changes

### API Design

**Good** (presentation layer):
```javascript
app.get('/api/v1/channels/status', (req, res) => {
  const statusFile = paths.getCoreStatusFile();
  const data = JSON.parse(fs.readFileSync(statusFile));
  res.json(data); // Just read and serve
});
```

**Bad** (domain logic in web UI):
```javascript
app.get('/api/v1/channels/status', (req, res) => {
  // Don't calculate quality metrics here!
  // Don't interpret timing errors!
  // Don't make scientific decisions!
});
```

---

## Troubleshooting

### Server Won't Start

```bash
# Check if port 3000 is in use
lsof -i :3000

# Kill existing instance
pkill -f monitoring-server

# Check logs
tail -f web-ui/monitoring-server.log
```

### Data Not Showing

```bash
# Verify paths are correct
node -e "const p = require('./grape-paths.js'); console.log(p.getDataRoot())"

# Check if files exist
ls -lh /path/to/data/archives/

# Check API directly
curl http://localhost:3000/api/v1/summary | jq
```

### Path Sync Issues

```bash
# Validate Python/JavaScript path consistency
cd /home/mjh/git/signal-recorder
./scripts/validate-paths-sync.sh
```

---

## Future Improvements

### Timing Dashboard
- User noted: "needs work"
- Current: Basic timing quality display
- Needed: Better visualization, historical trends

### Real-time Updates
- Current: Polling every 5 seconds
- Consider: WebSocket for true real-time

### Mobile Responsiveness
- Current: Desktop-optimized
- Consider: Mobile-friendly layouts

---

## Related Documentation

- **Python PathConfig**: `src/signal_recorder/path_config.py`
- **Path Validation**: `scripts/validate-paths-sync.sh`
- **API Reference**: `web-ui/PATHS_API_QUICK_REFERENCE.md`
- **Operational Summary**: `../OPERATIONAL_SUMMARY.md`

---

**Key Takeaway**: Web UI is a **dumb display layer**. All intelligence lives in the analytics service.
