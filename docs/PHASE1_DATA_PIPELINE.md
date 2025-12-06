# Phase 1: Raw Data Pipeline Architecture

## Overview

Phase 1 is the foundation of the GRAPE recording system. It captures raw 20 kHz IQ
samples from ka9q-radio's RTP multicast stream and stores them in Digital RF (DRF)
format as the immutable source of truth.

**Design Principle:** Raw data integrity > all other concerns.

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            KA9Q-RADIO (radiod)                              │
│  Generates RTP packets with 32-bit timestamps (sample counter at 20 kHz)   │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼ UDP Multicast
┌─────────────────────────────────────────────────────────────────────────────┐
│                          RTPReceiver (rtp_receiver.py)                      │
│  - Parses RTP headers (sequence, timestamp, SSRC, payload)                  │
│  - Calculates wallclock time if channel timing info available               │
│  - Dispatches to registered callbacks by SSRC                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     PacketResequencer (packet_resequencer.py)               │
│  - 64-packet circular buffer (handles ~1.3s network jitter)                 │
│  - Reorders out-of-sequence packets                                         │
│  - Detects gaps via RTP timestamp jumps                                     │
│  - Handles 32-bit RTP wraparound with signed arithmetic                     │
│  - Fills gaps with zeros (maintains sample count integrity)                 │
│  - Detects stream discontinuities (>10s jumps) → resets state               │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    RawArchiveWriter (raw_archive_writer.py)                 │
│  - Establishes RTP→SystemTime mapping (SystemTimeReference)                 │
│  - Writes to Digital RF format (HDF5-based)                                 │
│  - DRF global_index = system_time × sample_rate (64-bit, no wraparound)     │
│  - Validates samples (NaN, Inf, clipping)                                   │
│  - Records gaps and quality metrics                                         │
│  - Periodic flush, watchdog, and heartbeat (resilience)                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Digital RF Archive                                │
│  Directory: raw_archive/{CHANNEL}/{YYYYMMDD}/{ISO-TIMESTAMP}/               │
│  Files: rf@{GLOBAL_INDEX}.h5 (60-second file cadence)                       │
│  Metadata: Station, frequency, sample rate, compression, NTP status         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Time Bases

### 1. RTP Timestamp (from radiod)
| Property | Value |
|----------|-------|
| **Width** | 32-bit unsigned |
| **Resolution** | 1 sample (50 μs at 20 kHz) |
| **Wraparound** | Every ~59.6 hours at 20 kHz |
| **Source** | radiod's internal sample counter |
| **Used for** | Gap detection, packet ordering, relative timing |

### 2. System Time (wall clock)
| Property | Value |
|----------|-------|
| **Width** | 64-bit float (seconds since Unix epoch) |
| **Resolution** | Nanosecond precision |
| **Wraparound** | Never (billions of years) |
| **Source** | Host system clock (NTP-synchronized) |
| **Used for** | DRF global index, absolute timing reference |

### 3. DRF Global Sample Index
| Property | Value |
|----------|-------|
| **Width** | 64-bit integer |
| **Calculation** | `int(system_time × sample_rate)` |
| **Wraparound** | Never |
| **Used for** | File positioning, data access |

---

## RTP Timestamp Wraparound Handling

The 32-bit RTP timestamp wraps every ~59.6 hours at 20 kHz:
```
2^32 samples ÷ 20,000 samples/sec = 214,748 seconds ≈ 59.6 hours
```

### KA9Q Signed-Difference Technique

The code uses Phil Karn's (KA9Q) technique for handling wraparound:

```python
# Calculate signed difference (handles wraparound naturally)
ts_diff = (new_timestamp - expected_timestamp) & 0xFFFFFFFF

# Convert to signed: values > 2^31 are treated as negative
if ts_diff >= 0x80000000:
    ts_diff = ts_diff - 0x100000000  # Now negative

# ts_diff is now a signed value:
#   Positive = forward gap (missing samples)
#   Negative = backward jump (duplicate/late packet)
#   Zero = exactly as expected
```

This technique works correctly within a ~29.8 hour window (half the wraparound period).

---

## SystemTimeReference: The Bridge

The `SystemTimeReference` dataclass establishes the mapping between RTP timestamps
and system wall-clock time:

```python
@dataclass
class SystemTimeReference:
    rtp_timestamp: int        # RTP timestamp at reference point
    system_time: float        # System wall clock at reference point
    ntp_offset_ms: float      # NTP offset if known (for provenance)
    sample_rate: int          # For conversion calculations
    
    def calculate_time_at_sample(self, sample_rtp: int) -> float:
        """Convert RTP timestamp to system time."""
        rtp_diff = sample_rtp - self.rtp_timestamp
        # Handle 32-bit wraparound...
        elapsed_seconds = rtp_diff / self.sample_rate
        return self.system_time + elapsed_seconds
```

### When It's Established
- On first packet after service start
- After stream discontinuity reset (gap > 10 seconds)
- After massive gap recovery (gap > 20 seconds)

### Current Limitation
The reference is **not persisted** across service restarts. After restart,
a new reference is established from the first received packet.

---

## Resilience Mechanisms

### 1. Heartbeat (every 60s)
```
📡 WWV_10_MHz heartbeat: 72,000,000 samples, 5 gaps, 0 errors
```
- **Trigger:** Wall-clock time (`time.time()`)
- **Purpose:** Confirm the writer is actively processing data
- **What it monitors:** Sample count, gap count, error count

### 2. Forced Flush (every 60s)
- **Trigger:** Wall-clock time
- **Action:** Close and reopen DRF writer
- **Purpose:** Ensure data is written to disk, not just buffered

### 3. Watchdog (timeout: 120s)
- **Trigger:** No successful `rf_write()` calls for 120 seconds
- **Action:** Close and recreate DRF writer
- **Purpose:** Recover from stalled DRF library state

### 4. Large Gap Recovery (threshold: 20s)
- **Trigger:** Detected gap > 400,000 samples (20 seconds at 20 kHz)
- **Action:** Reset DRF writer AND SystemTimeReference
- **Purpose:** Re-establish timing after major disruption

---

## Gap Detection and Handling

### Small Gaps (< 10 seconds)
- Fill with zeros (maintains sample count)
- Log warning with gap size
- Continue recording

### Medium Gaps (10-20 seconds) 
- Detected by resequencer as discontinuity
- Reset resequencer state
- Continue with new sequence

### Large Gaps (> 20 seconds)
- Reset DRF writer completely
- Re-establish SystemTimeReference
- Start fresh timing context

---

## Recovery After Service Stop/Restart

### Current Behavior
1. All in-memory state is lost
2. DRF writer starts fresh from current system time
3. First packet establishes new SystemTimeReference
4. Recording continues seamlessly (DRF handles day boundaries)

### What's Preserved
- Previous DRF files (immutable)
- Directory structure
- Metadata files

### What's NOT Preserved
- RTP→SystemTime mapping (re-established)
- Resequencer buffer (empty on start)
- Gap statistics (reset to zero)

---

## Logging During Different States

### Normal Operation
```
INFO: 📡 WWV_10_MHz heartbeat: 72,000,000 samples, 0 gaps, 0 errors
```

### Gap Detected
```
WARNING: ⚠️ Large gap detected: 20000 samples (1000.0ms)
WARNING: Gap detected: 20000 samples (50 packets), ts 1000000 -> 1020000
```

### Stream Discontinuity
```
WARNING: Stream discontinuity detected: timestamp jump of 500000 samples (25.0 seconds)
INFO: Resequencer reset #1: new seq=1234, ts=5000000
```

### Writer Reset
```
WARNING: ⚠️ Massive gap (500000 samples = 25.0s) - resetting DRF writer to resync
INFO: Creating DRF writer for 2025-12-06
INFO: System time reference set: RTP=5000000, system_time=1733489234.567
```

### Watchdog Intervention
```
WARNING: ⚠️ Watchdog: No writes for 120s - resetting DRF writer
```

---

## Future Enhancements

### 1. Persistent Time Reference
Save `SystemTimeReference` to disk periodically:
```python
{
    "rtp_timestamp": 1234567890,
    "system_time": 1733489234.567890,
    "ntp_offset_ms": 0.123,
    "last_update": "2025-12-06T12:00:00Z"
}
```
On restart, load and validate before using (check for RTP wraparound).

### 2. RTP Epoch Tracking
Track which RTP wraparound epoch we're in:
```python
{
    "rtp_epoch": 3,  # Number of complete wraparounds
    "epoch_start_system_time": 1733400000.0
}
```

### 3. Continuous Health Metrics
Expose real-time metrics for monitoring:
- Samples written per minute
- Gap rate (gaps per hour)
- Writer state (active/stalled/recovering)
- Time since last successful write

---

## Summary: Time Basis Hierarchy

| Priority | Time Source | Used When | Fallback |
|----------|-------------|-----------|----------|
| 1 | RTP Timestamp | Normal packet ordering | N/A |
| 2 | SystemTimeReference | RTP→absolute time | Wall clock |
| 3 | Wall Clock (NTP) | DRF indexing, heartbeat | System time |
| 4 | Wall Clock (raw) | Emergency fallback | None |

The system is designed to degrade gracefully:
- If RTP stalls → Watchdog resets writer
- If NTP lost → Warning logged, recording continues
- If time jumps → Writer resets and re-syncs
