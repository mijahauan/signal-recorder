# GRAPE Data Paths and Flow

## Current Problems

1. **Hardcoded "overnight" paths** - Not aligned with actual dates/operations
2. **Web-UI can't find recorder data** - Paths not synchronized  
3. **No standard for PSWS upload** - File organization unclear

---

## Proposed Data Organization

### Directory Structure

```
/var/lib/signal-recorder/    # Production data root (or ~/grape-data/)
├── raw/                     # Raw IQ recordings (large!)
│   └── YYYYMMDD/
│       └── CALLSIGN_GRID/
│           ├── WWV_5_MHz/
│           │   └── WWV_5_MHz_HHMMSS.iq
│           └── CHU_14.67_MHz/
│               └── CHU_14.67_MHz_HHMMSS.iq
│
├── analytics/               # Derived products (for web-ui & PSWS)
│   ├── quality/
│   │   └── YYYYMMDD/
│   │       ├── WWV_5_MHz_minute_quality_YYYYMMDD.csv
│   │       └── ...
│   ├── discontinuities/
│   │   └── YYYYMMDD/
│   └── daily_summary/
│       └── YYYYMMDD/
│
└── psws_upload/             # Staged for upload to HamSCI
    └── YYYYMMDD/
        ├── quality_metrics.csv
        ├── discontinuities.csv
        └── metadata.json
```

### Path Configuration

**Environment Variable** (preferred):
```bash
export GRAPE_DATA_ROOT=/var/lib/signal-recorder
```

**Config File** (fallback):
```toml
[recorder]
data_root = "/var/lib/signal-recorder"
raw_dir = "${data_root}/raw"           # Or explicit path
analytics_dir = "${data_root}/analytics"
psws_staging_dir = "${data_root}/psws_upload"
```

---

## Data Flow

```
┌─────────────┐
│   KA9Q      │
│   radiod    │ RTP packets (multicast)
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────┐
│  GRAPE Recorder                     │
│  (grape_channel_recorder_v2.py)     │
├─────────────────────────────────────┤
│  • Resequencing buffer              │
│  • Zero-fill gaps                   │
│  • WWV tone detection               │
│  • Time_snap establishment          │
│  • Quality metrics calculation      │
└───┬─────────────────────┬───────────┘
    │                     │
    ▼                     ▼
┌──────────────┐    ┌──────────────────┐
│  Raw IQ      │    │  Quality CSV     │
│  Files       │    │  (every 10 min)  │
│  (per min)   │    └────────┬─────────┘
└──────────────┘             │
                             ▼
                    ┌────────────────────┐
                    │  Web Dashboard     │
                    │  (monitoring-      │
                    │   server.js)       │
                    │                    │
                    │  • Live quality    │
                    │  • Time_snap status│
                    │  • Channel metrics │
                    └────────────────────┘
                             │
                             ▼
                    ┌────────────────────┐
                    │  PSWS Upload       │
                    │  (planned)         │
                    │                    │
                    │  • Aggregate daily │
                    │  • Format for PSWS │
                    │  • Upload to cloud │
                    └────────────────────┘
```

---

## Implementation Steps

### 1. Create Standard Paths Script

```bash
#!/bin/bash
# setup-grape-paths.sh

GRAPE_ROOT="${GRAPE_DATA_ROOT:-$HOME/grape-data}"

mkdir -p "$GRAPE_ROOT"/{raw,analytics/{quality,discontinuities,daily_summary},psws_upload}

# Create today's subdirectories
TODAY=$(date +%Y%m%d)
mkdir -p "$GRAPE_ROOT/raw/$TODAY"
mkdir -p "$GRAPE_ROOT/analytics/quality/$TODAY"
mkdir -p "$GRAPE_ROOT/analytics/discontinuities/$TODAY"
mkdir -p "$GRAPE_ROOT/analytics/daily_summary/$TODAY"
mkdir -p "$GRAPE_ROOT/psws_upload/$TODAY"

echo "✅ GRAPE data paths created:"
echo "   Root: $GRAPE_ROOT"
echo "   Date: $TODAY"
```

### 2. Update Recorder to Use Standard Paths

**Option A: Environment variable**
```bash
export GRAPE_DATA_ROOT=/var/lib/signal-recorder
python scripts/run_recorder.py --config config/grape-S000171.toml
```

**Option B: Command-line argument**
```bash
python scripts/run_recorder.py \
  --config config/grape-S000171.toml \
  --data-root /var/lib/signal-recorder
```

### 3. Update Web-UI to Auto-Discover Paths

```javascript
// monitoring-server.js

function findQualityDataPath() {
  const roots = [
    process.env.GRAPE_DATA_ROOT,
    '/var/lib/signal-recorder',
    '/home/mjh/grape-data',
    installDir
  ];
  
  const today = new Date().toISOString().split('T')[0].replace(/-/g, '');
  
  for (const root of roots) {
    if (!root) continue;
    const path = join(root, 'analytics', 'quality', today);
    if (fs.existsSync(path)) {
      return path;
    }
  }
  
  return null;
}
```

---

## Migration Plan

1. **Keep existing data** - Don't delete `/tmp/signal-recorder/overnight_*`
2. **Create new structure** - Set up `/var/lib/signal-recorder` or `~/grape-data`
3. **Restart recorder** - Point to new paths
4. **Update web-ui** - Auto-discover from standard locations
5. **Test** - Verify dashboard shows live data
6. **Document** - Update README with new paths

---

## Benefits

✅ **Predictable paths** - Always know where data lives  
✅ **Date-based organization** - Easy to archive/cleanup  
✅ **Web-UI auto-discovery** - No hardcoded paths  
✅ **PSWS alignment** - Clear staging area for uploads  
✅ **Multi-station** - Can run multiple stations on one host  

---

## PSWS Upload Format (TBD)

```
/var/lib/signal-recorder/psws_upload/20251104/
├── metadata.json          # Station info, config
├── quality_summary.csv    # Hourly/daily aggregates
├── discontinuities.csv    # Gap/loss events
└── timing_quality.csv     # Time_snap drift, WWV detection
```

Upload to: `https://psws.hamsci.org/api/upload` (TBD)
