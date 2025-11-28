# GRAPEPaths API Quick Reference

**⚠️ CRITICAL**: When adding/changing analytics paths, update BOTH implementations.

---

## Quick Checklist

Adding a new path? Follow these steps:

- [ ] 1. Update `src/signal_recorder/paths.py` (Python)
- [ ] 2. Update `web-ui/grape-paths.js` (JavaScript)
- [ ] 3. Run `./scripts/validate-paths-sync.sh`
- [ ] 4. Use new path in analytics code
- [ ] 5. Use new path in web-ui code
- [ ] 6. Commit both files together

---

## Common Paths

### Archives (Raw 16 kHz NPZ)
```python
# Python
paths.get_archive_dir(channel_name)  # → {data_root}/archives/{CHANNEL}/
```
```javascript
// JavaScript
paths.getArchiveDir(channelName)     // → {dataRoot}/archives/{CHANNEL}/
```

### Analytics Products
```python
# Python
paths.get_analytics_dir(channel_name)           # Base directory
paths.get_decimated_dir(channel_name)           # 10 Hz NPZ (pre-DRF)
paths.get_digital_rf_dir(channel_name)          # Digital RF HDF5
paths.get_discrimination_dir(channel_name)      # Final weighted voting CSVs
paths.get_bcd_discrimination_dir(channel_name)  # BCD 100 Hz correlation CSVs
paths.get_tone_detections_dir(channel_name)     # 1000/1200 Hz tone CSVs
paths.get_tick_windows_dir(channel_name)        # 5ms tick analysis CSVs
paths.get_station_id_440hz_dir(channel_name)    # 440 Hz station ID CSVs
paths.get_quality_dir(channel_name)             # Quality CSVs
```
```javascript
// JavaScript
paths.getAnalyticsDir(channelName)
paths.getDecimatedDir(channelName)
paths.getDigitalRFDir(channelName)
paths.getDiscriminationDir(channelName)
paths.getBcdDiscriminationDir(channelName)
paths.getToneDetectionsDir(channelName)
paths.getTickWindowsDir(channelName)
paths.getStationId440hzDir(channelName)
paths.getQualityDir(channelName)
```

### Spectrograms
```python
# Python
paths.get_spectrograms_root()
paths.get_spectrograms_date_dir(date)     # date = "20251117"
paths.get_spectrogram_path(channel, date, spec_type='carrier')
```
```javascript
// JavaScript
paths.getSpectrogramsRoot()
paths.getSpectrogramsDateDir(date)
paths.getSpectrogramPath(channel, date, 'carrier')
```

### State & Status
```python
# Python
paths.get_state_dir()
paths.get_analytics_state_file(channel_name)  # time_snap, etc.
paths.get_status_dir()
```
```javascript
// JavaScript
paths.getStateDir()
paths.getAnalyticsStateFile(channelName)
paths.getStatusDir()
```

---

## Usage Examples

### Python (Analytics Service)
```python
from signal_recorder.paths import GRAPEPaths

paths = GRAPEPaths('/tmp/grape-test')
output_dir = paths.get_decimated_dir('WWV 10 MHz')
output_file = output_dir / f"{timestamp}_iq_10hz.npz"
```

### JavaScript (Web-UI)
```javascript
import { GRAPEPaths } from './grape-paths.js';

const paths = new GRAPEPaths(dataRoot);
const decimatedDir = paths.getDecimatedDir('WWV 10 MHz');
const files = fs.readdirSync(decimatedDir);
```

---

## ❌ Anti-Patterns (DO NOT DO THIS)

### Hardcoded Paths
```javascript
// ❌ BAD - Will break when paths change
const dir = join(dataRoot, 'analytics', 'WWV_10_MHz', 'decimated');

// ✅ GOOD - Uses centralized API
const dir = paths.getDecimatedDir('WWV 10 MHz');
```

### Inconsistent Naming
```python
# ❌ BAD - Different format than API
channel_dir = channel_name.replace(' ', '-').lower()

# ✅ GOOD - Use API helper
from signal_recorder.paths import channel_name_to_dir
channel_dir = channel_name_to_dir(channel_name)
```

---

## Validation

```bash
# Run after ANY path changes
./scripts/validate-paths-sync.sh

# Expected output:
# ✅ SUCCESS: Python and JavaScript paths are identical!
```

---

## Full Documentation

See `WEB_UI_ARCHITECTURE.md` for:
- Complete protocol and rules
- Step-by-step examples
- Migration guide
- Troubleshooting

---

## Emergency Fix: Web-UI Out of Sync

If web-ui can't find data:

1. Check which monitoring server is running:
   ```bash
   ps aux | grep monitoring-server
   ```

2. If it's the old one, restart with v3:
   ```bash
   pkill -f monitoring-server
   cd web-ui
   node monitoring-server-v3.js
   ```

3. Verify paths match analytics:
   ```bash
   ./scripts/validate-paths-sync.sh
   ```

4. Check data actually exists:
   ```bash
   tree -L 4 /tmp/grape-test/analytics/
   ```
