# GRAPE Upload Implementation Guide

**Date:** November 6, 2025  
**Purpose:** Ensure GRAPE recorder produces PSWS-compatible data format

---

## 1. wsprdaemon Signal Path Analysis

### Data Flow (wsprdaemon)

```
Raw IQ (16 kHz from radiod)
    ↓ Decimate to 10 Hz complex IQ
24-hour WAV files (864,000 samples @ 10 Hz)
    ↓ wav2grape.py conversion
Digital RF dataset
    ↓ SFTP upload
PSWS server (pswsnetwork.eng.ua.edu)
```

### wsprdaemon Directory Structure

**Local storage:**
```
wav-archive/
└── YYYYMMDD/
    └── CALLSIGN_GRID/
        └── RECEIVER@SITEID_INSTRUMENTID/
            └── WWV_2_5/
                └── 24_hour_10sps_iq.wav
```

**Digital RF output (temporary):**
```
/tmp/grape/
└── CALLSIGN_GRID/
    └── OBSYYYY-MM-DDTHH-MM/
        └── ch0/
            ├── YYYY-MM-DDTHH-MM-SS/
            │   └── rf@<timestamp>.h5
            └── metadata/
                └── YYYY-MM-DDTHH-MM-SS/
                    └── metadata@<timestamp>.h5
```

**PSWS upload:**
```
SFTP to: SITEID@pswsnetwork.eng.ua.edu

Uploaded directory: CALLSIGN_GRID/OBSYYYY-MM-DDTHH-MM/
Trigger directory:  cOBSYYYY-MM-DDTHH-MM_#INSTRUMENTID_#YYYY-MM-DDTHH-MM
```

### Critical wsprdaemon Parameters

From `wav2grape.conf`:
```ini
[global]
channel name = ch0
subdir cadence secs = 86400      # 24-hour subdirectories
file cadence millisecs = 3600000  # 1-hour files
compression level = 9
```

From `wav2grape.py`:
```python
# Digital RF parameters
dtype = 'i2' or 'float32'  # Based on WAV format
sample_rate = 10 Hz
num_channels = 2 (IQ)
is_complex = True
num_subchannels = N (number of frequencies)
compression_level = 9
```

**Metadata fields (CRITICAL):**
- `callsign`
- `grid_square`
- `receiver_name`
- `center_frequencies` - numpy array of all frequencies
- `lat` / `long` - np.single precision
- `uuid_str` - dataset UUID

---

## 2. GRAPE Recorder vs wsprdaemon Comparison

### ✅ What MATCHES

| Feature | wsprdaemon | GRAPE Recorder | Status |
|---------|------------|----------------|--------|
| Sample rate | 10 Hz complex IQ | 10 Hz complex IQ | ✅ MATCH |
| Data format | Digital RF | Digital RF | ✅ MATCH |
| Decimation | 16kHz → 10Hz | 16kHz → 10Hz | ✅ MATCH |
| Data type | complex64 | complex64 | ✅ MATCH |
| Metadata | HDF5 sidecar | HDF5 sidecar | ✅ MATCH |

### ⚠️ What DIFFERS

| Parameter | wsprdaemon | GRAPE Recorder | Impact |
|-----------|------------|----------------|--------|
| **File cadence** | 3600000 ms (1 hour) | 1000 ms (1 second) | ⚠️ MISMATCH |
| **Subdir cadence** | 86400 s (24 hours) | 3600 s (1 hour) | ⚠️ MISMATCH |
| **Channel name** | `ch0` (hardcoded) | Variable by frequency | ⚠️ DIFFERENT |
| **Directory structure** | `CALLSIGN_GRID/OBSTIME/ch0/` | `YYYYMMDD/CALLSIGN_GRID/CHANNEL/` | ⚠️ DIFFERENT |
| **Upload trigger** | Trigger directory on PSWS | Not implemented | ❌ MISSING |
| **Compression** | Level 9 | Level 1 (default) | ⚠️ DIFFERENT |

### ❌ What's MISSING in GRAPE Recorder

1. **SFTP upload mechanism** - Exists in code but disabled
2. **PSWS trigger directory creation** - Required for PSWS to process data
3. **wsprdaemon-compatible directory naming** - PSWS expects specific format
4. **Completion marker** - `.upload_complete` file
5. **Multi-frequency metadata** - wsprdaemon includes ALL frequencies in single metadata

---

## 3. Required Changes for PSWS Compatibility

### Priority 1: Critical for Upload

**A. Match wsprdaemon Digital RF Parameters**

Change in `grape_rtp_recorder.py` line ~1220:

```python
# BEFORE (current)
with drf.DigitalRFWriter(
    str(drf_dir),
    dtype=np.complex64,
    subdir_cadence_secs=3600,        # 1 hour
    file_cadence_millisecs=1000,      # 1 second
    compression_level=1,              # Low compression
    ...
)

# AFTER (wsprdaemon-compatible)
with drf.DigitalRFWriter(
    str(drf_dir),
    dtype=np.complex64,
    subdir_cadence_secs=86400,        # 24 hours (CRITICAL!)
    file_cadence_millisecs=3600000,   # 1 hour files (CRITICAL!)
    compression_level=9,              # High compression (bandwidth savings)
    ...
)
```

**B. Directory Structure**

Current:
```
/tmp/grape-test/data/20251106/AC0G_EM38ww/WWV_2_5/
```

Required for PSWS:
```
/tmp/grape-test/AC0G_EM38ww/OBS2025-11-06T00-00/ch0/
```

**C. SFTP Upload with Trigger**

```python
# After uploading DRF tree:
trigger_dir = f"cOBS{timestamp}_#{instrument_id}_#{upload_timestamp}"
sftp.mkdir(trigger_dir)  # This signals PSWS to process the data
```

### Priority 2: Enhanced Compatibility

**D. Multi-Channel Metadata**

wsprdaemon includes ALL frequencies in a single metadata file:
```python
metadata['center_frequencies'] = np.array([2.5e6, 5e6, 10e6, ...])
```

GRAPE recorder currently: One metadata file per frequency

**E. Metadata Field Mapping**

Ensure all wsprdaemon fields are present:
- `uuid_str` - Dataset UUID
- `callsign` - Station callsign
- `grid_square` - Maidenhead grid
- `receiver_name` - Instrument identifier
- `lat` / `long` - Location (np.single)
- `center_frequencies` - All monitored frequencies

---

## 4. Upload Configuration

### grape-config.toml Updates Needed

```toml
[uploader]
enabled = true  # ← Change from false
protocol = "sftp"  # ← Not rsync! PSWS requires SFTP
upload_time = "00:30"
upload_timezone = "UTC"

[uploader.sftp]
host = "pswsnetwork.eng.ua.edu"
port = 22
user = "S000171"  # ← Station ID (from station.id)
ssh_key = "/home/mjh/.ssh/id_ed25519"  # ← Your SSH key
remote_base_path = "/"  # ← PSWS expects upload to home directory
bandwidth_limit_kbps = 100  # ← wsprdaemon uses 100 kbps
create_trigger_directory = true  # ← CRITICAL!
trigger_format = "cOBS{obs_time}_#{instrument_id}_#{upload_time}"
```

### Authentication

You already have SSH key set up (`~/.ssh/id_ed25519.pub`). You need to:

1. Send public key to PSWS administrators
2. Verify autologin works:
```bash
sftp -o ConnectTimeout=20 S000171@pswsnetwork.eng.ua.edu
```

---

## 5. Implementation Checklist

- [ ] Update Digital RF parameters to match wsprdaemon (24h subdirs, 1h files, compress=9)
- [ ] Implement directory naming: `CALLSIGN_GRID/OBSYYYY-MM-DDTHH-MM/ch0/`
- [ ] Add multi-frequency metadata support
- [ ] Implement SFTP upload module (adapt existing rsync code)
- [ ] Add trigger directory creation
- [ ] Test with sample dataset locally
- [ ] Dry-run upload to verify PSWS accepts format
- [ ] Enable continuous uploads

---

## 6. Testing Before Production

### Local Validation

```bash
# Generate 24-hour test dataset
python3 -c "
import digital_rf as drf
import numpy as np
from pathlib import Path

# Create wsprdaemon-compatible test data
drf_dir = Path('/tmp/test-grape/AC0G_EM38ww/OBS2025-11-06T00-00/ch0')
drf_dir.mkdir(parents=True, exist_ok=True)

with drf.DigitalRFWriter(
    str(drf_dir),
    dtype=np.complex64,
    subdir_cadence_secs=86400,
    file_cadence_millisecs=3600000,
    start_global_index=0,
    sample_rate_numerator=10,
    sample_rate_denominator=1,
    uuid_str='test-uuid',
    compression_level=9,
    is_complex=True,
    num_subchannels=1
) as writer:
    # Write 1 hour of test data
    test_data = np.random.randn(36000) + 1j*np.random.randn(36000)
    writer.rf_write(test_data.astype(np.complex64))
"

# Verify format
python3 -c "
import digital_rf as drf
reader = drf.DigitalRFReader('/tmp/test-grape/AC0G_EM38ww/OBS2025-11-06T00-00')
print('Channels:', reader.get_channels())
print('Sample rate:', reader.get_properties('ch0')['sample_rate_numerator'])
"
```

### Upload Test

```bash
# Dry run to PSWS (if you have access)
sftp S000171@pswsnetwork.eng.ua.edu <<EOF
cd /
put -r /tmp/test-grape/AC0G_EM38ww/OBS2025-11-06T00-00
mkdir cOBS2025-11-06T00-00_#172_#$(date -u +%Y-%m-%dT%H-%M)
quit
EOF
```

---

## References

- **wsprdaemon source**: `/home/mjh/git/wsprdaemon/wav2grape.py`
- **wsprdaemon config**: `/home/mjh/git/wsprdaemon/wav2grape.conf`
- **PSWS server**: `pswsnetwork.eng.ua.edu`
- **Station ID**: S000171
- **Instrument ID**: 172

---

**Next Steps**: Implement Priority 1 changes, then test with sample data before enabling uploads.
