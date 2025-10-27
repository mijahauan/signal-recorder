# GRAPE Upload: wsprdaemon vs signal-recorder

## wsprdaemon Upload Process

### Directory Structure
```
wsprdaemon/wav-archive/
  └── YYYYMMDD/                           # Date
      └── CALLSIGN_GRID/                  # Reporter (e.g., AI6VN_CM87)
          └── RECEIVER@PSWS_ID_INST/      # Receiver (e.g., KA9Q_0@hamsci_123)
              └── WWV_2_5/                # Band
                  ├── *.wv                # Compressed 1-min files
                  └── 24_hour_10sps_iq.wav # 24-hour WAV (864,000 samples)
```

### Upload Workflow

1. **Trigger**: Runs on day **after** recording (not current UTC date)
   ```bash
   current_date=$(TZ=UTC printf "%(%Y%m%d)T" -1)
   if [[ "${reporter_wav_root_dir_date}" == "${current_date}" ]]; then
       echo "Skipping today's date"
       return 0
   fi
   ```

2. **Pre-Check**: Skip if already uploaded
   ```bash
   if [[ -f ${reporter_upload_complete_file_name} ]]; then
       echo "Already uploaded"
       return 0
   fi
   ```

3. **WAV Validation**: Check 24-hour WAV file
   ```bash
   soxi ${band_24hour_wav_file} | grep -q '864000 samples'
   ```

4. **Gap Repair**: Fill missing minutes with silence
   ```bash
   grape_repair_band_bad_compressed_files ${band_dir}
   ```

5. **Convert to Digital RF**:
   ```bash
   ${WAV2GRAPE_PYTHON_CMD} -i "${receiver_dir}" -o "${GRAPE_TMP_DIR}"
   ```

6. **SFTP Upload**:
   ```bash
   cd "${receiver_tmp_dir%/*}"
   sftp -v -l ${sftp_bw_limit_kbps} -b ${sftp_cmds_file} \
        "${psws_station_id}@${PSWS_SERVER_URL}"
   ```

7. **Trigger Directory**: Create completion marker on PSWS
   ```bash
   mkdir c${receiver_tmp_dir##*/}_#${psws_instrument_id}_#$(date -u +%Y-%m%dT%H-%M)
   ```

8. **Mark Complete**: Create local marker file
   ```bash
   touch "${reporter_upload_complete_file_name}"
   ```

---

## Our Implementation (signal-recorder)

### Current Status: ⚠️ NEEDS UPDATES

Our `uploader.py` has the **basic infrastructure** but needs wsprdaemon-compatible changes:

#### ✅ What We Have:
- SSH/rsync upload protocol
- Retry queue with exponential backoff
- Upload verification
- Persistent queue (survives restarts)

#### ❌ What's Missing:
1. **No 24-hour wait** - We might try to upload same-day data
2. **No completion marker file** - Won't skip already-uploaded days
3. **Wrong remote path format** - Not PSWS-compatible
4. **No trigger directory creation** - PSWS won't process upload
5. **SFTP instead of rsync** - wsprdaemon uses SFTP
6. **No bandwidth limiting** - Could saturate link

---

## Required Fixes

### Fix 1: Add 24-Hour Wait Check

```python
def should_upload_date(self, date: datetime.date) -> bool:
    """
    Check if date is ready for upload (must be previous day or earlier).
    wsprdaemon only uploads data from completed days.
    """
    today_utc = datetime.now(timezone.utc).date()
    return date < today_utc  # Only upload previous days
```

### Fix 2: Check for Completion Marker

```python
def is_already_uploaded(self, date: datetime.date, station_path: Path) -> bool:
    """
    Check if date has already been uploaded successfully.
    Looks for .upload_complete marker file.
    """
    marker_file = station_path / str(date) / ".upload_complete"
    return marker_file.exists()
```

### Fix 3: Fix Remote Path Format

**Current (WRONG)**:
```python
remote_path = f"{date}/{reporter}/{receiver}/{dataset_path.name}"
```

**wsprdaemon format (CORRECT)**:
```python
# Just upload to home directory, PSWS will organize by trigger dir
remote_path = dataset_path.name  # e.g., "OBS2025-10-27T00-00"
```

### Fix 4: Add SFTP Upload Protocol

```python
class SFTPUpload(UploadProtocol):
    """Upload via SFTP (wsprdaemon-compatible)"""
    
    def upload(self, local_path: Path, remote_path: str, metadata: Dict) -> bool:
        """Upload using SFTP with bandwidth limiting"""
        
        # Create trigger directory name
        obs_name = local_path.name  # e.g., OBS2025-10-27T00-00
        psws_instrument = metadata['instrument_id']
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m%dT%H-%M')
        trigger_dir = f"c{obs_name}_#{psws_instrument}_#{timestamp}"
        
        # Create SFTP commands file
        sftp_cmds = f"""
        put -r {local_path}
        mkdir {trigger_dir}
        """
        
        # Execute SFTP with bandwidth limit
        cmd = [
            "sftp",
            "-v",  # Verbose
            "-l", str(self.bandwidth_limit_kbps),  # Limit bandwidth
            "-b", sftp_cmds_file,  # Batch commands
            f"{metadata['psws_station_id']}@{self.psws_server_url}"
        ]
        
        # Run SFTP...
```

### Fix 5: Validate Digital RF Before Upload

```python
def validate_digital_rf(self, drf_path: Path) -> bool:
    """
    Verify Digital RF dataset is complete before upload.
    Check for 864,000 samples (10 Hz × 86,400 seconds).
    """
    import digital_rf as drf
    
    try:
        reader = drf.DigitalRFReader(str(drf_path))
        # Check sample count, completeness, etc.
        return True
    except Exception as e:
        logger.error(f"Digital RF validation failed: {e}")
        return False
```

---

## Testing Without 24-Hour Wait

### Option 1: Create Synthetic Test Data (RECOMMENDED)

```python
# test_upload.py - Create minimal Digital RF for testing

import numpy as np
import digital_rf as drf
from datetime import datetime, timezone, timedelta
from pathlib import Path

def create_test_digital_rf(output_dir: Path, date: datetime.date):
    """
    Create a minimal but valid Digital RF dataset for testing.
    Uses only 600 samples (1 minute) instead of 864,000 (24 hours).
    """
    # Calculate midnight UTC
    day_start = datetime.combine(date, datetime.min.time(), tzinfo=timezone.utc)
    start_global_index = int(day_start.timestamp() * 10)
    
    # Create minimal dataset (1 minute = 600 samples at 10 Hz)
    samples = np.random.randn(600) + 1j * np.random.randn(600)
    samples = samples.astype(np.complex64)
    
    # Write Digital RF
    channel_dir = output_dir / "WWV_2_5"
    channel_dir.mkdir(parents=True, exist_ok=True)
    
    with drf.DigitalRFWriter(
        str(channel_dir),
        dtype=np.complex64,
        subdir_cadence_secs=3600,
        file_cadence_millisecs=1000,
        start_global_index=start_global_index,
        sample_rate_numerator=10,
        sample_rate_denominator=1,
        uuid_str="test-uuid-12345",
        compression_level=6,
        checksum=False,
        is_complex=True,
        num_subchannels=1,
        is_continuous=True,
        marching_periods=False
    ) as writer:
        writer.rf_write(samples)
    
    # Write metadata
    metadata_dir = channel_dir / 'metadata'
    metadata_dir.mkdir(parents=True, exist_ok=True)
    
    metadata = {
        'callsign': 'TESTCALL',
        'grid_square': 'EM00',
        'receiver_name': 'test_receiver',
        'center_frequencies': np.array([2500000.0], dtype=np.float64),
        'uuid_str': "test-uuid-12345"
    }
    
    with drf.DigitalMetadataWriter(
        str(metadata_dir),
        subdir_cadence_secs=3600,
        file_cadence_secs=3600,
        sample_rate_numerator=10,
        sample_rate_denominator=1,
        file_name='metadata'
    ) as metadata_writer:
        metadata_writer.write(start_global_index, metadata)
    
    print(f"✅ Created test Digital RF at {channel_dir}")
    return channel_dir

if __name__ == "__main__":
    # Create test data for yesterday
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    test_dir = Path("/tmp/grape_test_upload")
    
    create_test_digital_rf(test_dir, yesterday)
    print(f"\\nTest data ready for upload testing")
    print(f"Date: {yesterday}")
    print(f"Path: {test_dir}")
```

### Option 2: Mock the Date Check

```python
# For testing only - skip date validation
class UploadManager:
    def __init__(self, config: Dict, storage_manager, test_mode=False):
        self.test_mode = test_mode
        ...
    
    def should_upload_date(self, date: datetime.date) -> bool:
        if self.test_mode:
            return True  # Allow upload of any date
        
        # Normal: only previous days
        today_utc = datetime.now(timezone.utc).date()
        return date < today_utc
```

### Option 3: Override System Date (Advanced)

```bash
# Use faketime to make system think it's tomorrow
faketime 'tomorrow' python test_upload.py
```

---

## Test Plan

### Step 1: Create Test Digital RF
```bash
cd ~/git/signal-recorder
python3 test_upload.py
```

### Step 2: Configure SFTP Access
```bash
# Generate SSH key for PSWS (if not exists)
ssh-keygen -t ed25519 -f ~/.ssh/psws_upload_key

# Get PSWS credentials from wsprdaemon config
grep -A 5 "PSWS" ~/wsprdaemon/wsprdaemon.conf
```

### Step 3: Test SFTP Connectivity
```bash
# Test manual SFTP connection
sftp -i ~/.ssh/psws_upload_key <station_id>@pswsnetwork.eng.ua.edu

# If successful, you should see sftp> prompt
# Type 'ls' to list files, 'quit' to exit
```

### Step 4: Update signal-recorder Config
```yaml
upload:
  enabled: true
  protocol: "sftp"  # Change from ssh_rsync
  host: "pswsnetwork.eng.ua.edu"
  user: "<your_psws_station_id>"
  ssh:
    key_file: "/home/mjh/.ssh/psws_upload_key"
  bandwidth_limit_kbps: 100
  test_mode: true  # Allows uploading current day
```

### Step 5: Run Upload Test
```bash
# Start daemon with test data
signal-recorder-daemon --test-upload /tmp/grape_test_upload
```

### Step 6: Verify on PSWS
- Check PSWS web dashboard
- Verify trigger directory was created
- Confirm data processing started

---

## Success Criteria

✅ Test Digital RF created (600 samples minimum)  
✅ SFTP connection successful  
✅ Data uploaded to PSWS home directory  
✅ Trigger directory created (`c<OBS>_#<INST>_#<TIMESTAMP>`)  
✅ PSWS processes data (check dashboard)  
✅ Local marker file created (`.upload_complete`)  
✅ Second upload attempt skipped (already complete)  

---

## Next Steps

1. **Implement SFTP protocol** in `uploader.py`
2. **Add 24-hour wait logic**
3. **Create test script** for synthetic data
4. **Test with PSWS staging server** (if available)
5. **Monitor first real 24-hour upload**

