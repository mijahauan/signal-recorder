# GRAPE Configuration Architecture

## Single Config File: `grape-config.toml`

All components (recorder, web-UI, utilities) read from **one config file** with a **mode flag** to separate test and production data.

---

## Configuration Structure

```toml
[station]
callsign = "AC0G"
grid_square = "EM38ww"
id = "S000171"
instrument_id = "172"

[recorder]
# Mode: "test" or "production"
mode = "test"

# Data paths by mode
test_data_root = "/tmp/grape-test"
production_data_root = "/var/lib/signal-recorder"
```

---

## Mode Behavior

### **Test Mode** (default: `mode = "test"`)

- 🧪 **Purpose**: Development, debugging, experimentation
- **Data root**: `/tmp/grape-test` (temporary)
- **Safe to delete**: Yes - data cleared on reboot
- **Use for**: Testing new features, debugging, short recordings
- **No risk**: Won't interfere with operational data

### **Production Mode** (`mode = "production"`)

- 🚀 **Purpose**: Operational data collection for science
- **Data root**: `/var/lib/signal-recorder` (permanent)
- **Persistent**: Data survives reboots
- **Use for**: Long-term recording, PSWS uploads, published data
- **Requires**: Proper permissions, disk space planning

---

## Directory Structure (Both Modes)

```
${data_root}/
├── data/YYYYMMDD/CALLSIGN_GRID/       # Raw IQ recordings
│   ├── WWV_5_MHz/
│   │   ├── 20251104T120000Z_5000000_iq.npz
│   │   └── ...
│   └── CHU_14.67_MHz/
│       └── ...
│
├── analytics/                          # Derived metrics
│   ├── quality/YYYYMMDD/
│   │   ├── WWV_5_MHz_minute_quality_20251104.csv
│   │   └── ...
│   ├── discontinuities/YYYYMMDD/
│   └── daily_summary/YYYYMMDD/
│
└── logs/                               # Recorder logs
    └── recorder_20251104_120000.log
```

---

## Usage

### Starting the System

```bash
# Default: Uses config/grape-config.toml in test mode
./start-grape.sh

# Custom config
./start-grape.sh config/my-config.toml

# Custom duration (default: 86400 = 24 hours)
./start-grape.sh config/grape-config.toml 3600  # 1 hour
```

### Switching to Production

**Edit `config/grape-config.toml`:**

```toml
[recorder]
mode = "production"  # Changed from "test"
```

Then restart:

```bash
./start-grape.sh
```

The system will show:
```
🚀 Mode: PRODUCTION
📁 Data root: /var/lib/signal-recorder
```

### Checking Status

```bash
./web-ui/check-dashboard-status.sh
```

Output shows current mode:
```
📌 Mode: 🧪 TEST
📁 Data root: /tmp/grape-test
```

---

## Component Synchronization

All components automatically read from **the same config file**:

| Component | Config Location | Data Root |
|-----------|----------------|-----------|
| **Recorder** | `config/grape-config.toml` | From `mode` flag |
| **Web-UI** | Same file | Same path |
| **Scripts** | Same file | Same path |

**No hardcoded paths. No environment variables. Single source of truth.**

---

## Benefits

✅ **Simple switching**: Change one line, restart  
✅ **No confusion**: Mode clearly shown on startup  
✅ **Safe testing**: Test mode can't corrupt production data  
✅ **Single config**: All components stay synchronized  
✅ **Clear separation**: Test in `/tmp`, production in `/var/lib`  
✅ **Flexible**: Can have multiple configs for different stations  

---

## Example Workflow

### Development Phase

1. **Edit config**: `mode = "test"`
2. **Start**: `./start-grape.sh`
3. **Verify**: 🧪 TEST mode, `/tmp/grape-test`
4. **Test features**, check data, verify quality metrics
5. **Data auto-cleaned** on reboot

### Production Deployment

1. **Edit config**: `mode = "production"`
2. **Ensure permissions**: `sudo mkdir -p /var/lib/signal-recorder`
3. **Start**: `./start-grape.sh`
4. **Verify**: 🚀 PRODUCTION mode, `/var/lib/signal-recorder`
5. **Monitor**: Data persists, ready for PSWS upload

### Switching Back to Test

1. **Edit config**: `mode = "test"`
2. **Restart**: `./start-grape.sh`
3. **Continue development** without affecting production data

---

## Advanced: Multiple Stations

For multiple stations on one host:

```bash
# Station 1
./start-grape.sh config/station1-grape-config.toml

# Station 2
./start-grape.sh config/station2-grape-config.toml
```

Each config has its own `station.id`, paths, and mode.

---

## Migration from Old Setup

Old setup had hardcoded paths:
- `/tmp/signal-recorder/overnight_20251103`
- Environment variables: `GRAPE_DATA_ROOT`
- Different paths for recorder and web-UI

**New setup**: One config, one flag, all synchronized.

To migrate:
1. Copy old config to `grape-config.toml`
2. Add `mode = "test"` and path settings
3. Delete old files in `/tmp/signal-recorder/overnight_*`
4. Start with `./start-grape.sh`
