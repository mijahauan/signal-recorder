# GRAPE Web UI - Monitoring Dashboard

**Simple monitoring interface for the GRAPE signal recorder.**

## ✨ Features

- **Dashboard** - Data accumulation stats, spectrogram viewer, gap tracking
- **Logs** - System log viewer with filtering
- **About** - External links (PSWS, HamSCI), station info, references
- **Pure Presentation Layer** - No business logic, just displays data

---

## 🚀 Quick Start

### Prerequisites

1. **GRAPE signal recorder** installed and running
2. **Node.js 18+** and npm (or pnpm)
3. **Data being generated** by core recorder

### Installation

```bash
cd web-ui
npm install  # or: pnpm install
```

### Starting the Web UI

```bash
# From web-ui directory
npm start

# Or directly with custom data root
node monitoring-server-v3.js /path/to/data
```

Default data root is `/tmp/grape-test` (test mode).

### Accessing Pages

**Entry point**: http://localhost:3000/ (redirects to dashboard)

**Pages**:
- **dashboard.html** - Data accumulation, spectrograms, gap summary
- **logs.html** - System log viewer
- **about.html** - External links, station info, references

---

## 🗂️ Project Structure

```
web-ui/
├── monitoring-server-v3.js      # ⭐ API server
├── grape-paths.js               # Data location authority
│
├── index.html                   # Entry (redirects to dashboard)
├── dashboard.html               # ⭐ Main dashboard
├── logs.html                    # ⭐ Log viewer
├── about.html                   # ⭐ Links & references
│
├── components/                  # Reusable UI components
├── utils/                       # Server utilities
├── middleware/                  # Express middleware
├── data/                        # Runtime data (auth)
├── archive/                     # Archived/legacy files
└── package.json
```

---

## 🏗️ Architecture

**Design Principle**: Web UI is a **presentation layer only**.

- ✅ **Knows WHERE** data is located (via `grape-paths.js`)
- ✅ **Knows HOW** to display data effectively
- ❌ **Does NOT process** scientific data (that's time-manager's job)

---

## 🛠️ Key API Endpoints

```
GET /api/v1/summary                          - Dashboard data
GET /api/v1/carrier/quality?date=YYYYMMDD    - Carrier metrics + spectrograms
GET /api/v1/carrier/available-dates          - Available data dates
GET /api/v1/logs/list                        - Log file list
GET /api/v1/logs/content?path=...            - Log file contents
GET /spectrograms/:date/:dir/:file           - Spectrogram images
```

---

## 🚨 Troubleshooting

```bash
# Check if port 3000 is in use
lsof -i :3000

# Check API directly
curl http://localhost:3000/api/v1/summary | jq

# Verify data root
node -e "const p = require('./grape-paths.js'); console.log(p.getDataRoot())"
```

---

**Note**: Timing analysis (D_clock, discrimination) is handled by the separate `time-manager` application.
