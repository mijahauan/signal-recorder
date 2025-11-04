# Data Storage Audit - Signal Recorder

**Date**: 2025-11-03  
**Issue**: Data storage is scattered across multiple locations without clear separation between RTP stream data and site management data.

---

## Executive Summary

**Current State**: ❌ Data storage is fragmented and lacks clear separation  
**Risk Level**: HIGH - Deleting RTP stream data could accidentally remove site credentials or vice versa  
**Recommendation**: Implement centralized data storage with clear boundaries

---

## Current Data Storage Locations

### 1. RTP Stream Raw & Processed Data

#### Primary Archive (Configurable)
- **Location**: `/var/lib/signal-recorder/archive/` (default, configurable via `archive_dir`)
- **Format**: Digital RF (HDF5 files)
- **Structure**:
  ```
  /var/lib/signal-recorder/archive/
  ├── WWV-2.5/
  │   ├── rf@{timestamp}.h5       # Time-indexed HDF5 data
  │   └── metadata/
  │       └── metadata@{timestamp}.h5
  ├── WWV-5.0/
  ├── WWV-10.0/
  └── CHU-3.3/
  ```
- **Files**: `*.h5` (HDF5 format, compressed)
- **Controlled By**: `recorder.archive_dir` in config TOML
- **Code Reference**: `grape_rtp_recorder.py:1280`, `grape_rtp_recorder.py:1142-1218`

#### Temporary Stats & Status
- **Location**: `/tmp/signal-recorder-stats.json`
- **Purpose**: Real-time recording statistics for web UI monitoring
- **Format**: JSON
- **Code Reference**: `grape_rtp_recorder.py:36`
- **Issue**: ⚠️ Temp location - could be lost on reboot

### 2. Analytics & Quality Metrics

#### Quality Metadata (Per Channel)
- **Location**: `{archive_dir}/{channel_name}/`
- **Files**:
  - `{channel_name}_{YYYYMMDD}_quality.json` - Detailed metrics
  - `{channel_name}_{YYYYMMDD}_summary.txt` - Human-readable summary
  - `daily_report_{YYYYMMDD}.txt` - Daily aggregate report
- **Content**: Completeness %, packet loss, timing drift, gap analysis
- **Code Reference**: `grape_metadata.py:264-436`
- **Issue**: ✅ Co-located with data (good), but not easily separable

#### WWV Timing Analysis
- **Location**: `{project_root}/logs/wwv_timing.csv`
- **Purpose**: WWV tone detection timing validation
- **Format**: CSV (timestamp, channel, frequency_mhz, timing_error_ms, detection_count, snr)
- **Code Reference**: `grape_rtp_recorder.py:850`
- **Issue**: ⚠️ Relative to code location, not data directory

#### Discontinuity Logs
- **Location**: Embedded in Digital RF metadata + exportable to CSV
- **Purpose**: Track gaps, sync adjustments, RTP resets
- **Format**: 
  - Embedded in HDF5 metadata
  - CSV export via `DiscontinuityTracker.export_to_csv()`
- **Code Reference**: `grape_rtp_recorder.py:39-169`
- **Issue**: ⚠️ CSV export location not standardized

### 3. Upload Queue & State

#### Upload Queue
- **Location**: `/var/lib/signal-recorder/upload_queue.json`
- **Purpose**: Track pending/failed uploads to PSWS
- **Format**: JSON array of UploadTask objects
- **Code Reference**: `uploader.py:62, 384`
- **Issue**: ⚠️ Deleting this loses upload state

#### Legacy Processing State
- **Location**: `{archive_dir}/{YYYYMMDD}/{grid}/{receiver}/{band}/processing_state.json`
- **Purpose**: Track processing status in legacy pipeline
- **Code Reference**: `legacy/storage.py:63, 111`
- **Status**: Legacy code, may not be actively used

---

## Site Management Data (Should be Separate)

### Web UI Configuration Database
- **Location**: `/home/mjh/git/signal-recorder/web-ui/data/`
- **Files**:
  - `users.json` - **Login credentials (hashed passwords)**
  - `configurations.json` - Station configurations
  - `channels.json` - Channel definitions
  - `jwt-secret.txt` - JWT authentication secret
- **Code Reference**: `web-ui/simple-server.js:463-482`
- **Issue**: ✅ Separate from RTP data, but in source tree

### TOML Configuration Files
- **Location**: `{project_root}/config/*.toml`
- **Files**:
  - `grape-S000171.toml` - Active site config
  - `grape-production.toml` - Production template
  - Various test configs
- **Content**: Station info, ka9q settings, **PSWS SSH credentials**
- **Issue**: ⚠️ Contains credentials, mixed with version control

### Daemon Status
- **Location**: `{project_root}/data/daemon-status.json`
- **Purpose**: Current daemon state (running/stopped)
- **Code Reference**: `web-ui/simple-server.js:26`
- **Issue**: ⚠️ In source tree, not /var/lib

---

## Problems Identified

### Critical Issues

1. **❌ No Clear Separation**
   - RTP data in `/var/lib/signal-recorder/archive/`
   - Quality metadata mixed with RTP data
   - Upload queue in `/var/lib/signal-recorder/`
   - Site credentials in `web-ui/data/` and `config/*.toml`
   - **Risk**: Deleting archive directory could remove metadata; no single "delete all RTP data" command

2. **❌ Credentials Scattered**
   - User passwords in `web-ui/data/users.json`
   - PSWS SSH keys referenced in TOML configs
   - JWT secret in `web-ui/data/jwt-secret.txt`
   - **Risk**: Deleting RTP data could accidentally include credentials

3. **❌ Inconsistent Paths**
   - Some data in `/var/lib/` (good)
   - Some in `/tmp/` (volatile)
   - Some in project source tree (version control conflict)
   - WWV logs relative to source code location

### Moderate Issues

4. **⚠️ Temporary Files Not Ephemeral**
   - `/tmp/signal-recorder-stats.json` should persist or move
   - Lost on reboot, breaking web UI

5. **⚠️ No Data Lifecycle Management**
   - No age-based cleanup
   - No size limits
   - Archive grows indefinitely

6. **⚠️ Upload Queue Not Co-located**
   - Upload queue in `/var/lib/signal-recorder/`
   - Uploaded data in `{archive_dir}` (could be different)
   - Hard to associate queue with data

---

## Recommended Data Organization

### Proposed Structure

```
# RTP Stream Data (Everything related to recordings)
/var/lib/signal-recorder/
├── data/                           # Raw & processed RTP data
│   ├── WWV-2.5/
│   │   ├── rf@*.h5                # Digital RF files
│   │   └── metadata/              # Digital RF metadata
│   ├── WWV-5.0/
│   └── ...
├── analytics/                      # All analytics derived from RTP data
│   ├── quality/                   # Quality metrics per channel
│   │   ├── WWV-2.5/
│   │   │   ├── 20251103_quality.json
│   │   │   ├── 20251103_summary.txt
│   │   │   └── discontinuities_20251103.csv
│   │   └── ...
│   ├── timing/                    # WWV timing validation
│   │   └── wwv_timing.csv
│   └── reports/                   # Daily aggregate reports
│       └── daily_report_20251103.txt
├── upload/                        # Upload state (can be deleted safely)
│   ├── queue.json                # Pending uploads
│   └── history.json              # Completed uploads
└── status/                        # Runtime state (can be deleted)
    └── recording-stats.json      # Real-time stats for web UI

# Site Management Data (Separate from RTP data)
/etc/signal-recorder/              # System configuration
├── config.toml                   # Active site config (NO credentials)
└── credentials/                  # Sensitive data (restrictive permissions)
    ├── psws_ssh_key             # SSH key for uploads
    └── jwt_secret.txt           # Web UI JWT secret

/var/lib/signal-recorder-web/     # Web UI persistent data
├── users.json                    # Login credentials
├── configurations.json           # Saved configurations
└── channels.json                 # Channel definitions

/var/log/signal-recorder/         # Logs (not critical data)
├── daemon.log                    # Main daemon log
├── upload.log                    # Upload activity
└── web-ui.log                    # Web server log
```

### Benefits of Proposed Structure

✅ **Clear Separation**
- RTP data: `/var/lib/signal-recorder/data/` and `/var/lib/signal-recorder/analytics/`
- Site management: `/etc/signal-recorder/` and `/var/lib/signal-recorder-web/`
- Easy to delete all RTP data: `rm -rf /var/lib/signal-recorder/{data,analytics,upload}`

✅ **Organized Analytics**
- All derived data under `analytics/`
- Easy to regenerate from raw data if needed

✅ **Secure Credentials**
- All credentials under `/etc/signal-recorder/credentials/` with 0600 permissions
- Never co-located with deletable data

✅ **Standard FHS Locations**
- `/var/lib/` for application data
- `/etc/` for configuration
- `/var/log/` for logs
- No data in source tree or `/tmp/`

✅ **Upload State Isolated**
- Upload queue can be deleted without affecting recordings
- Clear what's "uploaded" vs "pending"

---

## Migration Plan

### Phase 1: Add Configuration (No Breaking Changes)

1. **Add new config options** to TOML:
   ```toml
   [recorder]
   archive_dir = "/var/lib/signal-recorder/data"
   analytics_dir = "/var/lib/signal-recorder/analytics"
   upload_state_dir = "/var/lib/signal-recorder/upload"
   status_dir = "/var/lib/signal-recorder/status"
   
   [paths]
   config_dir = "/etc/signal-recorder"
   credentials_dir = "/etc/signal-recorder/credentials"
   log_dir = "/var/log/signal-recorder"
   ```

2. **Update code** to respect new paths (with fallbacks to old paths)

### Phase 2: Migration Script

3. **Create migration script** (`scripts/migrate-data-storage.sh`):
   - Move existing data to new locations
   - Update config files
   - Set proper permissions
   - Verify integrity

### Phase 3: Cleanup Commands

4. **Add management commands**:
   ```bash
   signal-recorder clean-data      # Delete all RTP data
   signal-recorder clean-analytics # Delete derived analytics
   signal-recorder clean-uploads   # Clear upload queue
   signal-recorder clean-all       # Everything except site config
   ```

5. **Update documentation** with new file locations

---

## Immediate Actions Needed

### Priority 1 (Critical)
1. ✅ **Document current locations** (this file)
2. 🔧 **Move `/tmp/signal-recorder-stats.json`** to `/var/lib/signal-recorder/status/`
3. 🔧 **Separate credentials** from config files
4. 🔧 **Add `clean-data` command** for safe RTP data deletion

### Priority 2 (Important)
5. 🔧 **Implement analytics_dir** config option
6. 🔧 **Standardize WWV timing CSV** location
7. 🔧 **Add upload state management**

### Priority 3 (Nice to Have)
8. 🔧 **Implement full proposed structure**
9. 🔧 **Add data lifecycle policies** (age-based cleanup)
10. 🔧 **Add size monitoring and alerts**

---

## Code References

### Key Files to Modify

1. **`src/signal_recorder/grape_rtp_recorder.py`**
   - Line 36: `STATS_FILE` path
   - Line 1280: `archive_dir` usage
   - Line 850: WWV timing CSV path

2. **`src/signal_recorder/uploader.py`**
   - Line 62, 384: Upload queue path

3. **`src/signal_recorder/grape_metadata.py`**
   - Line 287-291: Quality metrics output
   - Line 312-313: Summary file output

4. **`web-ui/simple-server.js`**
   - Line 463-482: JSON database functions
   - Line 26: Daemon status path

5. **`src/signal_recorder/grape_recorder.py`**
   - Line 29-31: Config loading
   - Line 225: Archive directory logging

---

## Testing Strategy

### Before Migration
- [ ] Document all current file locations
- [ ] Create backup of all data
- [ ] Test data deletion scenarios
- [ ] Verify no credentials in deletable locations

### After Migration
- [ ] Verify all services start correctly
- [ ] Test data recording and retrieval
- [ ] Test web UI functionality
- [ ] Test upload queue persistence
- [ ] Verify credential separation
- [ ] Test clean-data command

---

## Appendix: File Inventory

### Files That Contain RTP Stream Data
```
/var/lib/signal-recorder/archive/**/*.h5
/var/lib/signal-recorder/archive/**/metadata/*.h5
{archive_dir}/**/*_quality.json
{archive_dir}/**/*_summary.txt
{archive_dir}/**/daily_report_*.txt
{project_root}/logs/wwv_timing.csv
/tmp/signal-recorder-stats.json
/var/lib/signal-recorder/upload_queue.json
```

### Files That Contain Site Management Data
```
web-ui/data/users.json              # Login credentials
web-ui/data/jwt-secret.txt          # JWT secret
web-ui/data/configurations.json     # Site configs
web-ui/data/channels.json           # Channel definitions
config/*.toml                       # Station config + SSH keys
```

### Safe to Delete (RTP Data Only)
```
rm -rf /var/lib/signal-recorder/archive/
rm -f /tmp/signal-recorder-stats.json
rm -f /var/lib/signal-recorder/upload_queue.json
rm -f {project_root}/logs/wwv_timing.csv
```

### Must NOT Delete (Site Management)
```
web-ui/data/users.json
web-ui/data/jwt-secret.txt
web-ui/data/configurations.json
web-ui/data/channels.json
config/*.toml (at least keep credentials portion)
```

---

**Status**: 🟡 ANALYSIS COMPLETE - AWAITING IMPLEMENTATION APPROVAL
