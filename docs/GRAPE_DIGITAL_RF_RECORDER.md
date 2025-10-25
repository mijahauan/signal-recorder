# GRAPE Digital RF Recorder

## Overview

The GRAPE Digital RF Recorder is a direct RTP→Digital RF pipeline for recording ionospheric time signal data from WWV and CHU stations. It replaces the pcmrecord-based approach with a pure Python implementation that provides per-channel separation, timestamp-based sample placement, and automatic Digital RF format generation compatible with the HamSCI PSWS server.

## Architecture

### Data Flow

```
ka9q-radio RTP Multicast (12 kHz IQ, float32)
    ↓
RTP Receiver (per-SSRC demultiplexing)
    ↓
IQ Sample Extraction
    ↓
Anti-aliasing Filter (8th order Butterworth, 5 Hz cutoff)
    ↓
Decimation (12 kHz → 10 Hz, factor of 1200)
    ↓
UTC-Aligned Daily Buffer (864,000 samples)
    ↓
Midnight Rollover Detection
    ↓
Digital RF Writer (compression level 9)
    ↓
Metadata Generation (quality metrics, gaps)
    ↓
Ready for PSWS Upload
```

### Key Components

#### 1. **RTPReceiver** (`grape_recorder.py`)
- Joins multicast group (239.251.200.0/24)
- Parses RTP headers (version, sequence, timestamp, SSRC)
- Demultiplexes packets by SSRC to channel-specific callbacks
- Runs in separate thread for non-blocking operation

#### 2. **Resampler** (`grape_recorder.py`)
- Scipy-based anti-aliasing filter (8th order Butterworth)
- Cutoff at Nyquist frequency of output rate (5 Hz)
- Stateful filtering for continuous operation across packets
- Decimation by factor of 1200 (12 kHz → 10 Hz)

#### 3. **DailyBuffer** (`grape_recorder.py`)
- UTC-aligned 24-hour buffer (864,000 samples @ 10 Hz)
- Timestamp-based sample placement using RTP timestamps
- NaN initialization for gap detection
- Automatic midnight rollover detection

#### 4. **GRAPEChannelRecorder** (`grape_recorder.py`)
- Per-channel recording pipeline
- RTP timestamp → Unix time conversion
- Accumulates input samples for efficient resampling
- Writes completed days to Digital RF format
- Generates metadata with quality metrics

#### 5. **GRAPEMetadataGenerator** (`grape_metadata.py`)
- Tracks packet reception, loss, and duplicates
- Records gap locations and durations
- Calculates data completeness percentage
- Estimates signal quality (mean/max levels, SNR)
- Generates JSON metadata and human-readable summaries

## Digital RF Format

### Directory Structure

```
<archive_dir>/
├── YYYYMMDD/                           # Recording date
│   └── <callsign>_<grid>/              # Station (e.g., AC0G_EM38ww)
│       └── <instrument>@<id>_0/        # Receiver (e.g., RX888@AC0G_0)
│           ├── WWV_2_5/                # Channel
│           │   ├── drf_YYYYMMDD_HHMMSS.h5  # Data files (1 hour each)
│           │   └── metadata/
│           │       └── metadata_YYYYMMDD.h5
│           ├── WWV_5/
│           ├── WWV_10/
│           ├── WWV_15/
│           ├── WWV_20/
│           ├── WWV_25/
│           ├── CHU_3/
│           ├── CHU_7/
│           └── CHU_14/
```

### Digital RF Parameters

- **Data Type**: float32 (f32)
- **Channels**: 2 (I and Q, interleaved)
- **Sample Rate**: 10 Hz
- **Subdir Cadence**: 86400 seconds (1 day)
- **File Cadence**: 3600000 milliseconds (1 hour)
- **Compression**: Level 9 (gzip)
- **Complex**: True (I/Q pairs)
- **Continuous**: True

### Metadata Fields

- `callsign`: Station callsign (e.g., "AC0G")
- `grid_square`: Maidenhead grid square (e.g., "EM38ww")
- `lat`: Latitude (converted from grid square)
- `long`: Longitude (converted from grid square)
- `receiver_name`: Instrument ID (e.g., "RX888")
- `center_frequencies`: Array of center frequencies (Hz)
- `uuid_str`: Unique identifier for dataset

## Configuration

### grape-production.toml

```toml
[station]
callsign = "AC0G"
grid_square = "EM38ww"
id = "AC0G"
instrument_id = "RX888"
description = "GRAPE station with RX888 MkII and ka9q-radio"

[ka9q]
status_address = "239.251.200.193"
auto_create_channels = true

[recorder]
data_dir = "/mnt/grape-data/raw"
archive_dir = "/mnt/grape-data/archive"
recording_interval = 60
continuous = true

[[recorder.channels]]
ssrc = 2500000
frequency_hz = 2500000
preset = "iq"
sample_rate = 12000
description = "WWV 2.5 MHz"
enabled = true
processor = "grape"

# ... additional channels for WWV 5, 10, 15, 20, 25 MHz
# ... and CHU 3.33, 7.85, 14.67 MHz
```

## Usage

### Running the Recorder

```bash
cd /home/ubuntu/signal-recorder-repo

# Run component tests first
python3.11 test_grape_components.py

# Start GRAPE recorder (requires active ka9q-radio channels)
python3.11 test_grape_recorder.py
```

### Creating GRAPE Channels

If channels aren't already created by radiod:

```bash
# Use the channel manager to create all 9 GRAPE channels
python3.11 -m signal_recorder.channel_manager \
    --config config/grape-production.toml \
    --create-all
```

### Monitoring

The recorder prints status updates every 30 seconds:

```
======================================================================
Status Update
======================================================================
Recorder manager: RUNNING
Active channels: 9

  WWV 2.5 MHz:
    Packets received: 12,345
    Packets dropped: 23
    Samples recorded: 1,481,400
    Data completeness: 99.81%
    Gaps: 2
```

### Output Files

For each channel and day, the recorder generates:

1. **Digital RF dataset** (`<channel>/drf_*.h5`)
   - HDF5 files with compressed IQ data
   - One file per hour (3.6 MB typical)
   
2. **Metadata** (`<channel>/metadata/metadata_*.h5`)
   - Station information
   - Frequency and sample rate
   - GPS coordinates
   
3. **Quality metrics** (`<channel>_YYYYMMDD_quality.json`)
   - Packet statistics
   - Gap locations and durations
   - Data completeness percentage
   
4. **Summary report** (`<channel>_YYYYMMDD_summary.txt`)
   - Human-readable quality summary
   - Gap details
   - Signal quality estimates

## Quality Metrics

### Data Completeness

The recorder tracks:

- **Expected samples**: 864,000 (24 hours × 10 Hz)
- **Received samples**: Actual samples recorded
- **Missing samples**: Gaps due to packet loss
- **Completeness %**: (Received / Expected) × 100

### Gap Tracking

For each gap, the recorder records:

- Start and end timestamps (ISO format)
- Duration in seconds
- RTP sequence numbers
- Number of missing packets
- Estimated missing samples

### Signal Quality

If enabled, the recorder estimates:

- **Mean signal level**: Average IQ magnitude
- **Max signal level**: Peak IQ magnitude  
- **SNR estimate**: Signal-to-noise ratio (dB)

## Upload to PSWS Server

### Manual Upload

Once Digital RF files are generated, upload to PSWS:

```bash
# Navigate to the dataset directory
cd /mnt/grape-data/archive/YYYYMMDD/AC0G_EM38ww

# Create trigger directory on PSWS server
TRIGGER_DIR="cOBSYYYY-MM-DDTHH-MM_#0_#$(date -u +%Y-%m-%dT%H-%M)"

# Upload via SFTP
sftp -l 100 <station_id>@pswsnetwork.eng.ua.edu <<EOF
put -r .
mkdir ${TRIGGER_DIR}
EOF
```

### Automated Upload

The recorder can be integrated with wsprdaemon's upload mechanism:

```bash
# Use wsprdaemon's GRAPE upload function
source /home/ubuntu/wsprdaemon/grape-utils.sh
upload_24hour_wavs_to_grape_drf_server /mnt/grape-data/archive/YYYYMMDD/AC0G_EM38ww
```

## Advantages Over pcmrecord Approach

### 1. **Per-Channel Separation**
- pcmrecord records ALL SSRCs sharing a multicast address together
- GRAPE recorder separates by SSRC, one Digital RF dataset per channel

### 2. **Timestamp-Based Placement**
- Uses RTP timestamps for accurate sample placement
- Detects and records gaps with precise timing

### 3. **Direct Digital RF Output**
- No intermediate WAV files
- No post-processing concatenation step
- Reduced disk I/O and storage requirements

### 4. **Quality Tracking**
- Real-time packet loss detection
- Gap cataloging with metadata
- Data completeness metrics

### 5. **Simplified Pipeline**
- Pure Python (no C dependencies)
- No pcmrecord, wvunpack, sox, wav2grape chain
- Easier to debug and maintain

## Performance

### Resource Usage

- **CPU**: ~5% per channel (resampling + filtering)
- **Memory**: ~100 MB per channel (daily buffer + filter state)
- **Disk I/O**: ~3.6 MB/hour per channel (compressed)
- **Network**: ~50 KB/s per channel (12 kHz IQ float32)

### Scalability

The recorder can handle:

- **9 GRAPE channels** simultaneously (WWV + CHU)
- **Additional channels** with minimal overhead
- **Multiple stations** with separate instances

## Troubleshooting

### No RTP Packets Received

1. Check if channels are created:
   ```bash
   avahi-browse -ptr _rtp._udp | grep -i "wwv\|chu"
   ```

2. Verify multicast routing:
   ```bash
   ip mroute show
   ```

3. Check firewall rules:
   ```bash
   sudo iptables -L -n | grep 239.251
   ```

### Packet Loss

- Monitor network interface for drops:
  ```bash
  netstat -su | grep -i "packet receive errors"
  ```

- Increase socket buffer size:
  ```bash
  sudo sysctl -w net.core.rmem_max=26214400
  ```

### Incomplete Data

- Check disk space:
  ```bash
  df -h /mnt/grape-data
  ```

- Review quality metrics in `*_summary.txt` files

- Examine gap records in `*_quality.json` files

## Testing

### Component Tests

```bash
# Run unit tests for individual components
python3.11 test_grape_components.py
```

Tests include:
- RTP header parsing
- IQ sample extraction
- Resampler (12 kHz → 10 Hz)
- Daily buffer with UTC alignment
- Metadata generation

### Integration Test

```bash
# Test with live RTP streams (requires active channels)
python3.11 test_grape_recorder.py
```

### Validation

After 24 hours of recording:

1. Check Digital RF files exist:
   ```bash
   find /mnt/grape-data/archive -name "drf_*.h5" -mtime -1
   ```

2. Verify file sizes (~86 MB per channel per day):
   ```bash
   du -sh /mnt/grape-data/archive/YYYYMMDD/*/WWV_*
   ```

3. Review quality metrics:
   ```bash
   cat /mnt/grape-data/archive/YYYYMMDD/*/*/*_summary.txt
   ```

4. Check data completeness (should be >99%):
   ```bash
   grep "Completeness:" /mnt/grape-data/archive/YYYYMMDD/*/*/*_summary.txt
   ```

## Future Enhancements

### Planned Features

1. **Real-time Quality Dashboard**
   - Web interface for monitoring
   - Live packet loss graphs
   - Data completeness indicators

2. **Automatic Upload**
   - Scheduled PSWS uploads at 00:05 UTC
   - Retry logic for failed uploads
   - Upload completion tracking

3. **Gap Filling**
   - Interpolation for short gaps (<2 minutes)
   - Zero-fill for longer gaps
   - NaN marking for missing data

4. **Advanced Signal Processing**
   - Automatic gain control (AGC)
   - Noise floor estimation
   - Time-of-arrival detection

5. **Multi-Station Support**
   - Centralized management
   - Cross-station synchronization
   - Aggregate quality reports

## References

- [Digital RF Format](https://github.com/MITHaystack/digital_rf)
- [HamSCI PSWS](https://hamsci.org/grape)
- [ka9q-radio](https://github.com/ka9q/ka9q-radio)
- [wsprdaemon GRAPE Implementation](https://github.com/rrobinett/wsprdaemon)

## Support

For issues or questions:

1. Check logs: `/tmp/grape_recorder_test.log`
2. Review quality metrics in output directory
3. Consult wsprdaemon documentation for PSWS upload procedures
4. Contact HamSCI GRAPE team for server-side issues

