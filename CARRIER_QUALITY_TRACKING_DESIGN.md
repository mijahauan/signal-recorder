# Carrier Channel Quality Tracking Design

## Overview

Even though carrier channels use NTP_SYNCED timing (±10ms) instead of GPS_LOCKED time_snap (±1ms), we need comprehensive quality tracking for scientific provenance and data validation.

## Quality Dimensions for Carrier Channels

### 1. Sample Completeness
- **Expected samples per minute:** Configured rate × 60 (e.g., 200 Hz → 12,000 samples/min)
- **Actual samples received:** Count from NPZ file
- **Completeness percentage:** Actual / Expected × 100%
- **Gap detection:** RTP timestamp discontinuities

### 2. Packet Reception
- **Expected packets:** Sample rate / samples per packet
- **Packets received:** From RTP sequence tracking
- **Packet loss percentage:** (Expected - Received) / Expected × 100%
- **Out-of-order packets:** Detected during resequencing

### 3. NTP Sync Quality
- **NTP synchronized:** Boolean from timedatectl/chrony
- **NTP offset:** Milliseconds from reference (via chronyc tracking)
- **NTP stratum:** Distance from reference clock (1-15)
- **NTP jitter:** Short-term offset variation
- **Sync status per minute:** Captured at file creation time

### 4. RTP Clock Drift
- **Wall clock drift:** Compare RTP timestamp progression to system clock
- **Drift rate:** ms/minute deviation from expected
- **Clock resets:** Sudden jumps in RTP timestamp

---

## Data Model

### Quality Metadata (Per Minute NPZ)

Embedded in carrier channel NPZ files:

```python
{
    # Sample integrity
    'sample_rate': 200,  # Configured rate
    'expected_samples': 12000,  # Expected per minute
    'actual_samples': 5880,  # ~49% (actual reception)
    'completeness_pct': 49.0,
    'gap_count': 23,
    'gap_samples_filled': 6120,
    
    # Packet reception
    'expected_packets': 40,  # Assuming 300 samples/packet @ 200 Hz
    'packets_received': 20,
    'packet_loss_pct': 50.0,
    'out_of_order_packets': 0,
    
    # NTP timing quality
    'timing_quality': 'NTP_SYNCED',
    'ntp_synchronized': True,
    'ntp_offset_ms': 2.3,  # From chronyc at capture time
    'ntp_stratum': 3,
    'ntp_jitter_ms': 0.5,
    'ntp_reference': '192.168.1.1',  # NTP server
    
    # RTP clock tracking
    'rtp_timestamp': 123456789,
    'unix_timestamp': 1763430540.0,
    'rtp_drift_ms': 15.2,  # Deviation from expected progression
    'rtp_clock_reset_detected': False,
    
    # Provenance
    'recorder_version': '2.0.0',
    'created_timestamp': 1763430541.234,
    'channel_type': 'carrier',
    'channel_bandwidth_hz': 200
}
```

### Quality CSV (Daily Aggregation)

Similar to wide channels but carrier-specific metrics:

```csv
timestamp,unix_ts,minute,completeness_pct,packet_loss_pct,ntp_offset_ms,ntp_stratum,ntp_sync,rtp_drift_ms,gap_count,quality_grade
2025-11-18T02:00:00+00:00,1763430000,0,49.2,50.8,2.3,3,True,15.2,23,B
2025-11-18T02:01:00+00:00,1763430060,1,48.8,51.2,2.1,3,True,14.8,25,B
```

**Quality Grades (Carrier-specific):**
- **A (95-100):** >95% completeness, NTP stratum ≤3, offset <5ms
- **B (85-94):** 85-95% completeness, NTP stratum ≤4, offset <10ms
- **C (70-84):** 70-85% completeness, NTP stratum ≤5, offset <20ms
- **D (50-69):** 50-70% completeness, NTP stratum >5, or offset >20ms
- **F (<50):** <50% completeness or NTP not synchronized

---

## Implementation

### 1. Core Recorder Enhancement

Add NTP quality capture during NPZ creation:

```python
def _get_ntp_status(self) -> dict:
    """
    Query NTP synchronization status
    
    Returns:
        {
            'synchronized': bool,
            'offset_ms': float,
            'stratum': int,
            'jitter_ms': float,
            'reference': str
        }
    """
    try:
        # Try chronyc first (more common)
        result = subprocess.run(
            ['chronyc', 'tracking'],
            capture_output=True,
            text=True,
            timeout=2
        )
        
        if result.returncode == 0:
            return self._parse_chronyc_output(result.stdout)
        
        # Fall back to ntpq
        result = subprocess.run(
            ['ntpq', '-c', 'rv'],
            capture_output=True,
            text=True,
            timeout=2
        )
        
        if result.returncode == 0:
            return self._parse_ntpq_output(result.stdout)
        
        # No NTP daemon found
        return {
            'synchronized': False,
            'offset_ms': None,
            'stratum': None,
            'jitter_ms': None,
            'reference': None
        }
        
    except Exception as e:
        logger.warning(f"Failed to query NTP status: {e}")
        return {'synchronized': False, 'offset_ms': None}


def _parse_chronyc_output(self, output: str) -> dict:
    """Parse chronyc tracking output"""
    info = {'synchronized': False}
    
    for line in output.split('\n'):
        if 'System time' in line:
            # Extract offset: "System time     : 0.000002345 seconds fast of NTP time"
            match = re.search(r'([\d.]+) seconds', line)
            if match:
                info['offset_ms'] = float(match.group(1)) * 1000
                info['synchronized'] = True
        
        elif 'Stratum' in line:
            match = re.search(r':\s*(\d+)', line)
            if match:
                info['stratum'] = int(match.group(1))
        
        elif 'Root delay' in line:
            # Can extract jitter from this section
            pass
    
    return info
```

### 2. Analytics Service Enhancement

Extend quality CSV generation for carrier channels:

```python
def _write_quality_csv_carrier(
    self,
    archive: NPZArchive,
    quality_info: QualityInfo,
    ntp_status: dict,
    output_file: Path
):
    """
    Write quality metrics specific to carrier channels
    
    Includes:
    - Sample completeness (RTP-based)
    - Packet loss statistics
    - NTP sync quality
    - RTP clock drift
    """
    minute_dt = datetime.fromtimestamp(archive.unix_timestamp, tz=timezone.utc)
    
    # Calculate expected samples for carrier rate
    expected_samples = archive.sample_rate * 60
    actual_samples = len(archive.iq_samples)
    completeness_pct = (actual_samples / expected_samples) * 100
    
    # Estimate packet loss (assuming typical packet size)
    samples_per_packet = 320  # Typical for ka9q-radio
    expected_packets = expected_samples / samples_per_packet
    packets_received = actual_samples / samples_per_packet
    packet_loss_pct = ((expected_packets - packets_received) / expected_packets) * 100
    
    # Quality grade
    quality_grade = self._calculate_carrier_quality_grade(
        completeness_pct=completeness_pct,
        ntp_status=ntp_status
    )
    
    # Write CSV row
    writer.writerow([
        minute_dt.isoformat(),
        archive.unix_timestamp,
        minute_dt.minute,
        f"{completeness_pct:.2f}",
        f"{packet_loss_pct:.2f}",
        f"{ntp_status.get('offset_ms', 0):.3f}",
        ntp_status.get('stratum', 16),
        ntp_status.get('synchronized', False),
        f"{quality_info.rtp_drift_ms:.2f}" if hasattr(quality_info, 'rtp_drift_ms') else "0.00",
        quality_info.gap_count,
        quality_grade
    ])


def _calculate_carrier_quality_grade(
    self,
    completeness_pct: float,
    ntp_status: dict
) -> str:
    """
    Calculate quality grade for carrier channel minute
    
    Weighting:
    - Completeness: 60% (packet loss expected, but want consistency)
    - NTP quality: 40% (timing accuracy critical for Doppler)
    """
    score = 0
    
    # Completeness scoring (60 points max)
    if completeness_pct >= 95:
        score += 60
    elif completeness_pct >= 85:
        score += 50
    elif completeness_pct >= 70:
        score += 40
    elif completeness_pct >= 50:
        score += 25
    else:
        score += 10
    
    # NTP quality scoring (40 points max)
    if not ntp_status.get('synchronized', False):
        score += 0  # Fail if not synchronized
    else:
        offset_ms = abs(ntp_status.get('offset_ms', 999))
        stratum = ntp_status.get('stratum', 16)
        
        # Offset scoring (20 points)
        if offset_ms < 5:
            score += 20
        elif offset_ms < 10:
            score += 15
        elif offset_ms < 20:
            score += 10
        else:
            score += 5
        
        # Stratum scoring (20 points)
        if stratum <= 3:
            score += 20
        elif stratum <= 4:
            score += 15
        elif stratum <= 5:
            score += 10
        else:
            score += 5
    
    # Convert to letter grade
    if score >= 95:
        return 'A'
    elif score >= 85:
        return 'B'
    elif score >= 70:
        return 'C'
    elif score >= 50:
        return 'D'
    else:
        return 'F'
```

### 3. Web UI Enhancement

Display carrier channel quality metrics:

**Channels Page:**
```javascript
// Show NTP quality for carrier channels
if (channel.channel_type === 'carrier') {
    html += `
        <div class="metric">
            <label>Timing:</label>
            <span class="badge badge-ntp">📡 NTP_SYNCED</span>
        </div>
        <div class="metric">
            <label>NTP Offset:</label>
            <span>${channel.ntp_offset_ms?.toFixed(1) || 'N/A'} ms</span>
        </div>
        <div class="metric">
            <label>NTP Stratum:</label>
            <span>${channel.ntp_stratum || 'N/A'}</span>
        </div>
        <div class="metric">
            <label>Completeness:</label>
            <span class="${channel.completeness_pct >= 85 ? 'good' : 'warning'}">
                ${channel.completeness_pct?.toFixed(1) || 'N/A'}%
            </span>
        </div>
    `;
}
```

**New Quality Dashboard Page (`carrier-quality.html`):**
- Time series plot of NTP offset over 24 hours
- Completeness percentage histogram
- Packet loss statistics
- Quality grade distribution
- RTP drift trends

---

## Quality Thresholds & Alerts

### Alert Conditions

**Critical (Red):**
- NTP not synchronized
- Completeness < 50%
- NTP stratum > 10
- NTP offset > 100ms

**Warning (Yellow):**
- Completeness 50-85%
- NTP stratum > 5
- NTP offset 20-100ms
- Sustained RTP drift > 50ms/min

**Good (Green):**
- Completeness > 85%
- NTP stratum ≤ 5
- NTP offset < 20ms
- RTP drift < 20ms/min

---

## Scientific Provenance

### Per-Minute Documentation

Each carrier channel minute includes:

```
Carrier Channel Minute Record:
- Timestamp (UTC): 2025-11-18T02:00:00Z
- RTP Timestamp: 123456789
- Expected samples: 12,000 (200 Hz × 60s)
- Actual samples: 5,880 (49.0%)
- Packet loss: 50.8%
- Gaps filled: 6,120 samples (with zeros)

Timing Quality:
- Method: NTP_SYNCED (system clock)
- NTP synchronized: Yes
- NTP offset: +2.3ms
- NTP stratum: 3 (3 hops from reference)
- NTP reference: 192.168.1.1
- Estimated accuracy: ±10ms

Data Quality Grade: B (87/100)
- Completeness: 49.0% (25/60 points)
- NTP quality: Good (37/40 points)

Reprocessing: Not recommended (adequate for Doppler analysis)
```

### Daily Quality Report

Aggregate statistics per channel:

```
WWV 5 MHz Carrier - Daily Quality Report (2025-11-18)
============================================================
Minutes recorded: 1,440
Complete data (>95%): 0 (0.0%)
Good data (85-95%): 0 (0.0%)
Acceptable (70-85%): 0 (0.0%)
Fair (50-70%): 1,440 (100.0%)  ← Expected for carrier
Poor (<50%): 0 (0.0%)

NTP Synchronization:
  Synchronized: 1,440/1,440 (100.0%)
  Mean offset: 2.5ms (σ=0.8ms)
  Mean stratum: 3.2
  Max offset: 8.2ms
  Min offset: 0.3ms

Packet Reception:
  Mean completeness: 49.2%
  Mean packet loss: 50.8%
  Consistent with multicast over WiFi/local network

Quality Grade Distribution:
  A: 0 (0.0%)
  B: 1,380 (95.8%)  ← Typical
  C: 60 (4.2%)
  D: 0 (0.0%)
  F: 0 (0.0%)

Overall Assessment: GOOD
Carrier channel performing as expected with consistent
NTP sync and typical multicast packet loss.
```

---

## Files to Modify/Create

### Core Recorder
1. `src/signal_recorder/core_recorder.py`
   - Add `_get_ntp_status()` method
   - Add `_parse_chronyc_output()` and `_parse_ntpq_output()`
   - Capture NTP status during NPZ creation
   - Embed in NPZ metadata

### Analytics Service
2. `src/signal_recorder/analytics_service.py`
   - Add `_write_quality_csv_carrier()` method
   - Add `_calculate_carrier_quality_grade()` method
   - Detect carrier channels (check channel name or bandwidth)
   - Generate separate quality CSV format for carriers

### Web UI
3. `web-ui/carrier-quality.html` (new page)
   - NTP quality dashboard
   - Completeness trends
   - Quality grade distribution

4. `web-ui/monitoring-server-v3.js`
   - Add `/api/v1/carrier/quality` endpoint
   - Return NTP status and completeness metrics

### Documentation
5. `docs/CARRIER_QUALITY_METRICS.md`
   - Complete quality tracking specification
   - Interpretation guide for scientists

---

## Testing Protocol

### 1. NTP Status Capture
```bash
# Verify NTP query works
chronyc tracking

# Test parsing
python3 -c "from signal_recorder.core_recorder import CoreRecorder; \
  cr = CoreRecorder(); print(cr._get_ntp_status())"
```

### 2. Quality CSV Generation
```bash
# Restart analytics to apply changes
pkill -f analytics_service
bash start-dual-service.sh

# Check quality CSV for carrier channel
tail -20 /tmp/grape-test/analytics/WWV_5_MHz_carrier/quality/WWV_5_MHz_carrier_quality_$(date +%Y%m%d).csv
```

### 3. Quality Grade Validation
```bash
# Should see mostly B grades (good NTP, ~49% completeness typical)
python3 -c "
import pandas as pd
df = pd.read_csv('/tmp/grape-test/analytics/WWV_5_MHz_carrier/quality/WWV_5_MHz_carrier_quality_20251118.csv')
print(df['quality_grade'].value_counts())
"
```

---

## Summary

This design provides **comprehensive quality tracking for carrier channels** despite using NTP timing:

✅ **Sample integrity:** Gap detection, completeness tracking  
✅ **Packet statistics:** Loss rates, out-of-order detection  
✅ **NTP provenance:** Per-minute sync status, offset, stratum  
✅ **Quality grading:** Objective scoring (60% completeness, 40% NTP)  
✅ **Scientific transparency:** Full documentation of timing method and accuracy  

The key insight: **Lower timing accuracy doesn't mean lower quality tracking.** We document what we have (NTP ±10ms) with the same rigor as GPS timing (±1ms), enabling scientists to make informed decisions about data usage.
