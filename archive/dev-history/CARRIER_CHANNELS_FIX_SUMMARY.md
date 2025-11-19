# Carrier Channels Fix Summary
## Date: 2025-11-17

## ✅ FIXES APPLIED

### 1. **Sample Rate Bug** (Critical)
**Problem**: `grape_channel_recorder_v2.py` line 83 hardcoded `self.sample_rate = 16000`

**Impact**:
- Carrier channels (200 Hz) expected 960,000 samples/minute instead of 12,000
- Caused wrong buffer calculations, byte parsing errors, NaN values in output

**Fix**:
```python
# Before
self.sample_rate = 16000  # TODO: Get from channel config

# After  
self.sample_rate = sample_rate  # From channel config parameter
```

**Files Modified**:
- `src/signal_recorder/grape_channel_recorder_v2.py` (lines 60, 85, 130)
- `src/signal_recorder/grape_rtp_recorder.py` (line 992)

### 2. **RTP Timestamp Rate Bug** (Critical)
**Problem**: Line 130 hardcoded `self.rtp_sample_rate = 16000`

**Impact**: RTP timestamp calculations incorrect for non-16kHz channels

**Fix**:
```python
# Before
self.rtp_sample_rate = 16000  # RTP timestamp rate (real samples)

# After
self.rtp_sample_rate = self.sample_rate  # Matches IQ sample rate
```

### 3. **Tone Detection on Carrier Channels** (Design)
**Problem**: Carrier channels (200 Hz bandwidth) cannot contain 1000 Hz WWV tones

**Fix**: Disable tone detection for channels < 8 kHz:
```python
self.is_wwv_channel = is_wwv_channel and self.sample_rate >= 8000
```

## ✅ VERIFICATION

Carrier channel NPZ files now contain valid data:
```
File: 20251117T233300Z_5000000_iq.npz (WWV 5 MHz carrier)
- Samples: 11,620 (expected ~12,000 for 200 Hz × 60 sec)
- Valid data: 60.5% (7,033 non-zero samples)
- NaN values: 0
- Magnitude range: 3×10⁻⁵ to 2.3×10⁻⁴  ✅
```

## ⚠️ REMAINING HARDCODED VALUES

These should be abstracted for future flexibility:

### Tone Detection Parameters (Lines 160-850)
**Current State**: Hardcoded for 16 kHz → 3 kHz resampling

Hardcoded values:
```python
Line 160:  sample_rate=3000              # Tone processing rate
Line 203:  fs_proc = 3000                # Processing sample rate
Line 707:  len(all_iq)/16000             # Buffer duration calculation
Line 712:  buffer_duration = len(all_iq) / 16000
Line 718:  int(7.0 * 16000)              # Start sample calculation
Line 719:  start_sample_16k + 256000     # 16-second window
Line 774:  int(0.5 * 3000)               # Search window
Line 813:  (timing_offset_samples / 3000) * 1000  # Timing error
Line 816:  int(peak_idx * (16000 / 3000))  # Coordinate conversion
Line 822:  onset_in_buffer_16k / 16000   # UTC time calculation
```

### Recommended Abstraction

Create channel parameters class:

```python
@dataclass
class ChannelParameters:
    """Channel-specific recording parameters"""
    sample_rate: int                    # IQ sample rate (16000 or 200)
    tone_detection_enabled: bool        # Based on bandwidth
    tone_processing_rate: int = 3000    # For wide channels only
    tone_resample_ratio: float = None   # Calculated: sample_rate / tone_processing_rate
    
    def __post_init__(self):
        if self.tone_detection_enabled:
            self.tone_resample_ratio = self.sample_rate / self.tone_processing_rate
```

Then replace hardcoded calculations:
```python
# Instead of: len(all_iq) / 16000
buffer_duration = len(all_iq) / self.params.sample_rate

# Instead of: int(peak_idx * (16000 / 3000))
onset_in_window = int(peak_idx * self.params.tone_resample_ratio)

# Instead of: onset_in_buffer_16k / 16000  
onset_utc_time = (minute_key - seconds_before_minute) + (onset_in_buffer / self.params.sample_rate)
```

## 📊 CHANNEL TYPES

### Wide Channels (16 kHz IQ)
- **Purpose**: WWV/CHU tone detection, discrimination analysis
- **Tone detection**: Enabled (resample 16k → 3k)
- **Timing**: GPS_LOCKED via tone detection
- **Channels**: WWV 2.5/5/10/15/20/25 MHz, CHU 3.33/7.85/14.67 MHz

### Carrier Channels (200 Hz IQ)
- **Purpose**: 10 Hz carrier Doppler analysis  
- **Tone detection**: Disabled (insufficient bandwidth)
- **Timing**: NTP_SYNCED (±10ms, adequate for Doppler)
- **Channels**: Same frequencies as wide, labeled "carrier"

## 🔧 FUTURE WORK

1. **Create ChannelParameters dataclass** for clean abstraction
2. **Parameterize all tone detection calculations** using sample rates
3. **Add Digital RF decimation parameters** for carrier channels (200 Hz → 10 Hz vs 16 kHz → 10 Hz)
4. **Configuration validation**: Warn if tone detection requested on narrow channels

## 📁 FILES MODIFIED

- `src/signal_recorder/grape_channel_recorder_v2.py`
- `src/signal_recorder/grape_rtp_recorder.py`

## 🎯 KEY INSIGHT

The root cause was **sample rate assumptions baked into the code**. The PT 97 payload type investigation was a red herring - radiod sends identical int16 format for all IQ presets. The real issue was expecting all channels to be 16 kHz.
