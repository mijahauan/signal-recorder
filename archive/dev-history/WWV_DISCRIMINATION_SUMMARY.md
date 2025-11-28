# WWV/WWVH Discrimination - Complete System Overview

## Introduction

The GRAPE Signal Recorder implements a **comprehensive multi-method discrimination system** to distinguish between WWV (Fort Collins, CO) and WWVH (Kauai, HI) time signal stations. This document provides an overview of all discrimination methods and their integration.

## Discrimination Methods

### 1. BCD Correlation (100 Hz Subcarrier)
**Availability**: All minutes  
**Quality**: ★★★★☆ Very Good  
**Status**: ✅ Active

Both WWV and WWVH transmit **identical** BCD time code on a 100 Hz subcarrier. Cross-correlation detects two peaks separated by the ionospheric differential delay (typically 8-15 ms).

**Features:**
- Sliding 10-second windows with 3-second steps
- Joint least-squares amplitude estimation
- Adaptive windowing based on signal conditions
- ~15 measurements per minute

**Recent Enhancement**: Geographic ToA prediction for single-station detection

**Documentation**: `GEOGRAPHIC_TOA_PREDICTION.md`

---

### 2. Geographic Time-of-Arrival (ToA) Prediction
**Availability**: All minutes (when enabled)  
**Quality**: ★★★★☆ Very Good (single-station scenarios)  
**Status**: ✅ Active

Uses receiver location (Maidenhead grid) and known transmitter positions to predict expected ToA for each station. Enables classification of **single peaks** when only one station is received.

**Key Capabilities:**
- Converts grid square to lat/lon coordinates
- Calculates great circle distance to each transmitter
- Models ionospheric propagation delay (frequency-dependent)
- Maintains historical ToA measurements for empirical refinement
- Classifies single correlation peaks as WWV or WWVH

**Benefits:**
- Reduces discarded measurements when only one station present
- Improves data yield during poor propagation conditions
- Self-calibrating via historical tracking

**Configuration**:
```toml
[station]
grid_square = "EM38ww"  # Required for geographic ToA
```

**Documentation**: `GEOGRAPHIC_TOA_PREDICTION.md`

---

### 3. Test Signal Discrimination (Minute 8/44)
**Availability**: 2 minutes per hour  
**Quality**: ★★★★★ Excellent  
**Status**: ✅ Active (NEW!)

Detects the scientific modulation test signal transmitted:
- **Minute 8**: WWV only
- **Minute 44**: WWVH only

**Signal Features:**
- Phase-coherent multi-tone (2, 3, 4, 5 kHz)
- Systematic 3dB attenuation pattern
- Chirp sequences (0-5 kHz sweeps)
- Timing bursts for propagation measurement

**Detection Method:**
- Normalized cross-correlation against synthesized template
- Multi-tone correlation (primary, 70% weight)
- Chirp spectrogram analysis (confirmatory, 30% weight)
- Combined confidence threshold

**Advantages:**
- ✅ **Unambiguous**: No timing overlap between WWV and WWVH
- ✅ **High confidence**: Designed for detection
- ✅ **Multiple features**: Redundant discrimination
- ✅ **Deterministic**: Perfect template synthesis

**Documentation**: `TEST_SIGNAL_DISCRIMINATION.md`

---

### 4. 440 Hz Tone Detection
**Availability**: 2 minutes per hour  
**Quality**: ★★★☆☆ Good  
**Status**: ✅ Active

WWV transmits 440 Hz tone in minute 2; WWVH in minute 1.

**Benefits:**
- Harmonic-free reference frequency
- Hourly calibration anchor
- Simple presence/absence detection

---

### 5. Tick Analysis (1 kHz / 1.2 kHz)
**Availability**: All minutes  
**Quality**: ★★☆☆☆ Fair  
**Status**: ✅ Active

Analyzes per-second tick timing tones:
- WWV: 5 cycles @ 1000 Hz
- WWVH: 6 cycles @ 1200 Hz

Uses coherent and incoherent integration over 10-second windows.

---

## System Architecture

### Discrimination Pipeline

```
Phase 1: Tone Detection
   ↓
Phase 2: 440 Hz Analysis (minutes 1-2)
   ↓
Phase 3: Tick Discrimination (1 kHz/1.2 kHz)
   ↓
Phase 4: BCD Correlation (100 Hz)
   ├─ Dual-peak: Standard correlation
   └─ Single-peak: Geographic ToA classification
   ↓
Phase 4.5: Test Signal Detection (minutes 8, 44) ⭐ NEW!
   ├─ Multi-tone correlation
   ├─ Chirp detection
   └─ Override if high confidence
   ↓
Phase 5: Weighted Voting & Finalization
   ├─ BCD amplitude ratio (40%)
   ├─ Test signal (60% if detected)
   ├─ 440 Hz presence
   └─ Tick ratio
```

### Data Flow

```
IQ Samples (60 sec @ 16 kHz)
   ↓
WWVHDiscriminator.analyze_minute_with_440hz()
   ├─ MultiStationToneDetector → Tone presence
   ├─ BCD correlation → WWV/WWVH amplitudes
   │   └─ WWVGeographicPredictor → Single-peak classification
   ├─ WWVTestSignalDetector → Test signal ID (min 8/44)
   └─ Tick analysis → Power ratios
   ↓
DiscriminationResult
   ├─ dominant_station: 'WWV' or 'WWVH' or None
   ├─ confidence: 'high', 'medium', 'low'
   ├─ bcd_wwv_amplitude, bcd_wwvh_amplitude
   ├─ test_signal_detected, test_signal_station
   ├─ test_signal_confidence
   └─ Time-series data (bcd_windows, tick_windows)
```

## Performance Comparison

| Method | Availability | Confidence | Single-Station | Requires |
|--------|--------------|-----------|----------------|----------|
| **Test Signal** | Min 8, 44 | ★★★★★ | ✅ Yes | Nothing |
| **BCD + Geographic** | All mins | ★★★★☆ | ✅ Yes | Grid square |
| **BCD (Dual-peak)** | All mins | ★★★★☆ | ❌ No | Both stations |
| **440 Hz Tone** | Min 1-2 | ★★★☆☆ | ✅ Yes | Nothing |
| **Tick Analysis** | All mins | ★★☆☆☆ | ⚠️ Weak | Both stations |

## Configuration

### Required Settings

```toml
[station]
callsign = "AA0GG"
grid_square = "EM38ww"  # Enable geographic ToA prediction
instrument_id = "grape_001"

[[channel]]
name = "WWV_10_MHz"
center_frequency = 10000000
```

### Optional Tuning

**Geographic ToA Predictor** (`wwv_geographic_predictor.py`):
```python
# Ionosphere parameters
F2_PEAK_HEIGHT_KM = 300        # F2 layer peak
OBLIQUITY_FACTOR = 1.1         # Path elongation

# Classification thresholds
MIN_AMPLITUDE_THRESHOLD = 0.5  # Minimum correlation amplitude
MIN_QUALITY_THRESHOLD = 2.0    # Minimum SNR
```

**Test Signal Detector** (`wwv_test_signal.py`):
```python
# Detection thresholds
self.multitone_threshold = 0.15
self.chirp_threshold = 0.2
self.combined_threshold = 0.20
```

**BCD Correlation** (`wwvh_discrimination.py`):
```python
# Windowing parameters
window_seconds = 10    # Correlation window
step_seconds = 3       # Step between windows
adaptive = True        # Enable adaptive windowing
```

## Monitoring & Validation

### Log Monitoring

**Geographic ToA:**
```bash
tail -f /tmp/grape-test/logs/analytics_WWV_10_MHz.log | grep -i "geographic\|single.peak"
```

**Test Signal:**
```bash
tail -f /tmp/grape-test/logs/analytics_WWV_10_MHz.log | grep -i "test signal"
```

### Data Files

**ToA History:**
```
/tmp/grape-test/analytics/WWV_10_MHz/toa_history/toa_history_WWV_10_MHz.json
```

**Discrimination Results:**
```
/tmp/grape-test/analytics/WWV_10_MHz/discrimination/WWV_10_MHz_discrimination_YYYYMMDD.csv
```

**BCD Windows (Time-series):**
```
/tmp/grape-test/analytics/WWV_10_MHz/discrimination/WWV_10_MHz_bcd_YYYYMMDD.csv
```

### Expected Output

**Geographic ToA (Single-Peak Classification):**
```json
{
  "window_start_sec": 12.0,
  "wwv_amplitude": 0.0,
  "wwvh_amplitude": 1.85e-06,
  "differential_delay_ms": null,
  "correlation_quality": 5.23,
  "detection_type": "single_peak_wwvh",
  "peak_delay_ms": 23.125
}
```

**Test Signal Detection:**
```json
{
  "test_signal_detected": true,
  "test_signal_station": "WWV",
  "test_signal_confidence": 0.232,
  "test_signal_multitone_score": 0.204,
  "test_signal_chirp_score": 0.295,
  "test_signal_snr_db": -1.2
}
```

## Testing

### Geographic ToA Predictor
```bash
python3 test_geographic_predictor.py
```

### Test Signal Detector
```bash
python3 test_wwv_test_signal.py
```

Both generate validation plots in `/tmp/`.

## Implementation Timeline

### November 2025 - Phase 1 ✅
- [x] Geographic ToA prediction
  - Grid square conversion
  - Great circle distance
  - Ionospheric delay modeling
  - Historical tracking
  - Single-peak classification
- [x] Test signal detector
  - Signal generator
  - Multi-tone correlation
  - Chirp detection
  - Minute 8/44 integration

### Future Enhancements 🔮
- Adaptive test signal thresholds
- Propagation delay from test signal timing
- Doppler shift measurement from chirps
- Multi-path detection from echoes
- Ionospheric model integration
- Machine learning discrimination fusion

## Files

### Core Implementation
- `wwvh_discrimination.py` - Main discriminator class
- `wwv_geographic_predictor.py` - Geographic ToA prediction
- `wwv_test_signal.py` - Test signal generator/detector
- `bcd_encoder.py` - BCD template generation
- `tone_detector.py` - Multi-station tone detection

### Testing
- `test_geographic_predictor.py` - Geographic ToA validation
- `test_wwv_test_signal.py` - Test signal validation

### Documentation
- `WWV_DISCRIMINATION_SUMMARY.md` - This file
- `GEOGRAPHIC_TOA_PREDICTION.md` - ToA prediction details
- `TEST_SIGNAL_DISCRIMINATION.md` - Test signal details

### Integration
- `analytics_service.py` - Calls discriminator with config
- `monitoring-server-v3.js` - Serves discrimination data
- `discrimination.js` - Dashboard visualization

## References

- **WWV/WWVH Time Signals**: https://www.nist.gov/pml/time-and-frequency-division/time-distribution/radio-station-wwv
- **HamSCI WWV Project**: https://hamsci.org/wwv
- **Maidenhead Grid System**: https://en.wikipedia.org/wiki/Maidenhead_Locator_System
- **BCD Time Code Format**: NIST Special Publication 432
- **Test Signal Specification**: WWV/WWVH Scientific Modulation Working Group

---

**System Status**: ✅ All methods active and validated  
**Last Updated**: November 23, 2025  
**Next Milestone**: Real-world testing with minute 8/44 recordings
