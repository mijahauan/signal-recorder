# Web-UI API Architecture Proposal
## GRAPE Signal Recorder Monitoring Interface

**Date:** 2024-11-08  
**Purpose:** Clean, focused monitoring interface with stable API

---

## Current State Analysis

### Existing Components
- ✅ `monitoring-server.js` - Express server with 3 endpoints
- ✅ `timing-dashboard.html` - Quality metrics dashboard
- ✅ Quality data collection (CSV files in `analytics/quality/`)
- ✅ Live status JSON from daemon (`recording-stats.json`)
- ⚠️ Multiple legacy HTML files (`.OLD`, `.backup`) - **needs cleanup**
- ⚠️ No spectrogram/visualization generation - **needs implementation**

### Current API Endpoints
1. `/api/monitoring/station-info` - Station config and uptime
2. `/api/monitoring/timing-quality` - Quality metrics from CSV files
3. `/api/monitoring/live-quality` - Live status from daemon

---

## Proposed Two-Tier Information Architecture

### **Tier 1: System Health & Status**
**What operators need to know immediately**

#### 1.1 System Status
- **Recorder daemon status**: Running / Stopped / Error
- **Daemon uptime**: Time since last start
- **Radiod status**: Connected / Disconnected
- **Channel status**: X/9 channels active
- **Data paths**: Where files are being written
- **Disk usage**: Free space on data partition
- **Recent errors**: Last 10 error messages

#### 1.2 Current State Summary
- **Time_snap status**: Established / Not established
- **Time_snap source**: Which WWV/CHU channel
- **Time_snap age**: Minutes since last update
- **Overall quality grade**: A/B/C/D/F (current hour average)
- **Recording mode**: Production / Test
- **Last upload**: Time of last successful upload (Function 6)

---

### **Tier 2: Per-Channel Data Analytics**
**Scientific data visualization and analysis**

#### 2.1 Signal Detection Timeline (ALL channels)
**Purpose:** Quick visual of data presence/absence

- **Minute-by-minute detection**: Present (green) / Absent (red) / Partial (yellow)
- **Timespan**: Current day (UTC), scrollable
- **Visual**: 9 horizontal tracks (one per channel)
- **Interaction**: Click minute to see details
- **Export**: Download as CSV

```
Channel       00:00  02:00  04:00  06:00  08:00  10:00  12:00  14:00  16:00  18:00  20:00  22:00
WWV 2.5 MHz   ████████████████████░░░░░░████████████████████████████████████████████████
WWV 5.0 MHz   ████████████████████████████████████████████████████████████████████████████
WWV 10 MHz    ████████░░░░░░░░░░░░░░░░░░░░░░░░██████████████████████████████████████████
...
```

#### 2.2 Time Metrics (WWV/CHU channels: 4 channels)

**A. Time Variation Plot**
- **X-axis**: Time (UTC, current day)
- **Y-axis**: Timing error (ms)
- **Data**: Minute-to-minute WWV/CHU timing errors
- **Colors**: WWV (blue), CHU (green)
- **Statistics panel**: Mean, Std Dev, Min, Max

**B. Time_Snap History**
- **Timeline**: When time_snap established/updated
- **Source changes**: Visual markers when switching WWV↔CHU
- **Confidence**: Line showing time_snap confidence over time

**C. Differential Delay (WWV-WWVH)**
- **X-axis**: Time (UTC)
- **Y-axis**: Differential delay (ms)
- **Purpose**: Ionospheric propagation difference
- **Channels**: Only 4 WWV channels (2.5, 5, 10, 15 MHz where WWVH detectable)

#### 2.3 WWV/WWVH/CHU Discrimination Data (4 WWV channels)

**Per-channel panel showing:**
- **Station detection rates**: WWV vs WWVH vs CHU percentage
- **SNR comparison**: WWV SNR vs WWVH SNR (scatter plot)
- **Differential delay distribution**: Histogram of WWV-WWVH delays
- **Detection timeline**: When each station detected (stacked bars)

**Example visualization:**
```
WWV 5.0 MHz Detections (Last 24h)
┌─────────────────────────────────────┐
│ WWV:  ████████████████ 78%         │
│ WWVH: ██████████ 52%               │
│                                     │
│ Differential Delay (WWV-WWVH):     │
│ Mean: +12.3 ms  Std: 3.4 ms       │
└─────────────────────────────────────┘
```

#### 2.4 Signal Quality Metrics (ALL channels)

**A. Quality Grade Timeline**
- **Visual**: Color-coded timeline (A=green, B=blue, C=yellow, D=orange, F=red)
- **Granularity**: Per-minute or hourly bins
- **Interaction**: Hover to see details

**B. Packet Loss Heatmap**
- **X-axis**: Hour of day
- **Y-axis**: Channel
- **Color**: Packet loss percentage
- **Purpose**: Identify problematic times/channels

**C. Gap Analysis**
- **Total gaps per channel**: Bar chart
- **Gap duration distribution**: Histogram
- **Gap timeline**: When gaps occurred (scatter plot)

#### 2.5 10 Hz Carrier Spectrogram (ALL channels)
**Purpose:** Visualize carrier stability and Doppler shifts

- **X-axis**: Time (current day)
- **Y-axis**: Frequency (±5 Hz around carrier)
- **Color**: Power (dB)
- **Data source**: 10 Hz decimated Digital RF files
- **Update**: Hourly or on-demand
- **Interaction**: Click to zoom into time range

**Implementation notes:**
- Generate spectrograms from Digital RF data (Function 5 output)
- Use FFT with ~1-minute windows
- Cache images (update hourly)
- PNG format for web display

```
Spectrogram: WWV 5.0 MHz (10 Hz decimated)
       Frequency (Hz)
         ↑
    +5  │ ░░░░▓▓▓▓████▓▓▓▓░░░░
         │ ░░▓▓████████████▓▓░░
     0  │▓▓██████████████████▓▓  ← Stable carrier
         │ ░░▓▓████████████▓▓░░
    -5  │ ░░░░▓▓▓▓████▓▓▓▓░░░░
        └─────────────────────→ Time (UTC)
          00:00      12:00    24:00
```

#### 2.6 Signal Power Timeline (ALL channels)
- **X-axis**: Time (current day)
- **Y-axis**: Signal power (dBm or normalized)
- **Purpose**: Track propagation variations
- **Data source**: Amplitude from IQ samples
- **Update**: Per-minute averages

---

## Additional Analytics Recommendations

### **Priority 1: Essential for Operations**

1. **Disk Space Monitoring**
   - Free space on data partition
   - Estimated time until full (based on rate)
   - Alert when <10% free

2. **Upload Queue Status** (Function 6)
   - Files pending upload
   - Upload success/failure rate
   - Network status indicator

3. **Error Log Display**
   - Recent errors/warnings from daemon
   - Filterable by severity
   - Auto-refresh

### **Priority 2: Scientific Analysis**

4. **Multi-Channel Correlation**
   - Compare timing errors across channels
   - Identify systematic vs random variations
   - Frequency-dependent propagation

5. **Long-Term Trending** (multi-day)
   - Quality grade trends over weeks
   - Seasonal propagation patterns
   - Equipment performance trends

6. **SNR Analysis**
   - SNR vs time-of-day
   - SNR vs frequency
   - Correlation with detection success

### **Priority 3: Advanced Features**

7. **Automated Quality Reports**
   - Daily/weekly PDF generation
   - Email delivery option
   - Customizable metrics

8. **Propagation Path Analysis**
   - WWV vs WWVH delay vs solar conditions
   - Compare with ionospheric models
   - Visualize propagation modes

9. **Station Comparison**
   - If multiple GRAPE stations deployed
   - Compare time_snap accuracy
   - Network-wide health monitoring

---

## Proposed API Architecture

### Design Principles
1. **RESTful**: Standard HTTP verbs and resource patterns
2. **Versioned**: `/api/v1/` prefix for future compatibility
3. **Stateless**: No server-side sessions
4. **Cacheable**: Appropriate cache headers
5. **Stable contracts**: API changes don't break existing clients

### API Structure

```
/api/v1/
├── system/               # Tier 1: System Health
│   ├── status
│   ├── health
│   ├── uptime
│   ├── disk-usage
│   └── errors
│
├── channels/             # Channel information
│   ├── list
│   ├── {channel_id}/info
│   └── {channel_id}/status
│
├── quality/              # Tier 2: Quality metrics
│   ├── summary
│   ├── timeline
│   ├── grades
│   └── {channel_id}/metrics
│
├── timing/               # Time_snap and WWV data
│   ├── time-snap
│   ├── wwv-detections
│   ├── differential-delays
│   └── {channel_id}/timing-errors
│
├── data/                 # Data analytics
│   ├── spectrograms/{channel_id}
│   ├── signal-power/{channel_id}
│   ├── detection-timeline
│   └── gaps/{channel_id}
│
└── upload/               # Upload status (Function 6)
    ├── queue-status
    ├── recent-uploads
    └── statistics
```

---

## Detailed API Endpoints

### **Tier 1: System Health**

#### `GET /api/v1/system/status`
**Purpose:** Overall system health check

**Response:**
```json
{
  "timestamp": "2024-11-08T21:00:00Z",
  "recorder": {
    "running": true,
    "uptime_seconds": 86423,
    "pid": 12345,
    "mode": "production"
  },
  "radiod": {
    "connected": true,
    "status_address": "239.192.152.141",
    "data_address": "239.192.152.141"
  },
  "channels": {
    "total": 9,
    "active": 9,
    "errors": 0
  },
  "time_snap": {
    "established": true,
    "source": "WWV 5.0 MHz",
    "age_minutes": 2,
    "confidence": 0.95
  },
  "quality": {
    "overall_grade": "A",
    "hour_score": 98.5
  },
  "data_paths": {
    "archive": "/var/lib/signal-recorder/data",
    "analytics": "/var/lib/signal-recorder/analytics",
    "upload": "/var/lib/signal-recorder/upload"
  },
  "disk": {
    "total_gb": 500,
    "used_gb": 234,
    "free_gb": 266,
    "percent_used": 46.8
  },
  "recent_errors": [
    {
      "timestamp": "2024-11-08T20:45:12Z",
      "level": "warning",
      "message": "Packet loss detected on WWV 10 MHz"
    }
  ]
}
```

#### `GET /api/v1/system/health`
**Purpose:** Simple health check for monitoring tools

**Response:**
```json
{
  "status": "healthy",
  "checks": {
    "recorder": "ok",
    "radiod": "ok",
    "disk_space": "ok",
    "time_snap": "ok"
  }
}
```

#### `GET /api/v1/system/errors?since=<timestamp>&severity=<level>`
**Purpose:** Retrieve error log

**Query params:**
- `since`: ISO timestamp or relative (e.g., "1h", "24h")
- `severity`: "error", "warning", "info"

**Response:**
```json
{
  "errors": [
    {
      "timestamp": "2024-11-08T20:45:12Z",
      "severity": "warning",
      "source": "GRAPEChannelRecorderV2",
      "channel": "WWV 10 MHz",
      "message": "Packet loss: 2 packets dropped",
      "context": {
        "ssrc": "0x12345678",
        "sequence_before": 12345,
        "sequence_after": 12348
      }
    }
  ],
  "total_count": 1,
  "filter": {
    "since": "2024-11-08T20:00:00Z",
    "severity": "warning"
  }
}
```

---

### **Tier 2: Channel Data Analytics**

#### `GET /api/v1/channels/list`
**Purpose:** Get all configured channels

**Response:**
```json
{
  "channels": [
    {
      "id": "wwv_2p5",
      "name": "WWV 2.5 MHz",
      "ssrc": "0x12345601",
      "frequency_hz": 2500000,
      "is_wwv_channel": true,
      "status": "active",
      "sample_rate": 16000
    },
    // ... 8 more channels
  ]
}
```

#### `GET /api/v1/quality/summary?date=<YYYYMMDD>&hour=<HH>`
**Purpose:** Quality summary for all channels

**Query params:**
- `date`: YYYYMMDD format (default: today)
- `hour`: 0-23 (default: current hour)

**Response:**
```json
{
  "date": "20241108",
  "hour": 20,
  "channels": {
    "WWV 2.5 MHz": {
      "grade": "A",
      "score": 98.5,
      "completeness_pct": 99.8,
      "packet_loss_pct": 0.2,
      "gaps": 1,
      "resequenced": 3,
      "minutes_in_hour": 60
    },
    // ... other channels
  },
  "overall": {
    "grade_distribution": {
      "A": 520,
      "B": 18,
      "C": 2,
      "D": 0,
      "F": 0
    },
    "avg_completeness": 99.7
  }
}
```

#### `GET /api/v1/timing/wwv-detections?channel=<id>&date=<YYYYMMDD>`
**Purpose:** WWV/WWVH/CHU detection data for a channel

**Response:**
```json
{
  "channel": "WWV 5.0 MHz",
  "date": "20241108",
  "detections": {
    "wwv": {
      "count": 1120,
      "rate_pct": 77.8,
      "timing_errors_ms": [2.1, 1.8, -0.5, ...],
      "avg_snr_db": 45.3
    },
    "wwvh": {
      "count": 748,
      "rate_pct": 51.9,
      "timing_errors_ms": [15.2, 14.8, 13.9, ...],
      "avg_snr_db": 38.7
    }
  },
  "differential_delays": {
    "values_ms": [12.3, 13.4, 11.8, ...],
    "mean_ms": 12.5,
    "std_ms": 1.2,
    "min_ms": 10.1,
    "max_ms": 15.8
  },
  "timeline": [
    {
      "minute": "2024-11-08T00:00:00Z",
      "wwv_detected": true,
      "wwvh_detected": true,
      "chu_detected": false,
      "wwv_timing_error_ms": 2.1,
      "wwvh_timing_error_ms": 14.4,
      "differential_ms": 12.3,
      "wwv_snr_db": 46.1,
      "wwvh_snr_db": 39.2
    },
    // ... per-minute data
  ]
}
```

#### `GET /api/v1/data/detection-timeline?date=<YYYYMMDD>`
**Purpose:** Minute-by-minute signal detection for all channels

**Response:**
```json
{
  "date": "20241108",
  "timeline": [
    {
      "minute": "2024-11-08T00:00:00Z",
      "channels": {
        "WWV 2.5 MHz": { "status": "present", "quality": "A", "samples": 960000 },
        "WWV 5.0 MHz": { "status": "present", "quality": "A", "samples": 960000 },
        "WWV 10 MHz": { "status": "partial", "quality": "C", "samples": 940000 },
        // ... all channels
      }
    },
    // ... 1440 minutes
  ]
}
```

#### `GET /api/v1/data/spectrograms/{channel_id}?date=<YYYYMMDD>&hour=<HH>`
**Purpose:** Get spectrogram image for channel

**Query params:**
- `date`: YYYYMMDD
- `hour`: 0-23 (optional, default: all day)
- `format`: "png" | "jpg" (default: png)

**Response:** PNG image (binary)

**Cache strategy:**
- Generate hourly spectrograms on-demand
- Cache for 1 hour
- Background job generates spectrograms every hour

**Implementation:**
```python
# Pseudo-code
def generate_spectrogram(channel_id, start_time, end_time):
    # Read 10 Hz Digital RF data
    drf_reader = DigitalRFReader(upload_dir)
    samples = drf_reader.read_time_range(start_time, end_time, channel_id)
    
    # Compute spectrogram
    f, t, Sxx = spectrogram(samples, fs=10, nperseg=600)  # 1-minute windows
    
    # Plot
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.pcolormesh(t, f, 10*np.log10(Sxx), shading='gouraud')
    ax.set_ylabel('Frequency (Hz)')
    ax.set_xlabel('Time (minutes since start)')
    ax.set_title(f'{channel_id} - 10 Hz Carrier Spectrogram')
    
    # Save to cache
    img_path = f'/cache/spectrograms/{channel_id}_{date}_{hour}.png'
    fig.savefig(img_path, dpi=150, bbox_inches='tight')
    
    return img_path
```

#### `GET /api/v1/data/signal-power/{channel_id}?date=<YYYYMMDD>`
**Purpose:** Signal power timeline for a channel

**Response:**
```json
{
  "channel": "WWV 5.0 MHz",
  "date": "20241108",
  "sample_rate": 10,
  "power_timeline": [
    {
      "minute": "2024-11-08T00:00:00Z",
      "mean_power_dbm": -45.2,
      "peak_power_dbm": -38.7,
      "noise_floor_dbm": -85.3,
      "snr_db": 40.1
    },
    // ... per-minute data
  ],
  "statistics": {
    "mean_power_dbm": -44.8,
    "std_power_dbm": 2.1,
    "min_power_dbm": -52.3,
    "max_power_dbm": -38.1
  }
}
```

---

## Implementation Plan

### Phase 1: System Status API (Week 1)
**Goal:** Get Tier 1 working perfectly

1. ✅ Refactor `monitoring-server.js` to new API structure
2. ✅ Implement `/api/v1/system/*` endpoints
3. ✅ Add disk usage monitoring
4. ✅ Create error log aggregation
5. ✅ Build simple status dashboard (HTML/JS)

### Phase 2: Quality & Timing API (Week 2)
**Goal:** Migrate existing quality data to new API

1. ✅ Implement `/api/v1/quality/*` endpoints
2. ✅ Implement `/api/v1/timing/*` endpoints
3. ✅ Update timing-dashboard.html to use new API
4. ✅ Add detection timeline visualization

### Phase 3: Data Analytics API (Week 3)
**Goal:** Add spectrogram and signal power

1. ✅ Implement spectrogram generation from Digital RF
2. ✅ Create `/api/v1/data/spectrograms` endpoint
3. ✅ Implement signal power calculation
4. ✅ Build visualization dashboard

### Phase 4: Upload Monitoring (Week 4)
**Goal:** Integrate Function 6 status

1. ✅ Wire up UploadManager to API
2. ✅ Implement `/api/v1/upload/*` endpoints
3. ✅ Add upload queue visualization
4. ✅ Alert on upload failures

### Phase 5: Cleanup & Polish (Week 5)
**Goal:** Remove legacy code, optimize performance

1. ✅ Delete `.OLD`, `.backup` HTML files
2. ✅ Optimize API response times
3. ✅ Add caching where appropriate
4. ✅ Write API documentation
5. ✅ Performance testing

---

## Technology Stack

### Backend
- **Server**: Node.js + Express (existing)
- **File parsing**: `csv-parse`, `toml` (existing)
- **Image generation**: Python scripts (matplotlib)
- **Caching**: Simple file-based cache or Redis (if needed)

### Frontend
- **Framework**: Vanilla JavaScript (keep it simple)
- **Charts**: Chart.js or D3.js
- **Styling**: Tailwind CSS or existing custom CSS
- **Real-time**: SSE (Server-Sent Events) for live updates

### Data Processing
- **Spectrograms**: Python + matplotlib + scipy
- **Digital RF reading**: Existing `DigitalRFReader` interface
- **Quality analysis**: Existing CSV parsing

---

## API Stability Guidelines

### Versioning
- Current API: `/api/v1/`
- Breaking changes require new version: `/api/v2/`
- Support old versions for 6 months

### Backwards Compatibility
- Never remove fields (only deprecate)
- Add new fields at end of objects
- Use optional query parameters
- Document deprecations in changelog

### Error Handling
**Standard error response:**
```json
{
  "error": {
    "code": "CHANNEL_NOT_FOUND",
    "message": "Channel 'WWV 99 MHz' does not exist",
    "details": {
      "available_channels": ["WWV 2.5 MHz", ...]
    }
  }
}
```

### Performance
- Response time targets:
  - `/system/status`: <100ms
  - `/quality/summary`: <500ms
  - `/data/spectrograms`: <2s (cached: <100ms)
- Pagination for large datasets (>1000 records)
- Compression (gzip) for text responses

---

## Web UI Layout Proposal

### Dashboard Structure

```
┌────────────────────────────────────────────────────────────────┐
│ GRAPE Signal Recorder - [Station Callsign] [Grid Square]      │
└────────────────────────────────────────────────────────────────┘

┌─ SYSTEM STATUS ─────────────────────────────────────────────────┐
│ ● RECORDING [23h 14m uptime]  ● RADIOD Connected                │
│ ● 9/9 Channels Active         ● TIME_SNAP: WWV 5.0 MHz (2m old) │
│ ● Disk: 266 GB free (53%)     ● Quality: A (current hour)       │
│ ● Upload Queue: 0 pending     ● Last Error: None                │
└─────────────────────────────────────────────────────────────────┘

┌─ TABS ──────────────────────────────────────────────────────────┐
│ [Overview] [Timing] [Quality] [Spectrograms] [Uploads] [Logs]  │
└─────────────────────────────────────────────────────────────────┘

┌─ TAB CONTENT ───────────────────────────────────────────────────┐
│                                                                  │
│  [Content varies based on selected tab]                         │
│                                                                  │
│  Overview:      Detection timeline (all channels)               │
│  Timing:        WWV/WWVH timing errors and differential delays  │
│  Quality:       Quality grades, packet loss, gaps               │
│  Spectrograms:  10 Hz carrier spectrograms per channel          │
│  Uploads:       Upload queue status and history                 │
│  Logs:          Error/warning log viewer                        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

Last updated: 2024-11-08 21:00:00 UTC  [Auto-refresh: ON ▼]
```

---

## Summary

### Key Recommendations

1. **Two-tier architecture**: System status (Tier 1) + Data analytics (Tier 2)
2. **Stable API**: Versioned, RESTful, well-documented
3. **Essential analytics**:
   - Detection timeline (all channels)
   - WWV/WWVH discrimination data
   - Time variation plots
   - 10 Hz carrier spectrograms
   - Signal power timelines
   
4. **Additional analytics**:
   - Disk usage monitoring
   - Upload queue status
   - Multi-day trending
   - Propagation analysis

5. **Clean implementation**:
   - Delete legacy HTML files
   - Separate API logic from presentation
   - Cache expensive operations (spectrograms)
   - Document everything

### Next Steps

1. **Review this proposal** - Adjust based on priorities
2. **Implement Phase 1** - Get system status API working
3. **Migrate existing dashboard** - Use new API endpoints
4. **Add spectrograms** - Most requested visualization
5. **Wire up Function 6** - Upload monitoring critical

This architecture provides:
- ✅ Clear separation of concerns
- ✅ Stable API for future development
- ✅ Essential operational visibility
- ✅ Scientific data analytics
- ✅ Room for future enhancements
