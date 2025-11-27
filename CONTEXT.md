# ------------------------------
# AI PROJECT CONTEXT MANIFEST
# ------------------------------
# Instructions: Paste this entire file at the start of any new chat session
# to provide ground-truth context for the GRAPE Signal Recorder project.

## 🚨 IMMEDIATE CONTEXT: WWV/WWVH Discrimination Testing & Refinement

**NEXT SESSION GOAL:** Test, validate, and refine the 6 WWV/WWVH discrimination methods to ensure accurate station identification across all propagation conditions.

---

## 1. 📋 Discrimination System Overview

The GRAPE Signal Recorder uses **6 independent methods** to distinguish between WWV (Fort Collins, CO) and WWVH (Kauai, HI) signals on shared frequencies (2.5, 5, 10, 15 MHz).

### The 6 Methods at a Glance

| # | Method | Rate | Best For | Ground Truth? | Output Directory |
|---|--------|------|----------|---------------|------------------|
| 1 | **Timing Tones** | 1/min | Baseline measurement | No | `tone_detections/` |
| 2 | **Tick Windows** | 6/min | Sub-minute dynamics | No | `tick_windows/` |
| 3 | **440 Hz Station ID** | 2/hour | Calibration | **YES** (min 1=WWVH, 2=WWV) | `station_id_440hz/` |
| 4 | **Test Signal** | 2/hour | ToA calibration | **YES** (min 8=WWV, 44=WWVH) | `test_signal/` |
| 5 | **BCD Correlation** | ~50/min | Amplitude + delay | No | `bcd_discrimination/` |
| 6 | **Weighted Voting** | 1/min | Final determination | Combined | `discrimination/` |

### Method Details

#### Method 1: Timing Tones (1000/1200 Hz Power Ratio)
- **What:** Measures power of WWV's 1000 Hz tone vs WWVH's 1200 Hz tone during the 0.8s marker
- **When:** Every minute at seconds 0-0.8
- **Output:** `wwv_power_db`, `wwvh_power_db`, `power_ratio_db`
- **Limitation:** Cannot distinguish when both stations equally strong

#### Method 2: Tick Windows (5ms Coherent Integration)
- **What:** Per-second tick analysis with adaptive coherent/incoherent integration
- **When:** 6 windows per minute (10-second intervals)
- **Output:** Coherent/incoherent SNR for each station, coherence quality
- **Strength:** Captures sub-minute propagation variations

#### Method 3: 440 Hz Station ID (Ground Truth)
- **What:** Detects 440 Hz voice announcement tone
- **When:** Minute 1 = WWVH announces, Minute 2 = WWV announces
- **Output:** `wwv_detected`, `wwvh_detected`, power levels
- **Strength:** **GROUND TRUTH** - if detected, 100% accurate identification

#### Method 4: Test Signal (Ground Truth + ToA)
- **What:** Detects scientific modulation test signal (multi-tone + chirp)
- **When:** Minute 8 = WWV only, Minute 44 = WWVH only
- **Output:** `detected`, `station`, `snr_db`, `toa_offset_ms`
- **Strength:** **GROUND TRUTH** + high-precision ToA measurement for ionospheric characterization

#### Method 5: BCD Correlation (Primary Continuous Method)
- **What:** Cross-correlates 100 Hz BCD time code subcarrier
- **When:** Every 10 seconds (~6 windows per minute)
- **Output:** `wwv_amplitude`, `wwvh_amplitude`, `differential_delay_ms`, `correlation_quality`
- **Key Insight:** The 100 Hz BCD IS the carrier - both stations modulate it with identical timing
- **Strength:** Measures BOTH amplitude AND differential delay simultaneously

#### Method 6: Weighted Voting (Final Determination)
- **What:** Combines all methods with minute-specific weighting
- **When:** Once per minute (final output)
- **Output:** `dominant_station` (WWV/WWVH/BALANCED), `confidence`, `method_weights`
- **Weighting Logic:**
  - Ground truth methods (440 Hz, test signal) get highest weight when detected
  - BCD gets high weight for continuous measurement
  - Timing tones provide baseline
  - Tick windows add sub-minute resolution

---

## 2. 🗂️ Key Source Files

### Core Discrimination Logic

| File | Lines | Purpose |
|------|-------|---------|
| `src/signal_recorder/wwvh_discrimination.py` | ~2100 | **Main discriminator class** - `WWVHDiscriminator` |
| `src/signal_recorder/wwv_geographic_predictor.py` | ~520 | Geographic ToA prediction, dual-peak classification |
| `src/signal_recorder/wwv_test_signal.py` | ~580 | Test signal detection (min 8/44) |
| `src/signal_recorder/discrimination_csv_writers.py` | ~400 | CSV output for all methods |
| `src/signal_recorder/tone_detector.py` | ~500 | Timing tone detection (1000/1200 Hz) |

### Key Classes and Functions

```python
# wwvh_discrimination.py
class WWVHDiscriminator:
    def analyze_minute_with_440hz(iq_samples, sample_rate, minute_timestamp, frequency_mhz, detections) -> DiscriminationResult
    def compute_discrimination(detections, minute_timestamp) -> DiscriminationResult
    def finalize_discrimination(result, minute_number, bcd_*, tone_440_*, tick_results) -> DiscriminationResult
    def bcd_correlation_discrimination(iq_samples, sample_rate, minute_timestamp, frequency_mhz, grid_square) -> dict

# wwv_geographic_predictor.py
class WWVGeographicPredictor:
    def classify_dual_peaks(early_amplitude, late_amplitude, delta_geo_ms) -> dict
    def predict_toa_difference(frequency_mhz) -> dict
    def get_expected_delay_ms(station, frequency_mhz) -> float

# wwv_test_signal.py
class WWVTestSignalDetector:
    def detect_test_signal(iq_samples, sample_rate, minute_number) -> TestSignalDetection
```

### Data Structures

```python
@dataclass
class DiscriminationResult:
    minute_timestamp: float
    wwv_detected: bool
    wwvh_detected: bool
    wwv_power_db: Optional[float]
    wwvh_power_db: Optional[float]
    power_ratio_db: Optional[float]
    differential_delay_ms: Optional[float]
    dominant_station: Optional[str]  # 'WWV', 'WWVH', 'BALANCED'
    confidence: str  # 'high', 'medium', 'low'
    
    # 440 Hz Station ID
    tone_440hz_wwv_detected: bool
    tone_440hz_wwvh_detected: bool
    
    # BCD Correlation
    bcd_wwv_amplitude: Optional[float]
    bcd_wwvh_amplitude: Optional[float]
    bcd_differential_delay_ms: Optional[float]
    bcd_correlation_quality: Optional[float]
    bcd_windows: Optional[List[Dict]]
    
    # Test Signal
    test_signal_detected: bool
    test_signal_station: Optional[str]
    test_signal_toa_offset_ms: Optional[float]
    
    # Tick Windows
    tick_windows_10sec: Optional[List[Dict]]
```

---

## 3. 📁 Data Directories and CSV Formats

### Directory Structure (Test Mode)
```
/tmp/grape-test/analytics/{channel}/
├── tone_detections/     # Method 1: Timing tones
├── tick_windows/        # Method 2: Tick analysis
├── station_id_440hz/    # Method 3: 440 Hz ID
├── test_signal/         # Method 4: Test signal
├── bcd_discrimination/  # Method 5: BCD correlation
├── discrimination/      # Method 6: Final voting
├── doppler/             # Doppler measurements
├── toa_history/         # ToA tracking
└── decimated/           # 10 Hz NPZ files
```

### CSV Column Headers

**tone_detections/{channel}_tones_YYYYMMDD.csv:**
```
timestamp_utc,station,frequency_hz,duration_sec,timing_error_ms,snr_db,tone_power_db,confidence,use_for_time_snap
```

**bcd_discrimination/{channel}_bcd_YYYYMMDD.csv:**
```
timestamp_utc,window_start_sec,wwv_amplitude,wwvh_amplitude,differential_delay_ms,correlation_quality,amplitude_ratio_db
```

**station_id_440hz/{channel}_440hz_YYYYMMDD.csv:**
```
timestamp_utc,minute_number,wwv_detected,wwvh_detected,wwv_power_db,wwvh_power_db
```

**test_signal/{channel}_test_signal_YYYYMMDD.csv:**
```
timestamp_utc,minute_number,detected,station,confidence,multitone_score,chirp_score,snr_db,toa_offset_ms
```

**discrimination/{channel}_discrimination_YYYYMMDD.csv:**
```
timestamp_utc,dominant_station,confidence,method_weights,minute_type
```

---

## 4. 🧪 Testing & Validation Commands

### Check Data Generation
```bash
# Verify all method directories have data
ls -la /tmp/grape-test/analytics/WWV_10_MHz/

# Check BCD discrimination output
tail -20 /tmp/grape-test/analytics/WWV_10_MHz/bcd_discrimination/*_bcd_*.csv

# Check 440 Hz station ID (should have data at minutes 1 and 2)
cat /tmp/grape-test/analytics/WWV_10_MHz/station_id_440hz/*_440hz_*.csv

# Check test signal detection (minutes 8 and 44)
cat /tmp/grape-test/analytics/WWV_10_MHz/test_signal/*_test_signal_*.csv

# Check final discrimination output
tail -30 /tmp/grape-test/analytics/WWV_10_MHz/discrimination/*_discrimination_*.csv
```

### Run Analytics Manually
```bash
cd /home/wsprdaemon/signal-recorder
source venv/bin/activate

# Process a specific archive file
python3 -c "
from signal_recorder.analytics_service import AnalyticsService
svc = AnalyticsService('/tmp/grape-test', 'WWV 10 MHz')
# Process will run on next available archive
"

# Test discrimination on a specific minute
python3 -c "
import numpy as np
from signal_recorder.wwvh_discrimination import WWVHDiscriminator

disc = WWVHDiscriminator('WWV 10 MHz')
# Load test data and run analyze_minute_with_440hz()
"
```

### Web UI Testing
```bash
# Start monitoring server
cd /home/wsprdaemon/signal-recorder/web-ui
pnpm start

# Access discrimination data via API
curl http://localhost:3000/api/v1/channels/WWV_10_MHz/discrimination/20251127/methods | python3 -m json.tool
curl http://localhost:3000/api/v1/channels/WWV_10_MHz/discrimination/20251127/bcd | python3 -m json.tool
```

---

## 5. 🎯 Testing Objectives

### Validation Criteria

1. **Ground Truth Accuracy:**
   - 440 Hz detection at minute 1 should identify WWVH
   - 440 Hz detection at minute 2 should identify WWV
   - Test signal at minute 8 should identify WWV
   - Test signal at minute 44 should identify WWVH

2. **BCD Correlation Quality:**
   - Should show two distinct amplitudes when both stations propagating
   - `differential_delay_ms` should be consistent with geographic prediction
   - `correlation_quality` should be > 0.5 for valid measurements

3. **Geographic Consistency:**
   - For station at EM38ww (Kansas):
     - WWV (Colorado) is ~800 km away
     - WWVH (Hawaii) is ~5500 km away
     - WWV should arrive ~15-20 ms earlier than WWVH

4. **Weighted Voting Logic:**
   - Ground truth methods should override when detected
   - Confidence should reflect measurement quality
   - `dominant_station` should match strongest signal

### Known Issues to Investigate

1. **BCD Dual-Peak Assignment:** Does `classify_dual_peaks()` correctly assign WWV/WWVH based on geographic prediction?

2. **Test Signal ToA:** Is `toa_offset_ms` providing meaningful ionospheric path length measurements?

3. **Tick Window Coherence:** Is coherent integration being selected when phase is stable?

4. **Method Weighting:** Are the weights in `finalize_discrimination()` optimal for different propagation conditions?

---

## 6. 📖 Essential Documentation

### Must-Read Files
- `WWV_WWVH_DISCRIMINATION_METHODS.md` - Detailed method descriptions
- `docs/WWV_WWVH_DISCRIMINATION_USER_GUIDE.md` - User-facing guide
- `CANONICAL_CONTRACTS.md` - API standards (read before code changes)
- `DIRECTORY_STRUCTURE.md` - Path conventions

### Recent Session Notes
- `CONTEXT.md` (previous) - Audio streaming implementation (Nov 26)
- `CRITICAL_FIXES_IMPLEMENTED.md` - Thread safety, timing fixes

---

## 7. 🌐 Station Reference

### WWV (Fort Collins, Colorado)
- **Coordinates:** 40.6779°N, 105.0392°W
- **Frequencies:** 2.5, 5, 10, 15, 20, 25 MHz
- **Timing Tone:** 1000 Hz (0.8 seconds)
- **Voice ID:** Minute 2 (440 Hz announcement)
- **Test Signal:** Minute 8

### WWVH (Kekaha, Kauai, Hawaii)
- **Coordinates:** 22.0534°N, 159.7619°W
- **Frequencies:** 2.5, 5, 10, 15 MHz ONLY (no 20/25 MHz)
- **Timing Tone:** 1200 Hz (0.8 seconds)
- **Voice ID:** Minute 1 (440 Hz announcement)
- **Test Signal:** Minute 44

### Receiver Location (AC0G)
- **Grid Square:** EM38ww (Kansas)
- **Distance to WWV:** ~800 km
- **Distance to WWVH:** ~5500 km
- **Expected Differential:** WWV arrives ~15-20 ms before WWVH

---

## 8. 🔧 Quick Reference

### Activate Environment
```bash
cd /home/wsprdaemon/signal-recorder
source venv/bin/activate
```

### Start Services
```bash
# Web UI (port 3000)
cd web-ui && pnpm start

# Core recorder (if needed)
cd .. && python3 -m signal_recorder.grape_channel_recorder_v2
```

### Key API Endpoints
```
GET /api/v1/channels/:name/discrimination/:date/methods  # All methods
GET /api/v1/channels/:name/discrimination/:date/bcd      # BCD only
GET /api/v1/channels/:name/discrimination/:date/station_id # 440 Hz
GET /api/v1/channels/:name/discrimination/:date/test_signal # Min 8/44
```

### File Naming Convention
```
{channel}_tones_YYYYMMDD.csv
{channel}_bcd_YYYYMMDD.csv
{channel}_440hz_YYYYMMDD.csv
{channel}_test_signal_YYYYMMDD.csv
{channel}_discrimination_YYYYMMDD.csv
```

---

## 9. 🏗️ Architecture Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                    GRAPE Signal Recorder                        │
├─────────────────────────────────────────────────────────────────┤
│  ka9q-radio RTP → Core Recorder → 16kHz NPZ Archives           │
│                         ↓                                       │
│              Analytics Service (per channel)                    │
│                         ↓                                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │            WWVHDiscriminator.analyze_minute_with_440hz() │   │
│  │                         ↓                                │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │   │
│  │  │ Timing   │ │  Tick    │ │  440 Hz  │ │   Test   │    │   │
│  │  │  Tones   │ │ Windows  │ │   ID     │ │  Signal  │    │   │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘    │   │
│  │       │            │            │            │           │   │
│  │       └────────────┼────────────┼────────────┘           │   │
│  │                    ↓            ↓                        │   │
│  │              ┌──────────┐ ┌──────────┐                   │   │
│  │              │   BCD    │ │ Weighted │                   │   │
│  │              │  Corr.   │ │  Voting  │                   │   │
│  │              └────┬─────┘ └────┬─────┘                   │   │
│  │                   │            │                         │   │
│  │                   ↓            ↓                         │   │
│  │            Separated CSV Files (per method)              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                         ↓                                       │
│              10Hz Decimation → Digital RF → Upload              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 10. ✅ What Was Completed (Nov 26-27)

### Audio Streaming ✅
- Live audio playback from Summary page
- AM demodulation with AGC, 12 kHz via WebSocket
- Files: `radiod_audio_client.py`, `monitoring-server-v3.js`, `summary.html`

### Geographic BCD Discrimination ✅
- `classify_dual_peaks()` uses geographic ToA to assign WWV/WWVH
- Test signal ToA offset measurement added

### Timing System ✅
- Thread-safe core recorder
- Stable wall clock prediction
- Timing dashboard with drift analysis
