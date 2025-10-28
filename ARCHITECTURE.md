# GRAPE Signal Recorder Architecture

## Overview

The GRAPE Signal Recorder is a **specialized system** for recording, processing, and uploading time-standard radio signals from ka9q-radio to the HamSCI PSWS repository. Unlike generic SDR recording systems, it is purpose-built for the **GRAPE (Grape Radio Aurora and Plasma Experiment)** project requirements.

## Design Philosophy

### GRAPE-Specific Goals
1. **Precision Timing**: Sub-millisecond timing accuracy for WWV/CHU time signals
2. **Data Quality**: Continuous monitoring of completeness, packet loss, and timing drift
3. **HamSCI Integration**: Native Digital RF format with HamSCI-compliant metadata
4. **Reliable Upload**: Resilient rsync-based upload to PSWS with retry logic
5. **Simple Management**: Web-based configuration and monitoring for non-technical users

### Why Not wsprdaemon?

This project **does not use wsprdaemon** or its WSPR-focused pipeline. Instead, it implements a streamlined scipy-based approach optimized for:
- **Direct RTP processing** (no external tools like sox/pcmrecord)
- **Continuous data flow** (not 2-minute WSPR cycles)
- **IQ data preservation** (full complex samples, not audio)
- **Sub-10Hz decimation** (from 16kHz → 10Hz for timing analysis)

---

## Architecture Layers

```
┌──────────────────────────────────────────────────────────────────┐
│                       User Interface Layer                        │
│  • Web UI (Node.js/Express) - Configuration & Monitoring         │
│  • CLI (Python) - Daemon control & channel management            │
└──────────────────────────────────────────────────────────────────┘
                                    ↓
┌──────────────────────────────────────────────────────────────────┐
│                      Application Layer                            │
│  • GRAPERecorderManager - Multi-channel coordination             │
│  • GRAPEChannelRecorder - Per-channel RTP → Digital RF           │
│  • GRAPEMetadata - HamSCI-compliant metadata generation          │
└──────────────────────────────────────────────────────────────────┘
                                    ↓
┌──────────────────────────────────────────────────────────────────┐
│                    Signal Processing Layer                        │
│  • RTPReceiver - UDP packet capture & sequencing                 │
│  • CircularBuffer - Jitter absorption (2-second buffer)          │
│  • scipy.signal.decimate - Anti-aliased 16kHz → 10Hz             │
│  • Resampler - Timing validation & quality metrics               │
└──────────────────────────────────────────────────────────────────┘
                                    ↓
┌──────────────────────────────────────────────────────────────────┐
│                      Storage & Upload Layer                       │
│  • Digital RF Writer - Time-indexed HDF5 format                  │
│  • Uploader - rsync to PSWS with retry & verification            │
└──────────────────────────────────────────────────────────────────┘
                                    ↓
┌──────────────────────────────────────────────────────────────────┐
│                    External Dependencies                          │
│  • ka9q-radio (radiod) - RTP stream source                       │
│  • HamSCI PSWS - Data repository                                 │
└──────────────────────────────────────────────────────────────────┘
```

---

## Component Details

### 1. Data Flow: RTP → Digital RF

#### Input: ka9q-radio RTP Streams
- **Format**: Complex IQ samples (int16, little-endian)
- **Sample Rate**: 16,000 Hz (configurable)
- **Protocol**: RTP over multicast UDP
- **Channels**: WWV (2.5, 5, 10, 15, 20, 25 MHz), CHU (3.3, 7.85, 14.67 MHz)

#### Processing Pipeline

**Step 1: RTP Reception** (`RTPReceiver`)
```
UDP Packet → Parse RTP header → Extract IQ samples
           → Track sequence numbers → Detect packet loss
```

**Step 2: Buffering** (`CircularBuffer`)
```
Incoming samples → 2-second circular buffer → Absorb network jitter
                 → Continuous read for decimation
```

**Step 3: Decimation** (`Resampler`)
```
16,000 Hz IQ → scipy.signal.decimate(1600) → 10 Hz IQ
             → Anti-aliased FIR filter
             → Timing validation (RTP clock vs system clock)
```

**Step 4: Digital RF Output** (`GRAPEChannelRecorder`)
```
10 Hz IQ samples → Digital RF Writer → Time-indexed HDF5
                 → HamSCI metadata → 60-second files
```

#### Why 10 Hz Output?

GRAPE analyzes **long-term timing variations** in WWV/CHU signals. The 10 Hz rate:
- Captures phase information for timing analysis
- Reduces data size (1,600x decimation)
- Matches HamSCI repository expectations
- Sufficient for < 100 ms timing precision

---

### 2. Timing & Quality Monitoring

The system tracks comprehensive quality metrics with **independent WWV/CHU timing validation**:

#### Completeness
```
(samples_received / expected_samples) × 100%
```
- **Healthy**: ≥99%
- **Warning**: 95-99%
- **Error**: <95%

#### Packet Loss
```
(packets_dropped / packets_received) × 100%
```
- Detected via RTP sequence number gaps
- Indicates network congestion or multicast issues

#### Timing Drift (RTP vs System Clock)
```
RTP timestamp - system clock offset
```
- Measured every 100 samples (10-second window)
- Mean ± std deviation tracked
- Should be < ±50 ms for healthy streams

#### WWV/CHU Timing Validation (NEW - Phase 1)
**Ground truth validation using time-standard signals:**

WWV broadcasts a **1200 Hz tone for 1 second** at the start of each UTC minute. CHU broadcasts a **60 Hz tone**. We use these as independent timing references.

**Parallel Processing:**
```
RTP Stream (16 kHz IQ)
  ├─→ Main: 16 kHz → 10 Hz (Digital RF)
  └─→ Tone: 16 kHz → 1 kHz (WWV detection)
            ↓
      1200 Hz bandpass filter
            ↓
      Envelope detection & onset timing
            ↓
      Compare to UTC minute boundary
```

**Metrics Tracked:**
- **Tone detection rate**: % of expected tones detected
- **Timing error**: RTP timestamp vs WWV tone onset (ms)
- **Mean ± std**: Statistical distribution of timing errors
- **Last detection**: Timestamp of most recent tone

**Benefits:**
- ✅ Independent of RTP/system clocks
- ✅ Validates timing accuracy against UTC ground truth
- ✅ Detects clock drift before it becomes significant
- ✅ Scientific proof of data quality

**Implementation:** See [docs/TIMING_VALIDATION.md](docs/TIMING_VALIDATION.md)

#### Discontinuity Tracking (NEW - Phase 1)
**Complete provenance of timing discontinuities:**

Every gap, sync adjustment, or timing jump is logged with:
- Sample index where it occurred
- Magnitude (samples and milliseconds)
- RTP sequence/timestamp before and after
- Explanation (human-readable)
- WWV validation flag

**Discontinuity Types:**
- **GAP**: Missed packets, samples lost/filled with zeros
- **SYNC_ADJUST**: Time sync correction (future: based on WWV tone)
- **RTP_RESET**: RTP sequence or timestamp reset
- **OVERFLOW/UNDERFLOW**: Buffer issues

**Export Formats:**
- Embedded in Digital RF metadata (per-sample provenance)
- JSON stats file (real-time monitoring)
- CSV export (offline analysis)

All quality metrics are:
- Logged to `/tmp/signal-recorder-stats.json`
- Displayed in real-time web UI
- Used for health status (🟢/🟡/🔴)
- Exportable for scientific analysis

---

### 3. HamSCI Metadata

Each Digital RF file includes HamSCI-compliant metadata:

```json
{
  "receiver": "WWV-10.0",
  "receiver_ant": "RX888-mkII",
  "receiver_callsign": "AC0G",
  "receiver_grid_square": "EM38ww",
  "receiver_lat": 38.xx,
  "receiver_lon": -77.xx,
  "sample_rate_numerator": 10,
  "sample_rate_denominator": 1,
  "uuid_str": "grape-recorder-ac0g-wwv10",
  "digital_rf_version": "3.0.0"
}
```

Generated by `GRAPEMetadata.generate()` from station config.

---

### 4. Upload Strategy

#### Rationale: Why rsync over HTTP/S3?

HamSCI PSWS uses **rsync over SSH** for institutional repository uploads:
- Supports incremental/partial file transfers
- Resumable on network interruption
- SSH key authentication (no password management)
- Standard tool at universities/observatories

#### Upload Flow

```
Local Digital RF directory
    ↓
Queue-based uploader (every 5 minutes)
    ↓
rsync --checksum --partial --append-verify
    ↓
PSWS repository (pswsnetwork.eng.ua.edu)
```

**Features**:
- Retry with exponential backoff (5 attempts)
- Checksum verification (`--checksum`)
- Partial transfer resume (`--partial`)
- Directory structure preservation
- Upload status tracking in web UI

---

### 5. Web Management Interface

#### Technology Stack
- **Backend**: Node.js with Express.js (single file: `simple-server.js`)
- **Frontend**: Vanilla HTML/CSS/JavaScript (single file: `index.html`, `monitoring.html`)
- **Database**: JSON files (no database server needed)
- **API**: RESTful JSON endpoints

#### Features

**Configuration Management**:
- Station info (callsign, grid square, instrument)
- Channel definitions (WWV/CHU presets)
- PSWS credentials (SSH host, path)
- TOML export for daemon

**Monitoring Dashboard**:
- Real-time channel health (🟢/🟡/🔴)
- Completeness, packet loss, timing drift
- Data throughput and file counts
- Daemon logs (tail -100)

**Channel Management**:
- Discover active RTP channels from radiod
- Auto-create channels via `control` utility
- Compare config vs actual channels

---

## Configuration Format

### Station Configuration (TOML)

```toml
[station]
callsign = "AC0G"
grid_square = "EM38ww"
instrument_id = "RX888"
description = "GRAPE station"

[ka9q]
status_address = "239.192.152.141"  # radiod multicast address

[recorder]
archive_dir = "/var/lib/signal-recorder/archive"
recording_interval = 60  # seconds per Digital RF file

[[recorder.channels]]
ssrc = 2500000
frequency_hz = 2500000
preset = "iq"
sample_rate = 16000
description = "WWV 2.5 MHz"
enabled = true

[uploader]
enabled = true
protocol = "rsync"
remote_host = "pswsnetwork.eng.ua.edu"
remote_user = "user_ac0g"
remote_path = "/var/psws/archive/data/GRAPE/AC0G"
ssh_key_path = "~/.ssh/psws_key"
upload_interval = 300  # seconds
```

---

## File Structure

### Active Codebase

**Core Processing**:
- `src/signal_recorder/grape_rtp_recorder.py` - Main daemon (RTP → Digital RF)
- `src/signal_recorder/grape_metadata.py` - HamSCI metadata
- `src/signal_recorder/uploader.py` - rsync upload

**Management**:
- `src/signal_recorder/grape_recorder.py` - CLI wrapper
- `src/signal_recorder/cli.py` - Entry point
- `src/signal_recorder/control_discovery.py` - Channel discovery
- `src/signal_recorder/radiod_control.py` - Channel creation
- `src/signal_recorder/channel_manager.py` - Channel management

**Web Interface**:
- `web-ui/simple-server.js` - API server
- `web-ui/index.html` - Configuration UI
- `web-ui/monitoring.html` - Dashboard

### Data Directories

```
/var/lib/signal-recorder/
├── archive/               # Digital RF output
│   ├── WWV-2.5/
│   │   ├── rf@1698768000.h5
│   │   └── metadata/
│   ├── WWV-5.0/
│   └── ...
└── upload_queue/         # Pending uploads
    └── ...
```

---

## Dependencies

### System Requirements
- **Python 3.8+** with scipy, numpy, digital_rf
- **ka9q-radio** (radiod + control utility)
- **Node.js 16+** (for web UI)
- **rsync** with SSH (for PSWS upload)
- **Linux** (multicast networking)

### Python Packages
```
digital_rf>=3.0.0      # Time-indexed HDF5 I/O
scipy>=1.7.0           # Signal decimation
numpy>=1.20.0          # Array operations
toml>=0.10.0           # Config parsing
```

### Optional
- `systemd` - Daemon management
- `nginx` - Reverse proxy for web UI

---

## Comparison: GRAPE vs wsprdaemon

| Aspect | wsprdaemon | GRAPE Recorder |
|--------|------------|----------------|
| **Purpose** | WSPR decoding | Timing signal archival |
| **Data Type** | Audio (PCM) | IQ samples |
| **Processing** | sox, wsprd | scipy decimation |
| **Output** | WSPR spots | Digital RF |
| **Cycle** | 2-minute WSPR windows | Continuous 60-second files |
| **Upload** | wsprnet.org | HamSCI PSWS (rsync) |
| **Metadata** | WSPR spots | HamSCI format |
| **Tools** | External (sox, jt9) | Pure Python |

**Key Insight**: wsprdaemon is optimized for **WSPR spot extraction**, while GRAPE focuses on **long-term timing data preservation**.

---

## Installation & Deployment

See [INSTALLATION.md](INSTALLATION.md) for:
- System requirements
- Dependency installation
- Configuration setup
- Daemon deployment (systemd)
- Web UI setup
- Troubleshooting

---

## Monitoring & Diagnostics

### Health Indicators

**🟢 Healthy**:
- Completeness ≥99%
- Packet loss <1%
- Timing drift <50ms

**🟡 Warning**:
- Completeness 95-99%
- Packet loss 1-5%
- Timing drift 50-100ms

**🔴 Error**:
- Completeness <95%
- Packet loss >5%
- Timing drift >100ms
- No data for >60 seconds

### Logs

- **Daemon**: `/tmp/signal-recorder-daemon.log`
- **Stats**: `/tmp/signal-recorder-stats.json`
- **Upload**: `/tmp/signal-recorder-upload.log`

### Web UI Monitoring

- Real-time dashboard: `http://localhost:3000/monitoring`
- JSON API: `http://localhost:3000/api/monitoring/recording-stats`

---

## Future Enhancements

Potential improvements (not currently implemented):

1. **Multi-site aggregation** - Centralized monitoring dashboard
2. **Automatic channel tuning** - Track propagation changes
3. **Ionospheric alerts** - Detect anomalies in timing data
4. **Machine learning** - Predict data quality issues
5. **Cloud upload** - S3/GCS as PSWS alternative

---

## Credits

- **ka9q-radio**: Phil Karn (KA9Q) - RTP streaming foundation
- **HamSCI GRAPE**: Nathaniel Frissell (W2NAF) - Project goals & metadata format
- **Digital RF**: MIT Haystack Observatory - Time-indexed HDF5 format
- **This implementation**: Michael Hauan (AC0G) - GRAPE-specific recorder

---

*Last Updated: 2025-10-28*
