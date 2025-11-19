# Web-UI / Analytics Synchronization Protocol

**Problem**: The web-ui repeatedly falls out of sync with analytics service, even for basic features like data storage paths. Changes to analytics (Python) break web-ui (Node.js) monitoring.

**Solution**: Centralized path management with automated validation.

---

## Architecture

### Single Source of Truth: GRAPEPaths API

Both Python and JavaScript implementations must stay synchronized:

- **Python**: `src/signal_recorder/paths.py`
- **JavaScript**: `web-ui/grape-paths.js`

### Directory Structure (Current)

```
data_root/
├── archives/{CHANNEL}/                  - Raw 16 kHz NPZ files
├── analytics/{CHANNEL}/
│   ├── decimated/                       - 10 Hz NPZ files (pre-DRF conversion)
│   ├── digital_rf/                      - Digital RF HDF5 files
│   ├── discrimination/                  - WWV/WWVH analysis CSVs
│   ├── quality/                         - Quality metrics CSVs
│   ├── logs/                            - Processing logs
│   └── status/                          - Runtime status JSON
├── spectrograms/{YYYYMMDD}/             - PNG spectrograms
├── state/                               - Service persistence (time_snap, etc.)
└── status/                              - System-wide status
```

---

## Mandatory Protocol for All Changes

### Rule 1: Update Both Implementations Simultaneously

When adding/changing paths:

1. **Update Python** (`paths.py`):
   ```python
   def get_new_feature_dir(self, channel_name: str) -> Path:
       """Get new feature directory."""
       return self.get_analytics_dir(channel_name) / 'new_feature'
   ```

2. **Update JavaScript** (`grape-paths.js`):
   ```javascript
   getNewFeatureDir(channelName) {
       return join(this.getAnalyticsDir(channelName), 'new_feature');
   }
   ```

3. **Update documentation** in both file headers with directory tree

### Rule 2: Validate Before Committing

**Always run validation script before committing:**

```bash
./scripts/validate-paths-sync.sh
```

This ensures Python and JavaScript produce identical paths.

### Rule 3: Never Use Hardcoded Paths

❌ **BAD** (hardcoded):
```javascript
const discriminationDir = join(dataRoot, 'analytics', channelDir, 'discrimination');
```

✅ **GOOD** (centralized):
```javascript
const discriminationDir = paths.getDiscriminationDir(channelName);
```

### Rule 4: Deprecate Old Code

When creating new versions:
1. Add deprecation warnings to old files
2. Update all shell scripts to use new version
3. Document migration path

**Example**: `monitoring-server.js` → `monitoring-server-v3.js`

---

## Common Sync Issues & Solutions

### Issue 1: New Analytics Output Directory

**Symptom**: Analytics creates `analytics/{CHANNEL}/new_output/` but web-ui can't find it.

**Fix**:
1. Add `get_new_output_dir()` to both `paths.py` and `grape-paths.js`
2. Run `validate-paths-sync.sh`
3. Update web-ui code to use `paths.getNewOutputDir()`

### Issue 2: Path Format Changes

**Symptom**: Analytics changes filename format (e.g., adds date subdirectory) but web-ui uses old format.

**Fix**:
1. Update path generation logic in both implementations
2. Add tests to `validate-paths-sync.sh` for the new format
3. Update web-ui API endpoints to use new paths

### Issue 3: Multiple Data Formats

**Symptom**: Analytics outputs multiple formats (CSV + JSON) but web-ui only knows about CSV.

**Fix**:
1. Add separate path methods for each format
2. Document expected files in path method docstrings
3. Web-ui should gracefully handle missing formats

---

## Web-UI Server Selection

### Current Servers

- **`monitoring-server-v3.js`** (RECOMMENDED) - Uses GRAPEPaths API
- **`monitoring-server.js`** (DEPRECATED) - Hardcoded paths

### Usage

**Startup scripts automatically use v3:**
```bash
./start-dual-service.sh    # Uses monitoring-server-v3.js
./restart-webui.sh         # Uses monitoring-server-v3.js
```

**Manual usage:**
```bash
cd web-ui
node monitoring-server-v3.js
```

---

## Validation Script Reference

### Script: `scripts/validate-paths-sync.sh`

**Purpose**: Ensure Python and JavaScript GRAPEPaths produce identical paths.

**When to Run**:
- After modifying `paths.py`
- After modifying `grape-paths.js`
- Before committing path-related changes
- In CI/CD pipeline (future)

**Output**:
```
✅ SUCCESS: Python and JavaScript paths are identical!

All path methods tested:
  ✓ analytics_dir
  ✓ decimated_dir
  ✓ digital_rf_dir
  ✓ discrimination_dir
  ...
```

**Failure Example**:
```
❌ FAILURE: Path mismatch detected!

Differences:
< "decimated_dir": "/tmp/test/analytics/WWV_10_MHz/decimated",
> "decimated_dir": "/tmp/test/analytics/WWV_10_MHz/decim",
```

---

## Adding New Path Methods: Step-by-Step

### Example: Adding Support for Carrier Quality Metrics

**Step 1**: Decide on path structure
```
analytics/{CHANNEL}/carrier_quality/{YYYYMMDD}_carrier_quality.csv
```

**Step 2**: Add to Python (`paths.py`)
```python
def get_carrier_quality_dir(self, channel_name: str) -> Path:
    """Get carrier-specific quality metrics directory.
    
    Returns: {data_root}/analytics/{CHANNEL}/carrier_quality/
    """
    return self.get_analytics_dir(channel_name) / 'carrier_quality'

def get_carrier_quality_file(self, channel_name: str, date: str) -> Path:
    """Get carrier quality CSV for specific date.
    
    Args:
        channel_name: Channel name
        date: Date in YYYYMMDD format
    
    Returns: {data_root}/analytics/{CHANNEL}/carrier_quality/{date}_carrier_quality.csv
    """
    return self.get_carrier_quality_dir(channel_name) / f"{date}_carrier_quality.csv"
```

**Step 3**: Add to JavaScript (`grape-paths.js`)
```javascript
/**
 * Get carrier-specific quality metrics directory.
 * 
 * @param {string} channelName - Channel name
 * @returns {string} Path: {data_root}/analytics/{CHANNEL}/carrier_quality/
 */
getCarrierQualityDir(channelName) {
    return join(this.getAnalyticsDir(channelName), 'carrier_quality');
}

/**
 * Get carrier quality CSV for specific date.
 * 
 * @param {string} channelName - Channel name
 * @param {string} date - Date in YYYYMMDD format
 * @returns {string} Path: {data_root}/analytics/{CHANNEL}/carrier_quality/{date}_carrier_quality.csv
 */
getCarrierQualityFile(channelName, date) {
    return join(this.getCarrierQualityDir(channelName), `${date}_carrier_quality.csv`);
}
```

**Step 4**: Update validation script
```bash
# Edit /tmp/test-python-paths.py to add:
"carrier_quality_dir": str(paths.get_carrier_quality_dir(test_channel)),
"carrier_quality_file": str(paths.get_carrier_quality_file(test_channel, test_date)),

# Edit /tmp/test-js-paths.mjs to add:
carrier_quality_dir: paths.getCarrierQualityDir(testChannel),
carrier_quality_file: paths.getCarrierQualityFile(testChannel, testDate),
```

**Step 5**: Validate
```bash
./scripts/validate-paths-sync.sh
# Should show ✓ carrier_quality_dir and ✓ carrier_quality_file
```

**Step 6**: Update analytics to use new paths
```python
from signal_recorder.paths import GRAPEPaths
paths = GRAPEPaths(data_root)
output_file = paths.get_carrier_quality_file(channel_name, date_str)
```

**Step 7**: Update web-ui to use new paths
```javascript
import { GRAPEPaths } from './grape-paths.js';
const paths = new GRAPEPaths(dataRoot);
const qualityFile = paths.getCarrierQualityFile(channelName, dateStr);
```

---

## Carrier Channel NTP Timing (Special Case)

### Background

From SESSION_2025-11-17_FINAL_SUMMARY.md:
- RTP offset correlation proven **UNSTABLE** (std dev 1.2B samples)
- Each ka9q-radio channel has independent RTP clock
- **Decision**: Use NTP_SYNCED timing for carrier channels (±10ms accuracy)

### Timing Quality Hierarchy

| Quality Level | Accuracy | Applicable To | Method |
|--------------|----------|---------------|--------|
| **TONE_LOCKED** | ±1ms | Wide channels (16 kHz) | WWV/CHU tone detection + time_snap |
| **NTP_SYNCED** | ±10ms | Carrier channels (200 Hz) | System clock with NTP validation |
| **WALL_CLOCK** | ±seconds | Fallback | Unsynchronized system clock |

### Implementation Status

**Analytics Service** (`analytics_service.py`):
- `RTPOffsetTracker` class exists but proven unviable
- NTP validation methods: `_get_ntp_offset()` (lines 105-134)

**Core Recorder** (`core_recorder.py`):
- Needs NTP status capture for carrier channels
- Store in per-minute metadata: `ntp_synchronized`, `ntp_offset_ms`, `ntp_stratum`

**Web-UI**:
- Display NTP status on carrier channel quality dashboard
- Path: Use existing `paths.getQualityDir()` for carrier quality CSVs

### Implementation TODO

1. **Core Recorder**: Add NTP capture for carrier channels
   - Use existing `_validate_ntp_sync()` logic from analytics_service.py
   - Store in NPZ metadata alongside RTP timestamps

2. **Analytics Service**: Generate carrier quality CSVs
   - Parse NTP metadata from carrier NPZ files
   - Output: `analytics/{CHANNEL}/quality/{date}_carrier_quality.csv`

3. **Web-UI**: Add carrier quality display
   - New page or section showing NTP status trends
   - Use `paths.getQualityDir(channelName)` to find CSVs

---

## Best Practices

### 1. Document Path Semantics

Always document what files live at each path:

```python
def get_quality_dir(self, channel_name: str) -> Path:
    """Get quality metrics directory.
    
    Expected files:
        - {YYYYMMDD}_quality.csv (per-minute completeness, gaps, SNR)
        - {YYYYMMDD}_carrier_quality.csv (carrier-specific: NTP status)
    
    Returns: {data_root}/analytics/{CHANNEL}/quality/
    """
```

### 2. Use Type Hints (Python) and JSDoc (JavaScript)

Makes autocomplete work and catches errors early.

### 3. Test with Real Data Paths

Validation script uses synthetic paths. Also manually verify:
```bash
# Check actual data structure
tree -L 4 /tmp/grape-test/analytics/
```

### 4. Graceful Degradation

Web-UI should handle missing directories/files gracefully:
```javascript
if (!fs.existsSync(discriminationFile)) {
    return { error: 'No data available for this date' };
}
```

---

## Migration Guide: Old Code → GRAPEPaths

### Pattern 1: Archive Paths

**Before**:
```javascript
const archiveDir = join(dataRoot, 'archives', channelDir);
```

**After**:
```javascript
const archiveDir = paths.getArchiveDir(channelName);
```

### Pattern 2: Analytics Paths

**Before**:
```javascript
const discriminationFile = join(dataRoot, 'analytics', channelDir, 
                                'discrimination', `${channelName}_${date}.csv`);
```

**After**:
```javascript
const discriminationDir = paths.getDiscriminationDir(channelName);
const discriminationFile = join(discriminationDir, `${channelName}_${date}.csv`);
```

### Pattern 3: State Files

**Before**:
```python
state_file = Path(data_root) / 'state' / f'analytics-{channel_key}.json'
```

**After**:
```python
state_file = paths.get_analytics_state_file(channel_name)
```

---

## Summary

**Key Takeaways**:

1. ✅ **Always use GRAPEPaths API** for all file paths
2. ✅ **Update both Python and JavaScript** when adding paths
3. ✅ **Run validation script** before committing
4. ✅ **Use monitoring-server-v3.js** (not the deprecated version)
5. ✅ **Document new paths** in method docstrings
6. ✅ **Carrier channels use NTP timing** (not RTP correlation)

**Result**: Web-UI stays synchronized with analytics automatically.

---

## References

- **Python API**: `src/signal_recorder/paths.py`
- **JavaScript API**: `web-ui/grape-paths.js`
- **Validation Script**: `scripts/validate-paths-sync.sh`
- **Carrier Timing Decision**: `SESSION_2025-11-17_FINAL_SUMMARY.md`
- **Config Structure**: `config/grape-config.toml` (lines 27-41)
