# GRAPE Timing & Quality Analysis: wsprdaemon vs signal-recorder

## Executive Summary

After reviewing wsprdaemon's `pcmrecord.c`, `grape-utils.sh`, and `wav2grape.py`, the key to GRAPE data quality is **precise timing tied to UTC boundaries** and **explicit gap handling**. Our implementation needs critical fixes in these areas.

---

## wsprdaemon's Timing Strategy

### 1. UTC Boundary Synchronization

**pcmrecord.c state machine**:
```c
case sync_state_startup:
    // Wait until second 59
    if (seconds == (FileLengthLimit - 1)) {
        sp->sync_state = sync_state_armed;
    }
    break;

case sync_state_armed:
    // Drop samples until second 0
    if (0 == seconds) {
        // START recording at exactly :00
        sp->wd_file_time.tv_sec = 0;
        session_file_init(sp, sender);
        sp->sync_state = sync_state_active;
    }
    break;
```

**Key Point**: Files start at **exact UTC minute boundaries** (00, 01, 02, ..., 59 seconds)

### 2. RTP Timestamp Validation

```c
// Track expected vs actual RTP timestamps
if ((0 != sp->total_file_samples) && 
    (sp->rtp_state.timestamp != sp->next_expected_rtp_ts)) {
    wd_log(0, "Weird rtp.timestamp: expected %u, received %u (delta %d)\n",
           sp->next_expected_rtp_ts,
           sp->rtp_state.timestamp,
           sp->rtp_state.timestamp - sp->next_expected_rtp_ts);
}
sp->next_expected_rtp_ts = sp->rtp_state.timestamp + frames;
```

**Key Point**: Every RTP timestamp is validated against expected progression

### 3. Gap Detection and Silence Insertion

```c
int jump = (int32_t)(qp->rtp.timestamp - sp->rtp_state.timestamp);
if (jump > 0) {
    // Timestamp jumped - emit silence padding
    fprintf(stderr, "timestamp jump %d frames\n", jump);
    
    if (sp->can_seek)
        fseeko(sp->fp, framesize * jump, SEEK_CUR);  // Seek forward (leaves zeros)
    else {
        unsigned char *zeroes = calloc(jump, framesize);
        fwrite(zeroes, framesize, jump, sp->fp);      // Write explicit zeros
        FREE(zeroes);
    }
    
    sp->rtp_state.timestamp += jump;
    sp->total_file_samples += jump;
}
```

**Key Point**: Missing samples are **explicitly filled with silence** to maintain timeline continuity

### 4. First Sample Timing Validation

```c
// Check if first sample is within tolerance of expected UTC boundary
struct timespec expected_start = now;
expected_start.tv_nsec = 0;
expected_start.tv_sec += (time_t)(FileLengthLimit / 2);
expected_start.tv_sec /= (time_t)(FileLengthLimit);
expected_start.tv_sec *= (time_t)(FileLengthLimit);

if (fabs(time_diff(expected_start, now)) >= wd_tolerance_seconds) {
    wd_log(0, "First sample %.3f s off...resync at next interval\n",
           time_diff(expected_start, now));
    sp->sync_state = sync_state_resync;
}
```

**Key Point**: Verifies timing is within **±2 seconds** of UTC boundary, resyncs if not

### 5. Digital RF Conversion with Precise Start Time

**wav2grape.py**:
```python
# Extract exact date from directory structure
start_datetime = datetime.strptime(path_element, '%Y%m%d').replace(tzinfo=timezone.utc)
start_time = start_datetime.timestamp()  # Midnight UTC

# Calculate global sample index
start_global_index = int(start_time * sample_rate)

with drf.DigitalRFWriter(channel_dir,
                         dtype,
                         subdir_cadence_secs,
                         file_cadence_millisecs,
                         start_global_index,      # <-- Precise to midnight UTC
                         sample_rate,
                         1,                        # sample_rate_denominator
                         uuid_str,
                         compression_level,
                         False,                    # checksum
                         num_channels == 2,        # is_complex
                         len(subchannels),         # num_subchannels
                         True,                     # is_continuous (no gaps!)
                         False) as do:
    do.rf_write(np.hstack(samples))
```

**Key Point**: `start_global_index` is tied to **midnight UTC**, not stream start time

---

## Our Current Implementation Issues

### ❌ Issue 1: No UTC Boundary Alignment

**Current code (grape_rtp_recorder.py)**:
```python
# Daemon starts whenever user runs it
self.start_time = time.time()  # Could be 13:47:23.456 UTC

# No synchronization to UTC boundaries
# Data collection starts immediately
```

**Impact**:
- Files don't align to midnight UTC
- Start time drifts based on daemon startup
- Digital RF `start_global_index` will be incorrect

### ❌ Issue 2: Timing Based on System Clock

**Current code**:
```python
unix_time = time.time()  # Current system time, NOT RTP timestamp
self.daily_buffer.add_samples(unix_time, resampled)
```

**Impact**:
- Ignores precise RTP timestamps
- Subject to system clock drift/jitter
- No way to detect timing jumps

### ❌ Issue 3: No Gap Detection or Filling

**Current code**:
```python
if self.last_sequence is not None:
    expected_seq = (self.last_sequence + 1) & 0xFFFF
    if header.sequence != expected_seq:
        dropped = (header.sequence - expected_seq) & 0xFFFF
        self.packets_dropped += dropped
        logger.warning(f"Dropped {dropped} packets")
        # BUT NO SILENCE INSERTION!
```

**Impact**:
- Gaps in RTP stream = missing samples in output
- Timeline is discontinuous
- Digital RF `is_continuous=True` would be **incorrect**
- PSWS will reject data

### ❌ Issue 4: Incorrect Start Time for Digital RF

**Current code**:
```python
# DailyBuffer uses stream start time, not UTC midnight
self.current_day = datetime.now(timezone.utc).date()
```

**Impact**:
- `start_global_index` will not align to midnight UTC
- Digital RF metadata will be incorrect
- PSWS upload will fail metadata validation

---

## Required Fixes

### Fix 1: UTC Boundary Synchronization

```python
class GRAPEChannelRecorder:
    def __init__(self, ...):
        self.sync_state = 'startup'  # startup → armed → active
        self.utc_aligned_start = None
        
    def process_rtp_packet(self, header: RTPHeader, payload: bytes):
        now = time.time()
        current_second = int(now) % 60
        
        if self.sync_state == 'startup':
            # Wait for second 59
            if current_second == 59:
                self.sync_state = 'armed'
                logger.info(f"{self.channel_name}: Armed, waiting for :00")
                
        elif self.sync_state == 'armed':
            # Drop samples until second 0
            if current_second == 0:
                # Start recording at exact UTC minute boundary
                self.utc_aligned_start = int(now / 60) * 60
                self.rtp_start_timestamp = header.timestamp
                self.sync_state = 'active'
                logger.info(f"{self.channel_name}: Started recording at UTC {datetime.fromtimestamp(self.utc_aligned_start, timezone.utc)}")
                
        elif self.sync_state == 'active':
            # Normal processing (see Fix 2)
            pass
```

### Fix 2: RTP Timestamp-Based Timing

```python
def _calculate_sample_time(self, rtp_timestamp: int) -> float:
    """
    Calculate Unix time for this sample based on RTP timestamp.
    
    Args:
        rtp_timestamp: RTP timestamp (12 kHz clock for real samples)
        
    Returns:
        Unix timestamp (seconds since epoch)
    """
    if self.sync_state != 'active':
        return time.time()  # Fallback before sync
    
    # Calculate elapsed time since recording started
    # RTP timestamp is in 12 kHz units (real samples, not complex)
    rtp_elapsed = (rtp_timestamp - self.rtp_start_timestamp) & 0xFFFFFFFF
    elapsed_seconds = rtp_elapsed / 12000.0
    
    # Add to UTC-aligned start time
    return self.utc_aligned_start + elapsed_seconds
```

### Fix 3: Gap Detection and Silence Insertion

```python
def _process_rtp_packet(self, header: RTPHeader, payload: bytes):
    # ... unpack samples ...
    
    # Detect gaps
    if self.last_sequence is not None:
        expected_seq = (self.last_sequence + 1) & 0xFFFF
        if header.sequence != expected_seq:
            gap_packets = (header.sequence - expected_seq) & 0xFFFF
            
            # Calculate timing of gap
            expected_rtp_ts = self.last_rtp_timestamp + (120 * gap_packets)  # 120 samples/packet
            actual_rtp_ts = header.timestamp
            
            # Verify gap is consistent
            rtp_gap = (actual_rtp_ts - expected_rtp_ts) & 0xFFFFFFFF
            if abs(rtp_gap) < 240:  # Within tolerance
                # Insert silence for missing packets
                gap_complex_samples = gap_packets * 120  # Input samples at 6 kHz complex
                gap_output_samples = gap_complex_samples // 600  # After 600:1 decimation
                
                if gap_output_samples > 0:
                    silence = np.zeros(gap_output_samples, dtype=np.complex64)
                    gap_time = self._calculate_sample_time(expected_rtp_ts)
                    self.daily_buffer.add_samples(gap_time, silence)
                    
                    logger.warning(f"{self.channel_name}: Filled {gap_packets} dropped packets "
                                 f"({gap_output_samples} output samples) with silence")
            else:
                logger.error(f"{self.channel_name}: RTP timestamp inconsistent with sequence gap!")
    
    self.last_sequence = header.sequence
    self.last_rtp_timestamp = header.timestamp
    
    # Process actual samples
    sample_time = self._calculate_sample_time(header.timestamp)
    # ... resample and add to buffer ...
```

### Fix 4: UTC Midnight-Aligned Digital RF Writing

```python
class DailyBuffer:
    def get_drf_start_time(self, date: datetime.date) -> float:
        """
        Get midnight UTC timestamp for given date.
        This is what Digital RF start_global_index must be based on.
        """
        midnight_utc = datetime.combine(date, datetime.min.time(), tzinfo=timezone.utc)
        return midnight_utc.timestamp()
    
def _write_digital_rf(self, day_date, data: np.ndarray):
    # Calculate start_global_index for midnight UTC
    start_time = self.daily_buffer.get_drf_start_time(day_date)
    start_global_index = int(start_time * 10)  # 10 Hz sample rate
    
    with drf.DigitalRFWriter(
        str(drf_path),
        np.complex64,
        3600,           # subdir_cadence_secs
        1000,           # file_cadence_millisecs  
        start_global_index,  # <-- CRITICAL: Midnight UTC
        10,             # sample_rate_numerator
        1,              # sample_rate_denominator
        uuid.uuid4().hex,
        6,              # compression_level
        False,          # checksum
        True,           # is_complex
        1,              # num_subchannels
        True,           # is_continuous (NOW VALID because we fill gaps!)
        False           # marching_periods
    ) as writer:
        writer.rf_write(data)
```

---

## Implementation Priority

1. **CRITICAL**: Fix #2 (RTP timestamp-based timing) - Required for accurate data
2. **CRITICAL**: Fix #3 (Gap filling) - Required for continuous timeline
3. **HIGH**: Fix #4 (UTC midnight alignment) - Required for PSWS upload
4. **MEDIUM**: Fix #1 (Boundary sync) - Nice to have, reduces file fragmentation

---

## Validation Plan

1. **Unit Test Gap Filling**:
   - Simulate dropped RTP packets
   - Verify silence insertion
   - Check output sample count matches expected

2. **Timing Accuracy Test**:
   - Compare RTP timestamp-based time vs system time
   - Measure drift over 24 hours
   - Verify alignment to UTC midnight

3. **Digital RF Validation**:
   - Use `drf_check.py` to verify file integrity
   - Check `is_continuous` flag is honored
   - Verify `start_global_index` matches midnight UTC

4. **Comparison with wsprdaemon**:
   - Record same channel with both systems
   - Compare Digital RF metadata
   - Verify sample counts match
   - Check timing alignment

---

## Quality Metrics

Our system should achieve:

- ✅ **Timing accuracy**: ±10 ms vs UTC boundaries
- ✅ **Gap handling**: 100% timeline continuity with silence fill
- ✅ **Sample rate**: 10.000 Hz (not 9.999 or 10.001)
- ✅ **Completeness**: 100% even with packet loss
- ✅ **PSWS compatibility**: Metadata matches wsprdaemon format

---

## References

- wsprdaemon `pcmrecord.c`: RTP timing and gap handling
- wsprdaemon `wav2grape.py`: Digital RF conversion
- Digital RF specification: https://github.com/MITHaystack/digital_rf
- PSWS requirements: Contact pswsnetwork.eng.ua.edu
