# GRAPE Signal Recorder API Reference
*Complete API documentation for all services and modules*

## Table of Contents

1. [Tone Detector API](#tone-detector-api)
2. [WWV-H Discrimination API](#wwv-h-discrimination-api)
3. [Analytics Service API](#analytics-service-api)
4. [DRF Writer Service API](#drf-writer-service-api)
5. [Data Models](#data-models)
6. [Configuration](#configuration)

---

## Tone Detector API

### `MultiStationToneDetector`

**Location:** `src/signal_recorder/tone_detector.py`

**Purpose:** Detects WWV (1000 Hz), WWVH (1200 Hz), and CHU (1000 Hz) time signal tones using phase-invariant quadrature matched filtering.

#### Constructor

```python
MultiStationToneDetector(
    channel_name: str,
    sample_rate: int = 3000
)
```

**Parameters:**
- `channel_name` (str): Channel name like "WWV 5 MHz", "CHU 7.85 MHz"
  - Determines which station types to detect
  - Extracts frequency to enable/disable WWVH detection
- `sample_rate` (int, optional): Processing sample rate in Hz (default: 3000)

**Behavior:**
- WWV channels (2.5, 5, 10, 15 MHz): Detects WWV + WWVH
- WWV channels (20, 25 MHz): Detects WWV only (WWVH doesn't broadcast here)
- CHU channels: Detects CHU only

**Example:**
```python
detector = MultiStationToneDetector("WWV 5 MHz")  # Detects WWV + WWVH
detector = MultiStationToneDetector("WWV 20 MHz") # Detects WWV only
detector = MultiStationToneDetector("CHU 7.85 MHz") # Detects CHU only
```

#### Methods

##### `process_samples()` ⭐ **PRIMARY METHOD**

```python
process_samples(
    timestamp: float,
    samples: np.ndarray,
    rtp_timestamp: int
) -> List[ToneDetectionResult]
```

**Parameters:**
- `timestamp` (float): UTC timestamp at buffer midpoint (where minute boundary is expected)
- `samples` (np.ndarray): IQ samples at 3000 Hz (must be pre-resampled!)
- `rtp_timestamp` (int): RTP timestamp for tracking

**Returns:**
- `List[ToneDetectionResult]`: Detected tones (may be empty if no detections)

**Notes:**
- Expects samples at 3000 Hz - you must resample from 16 kHz first!
- Searches ±500ms window around expected minute boundary
- Buffer should include at least 60s of data centered on minute boundary

**Resampling Example:**
```python
from scipy import signal as scipy_signal

# Resample 16 kHz → 3 kHz
resampled = scipy_signal.resample_poly(
    iq_samples_16khz,
    up=3,
    down=16,
    axis=0
)

# Detect tones
detections = detector.process_samples(
    timestamp=minute_timestamp,  # UTC of minute boundary
    samples=resampled,           # 3 kHz IQ samples
    rtp_timestamp=rtp_ts
)

for det in detections:
    print(f"{det.station.value}: {det.timing_error_ms:+.1f}ms, SNR={det.snr_db:.1f}dB")
```

##### `detect_tone_onset()` (Legacy - returns bool)

```python
detect_tone_onset(
    iq_samples: np.ndarray,
    buffer_start_time: float
) -> bool
```

**Note:** This is a legacy method that returns a boolean. Use `process_samples()` instead for full detection results.

---

## WWV-H Discrimination API

### `WWVHDiscriminator`

**Location:** `src/signal_recorder/wwvh_discrimination.py`

**Purpose:** Discriminate between WWV and WWVH stations using three methods: 1000/1200 Hz power ratio, differential delay, and 440 Hz station-specific tones.

#### Constructor

```python
WWVHDiscriminator(channel_name: str)
```

**Parameters:**
- `channel_name` (str): Channel name for logging (e.g., "WWV 5 MHz")

**Example:**
```python
discriminator = WWVHDiscriminator("WWV 5 MHz")
```

#### Methods

##### `compute_discrimination()`

**Basic discrimination** (1000 Hz vs 1200 Hz power, differential delay only)

```python
compute_discrimination(
    detections: List[ToneDetectionResult],
    minute_timestamp: float
) -> DiscriminationResult
```

**Parameters:**
- `detections` (List[ToneDetectionResult]): Tone detections from MultiStationToneDetector
- `minute_timestamp` (float): UTC timestamp of minute boundary

**Returns:**
- `DiscriminationResult`: Analysis result (always returns, even if no detections)

##### `analyze_minute_with_440hz()` ⭐ **RECOMMENDED**

**Complete discrimination** (includes 440 Hz tone analysis)

```python
analyze_minute_with_440hz(
    iq_samples: np.ndarray,
    sample_rate: int,
    minute_timestamp: float,
    detections: List[ToneDetectionResult]
) -> DiscriminationResult
```

**Parameters:**
- `iq_samples` (np.ndarray): Full minute of complex IQ samples
- `sample_rate` (int): Sample rate (typically 16000 Hz)
- `minute_timestamp` (float): UTC timestamp of minute boundary
- `detections` (List[ToneDetectionResult]): Pre-computed tone detections

**Returns:**
- `DiscriminationResult`: Complete analysis including 440 Hz detection

**440 Hz Detection:**
- Minute 1 (XX:01:15-59): Detects WWVH 440 Hz tone
- Minute 2 (XX:02:15-59): Detects WWV 440 Hz tone
- Other minutes: No 440 Hz analysis

**Example:**
```python
discrimination = discriminator.analyze_minute_with_440hz(
    iq_samples=archive.iq_samples,
    sample_rate=16000,
    minute_timestamp=minute_ts,
    detections=detections
)

print(f"WWV: {discrimination.wwv_detected}, WWVH: {discrimination.wwvh_detected}")
print(f"Power ratio: {discrimination.power_ratio_db:+.1f} dB")
print(f"Dominant: {discrimination.dominant_station} ({discrimination.confidence})")
if discrimination.tone_440hz_wwv_detected:
    print(f"WWV 440 Hz confirmed!")
```

##### `detect_440hz_tone()`

**Manual 440 Hz detection** (usually called internally)

```python
detect_440hz_tone(
    iq_samples: np.ndarray,
    sample_rate: int,
    minute_number: int
) -> Tuple[bool, Optional[float]]
```

**Parameters:**
- `iq_samples` (np.ndarray): Full minute of IQ samples
- `sample_rate` (int): Sample rate
- `minute_number` (int): Minute number (0-59); only processes minutes 1 and 2

**Returns:**
- `(detected: bool, power_db: Optional[float])`

---

## Analytics Service API

### `AnalyticsService`

**Location:** `src/signal_recorder/analytics_service.py`

**Purpose:** Orchestrates tone detection, decimation, quality metrics, and WWV-H discrimination for a single channel.

#### Constructor

```python
AnalyticsService(
    channel_name: str,
    frequency_hz: float,
    archive_directory: Path,
    output_directory: Path,
    station_config: dict
)
```

**Parameters:**
- `channel_name` (str): Channel name (e.g., "WWV 5 MHz")
- `frequency_hz` (float): Center frequency in Hz (e.g., 5_000_000)
- `archive_directory` (Path): Directory containing raw *_iq.npz files
- `output_directory` (Path): Base output directory for analytics products
- `station_config` (dict): Station configuration

**Station Config Required Fields:**
```python
{
    'callsign': str,           # Station callsign
    'grid_square': str,        # Maidenhead grid square
    'receiver_name': str,      # Receiver identifier
    'psws_station_id': str,    # PSWS station ID
    'psws_instrument_id': str  # PSWS instrument ID
}
```

**Example:**
```python
from pathlib import Path

service = AnalyticsService(
    channel_name="WWV 5 MHz",
    frequency_hz=5_000_000,
    archive_directory=Path("/tmp/grape-test/archives/WWV_5_MHz"),
    output_directory=Path("/tmp/grape-test/analytics/WWV_5_MHz"),
    station_config={
        'callsign': 'W1ABC',
        'grid_square': 'FN42',
        'receiver_name': 'grape_v2_receiver_1',
        'psws_station_id': 'station_001',
        'psws_instrument_id': 'grape_v2'
    }
)
```

#### Methods

##### `process_archive()`

```python
process_archive(archive: NPZArchive) -> dict
```

**Parameters:**
- `archive` (NPZArchive): Loaded NPZ archive

**Returns:**
- `dict`: Processing results with keys:
  - `'detections'`: List of tone detections
  - `'time_snap_updated'`: bool
  - `'decimated_file'`: Path or None
  - `'errors'`: List of error messages

**Pipeline:**
1. Tone detection (WWV/WWVH/CHU)
2. Time_snap update
3. Quality metrics calculation
4. WWV-H discrimination (if applicable)
5. Decimation to 10 Hz
6. Write decimated NPZ file

##### `run()`

```python
run(poll_interval: float = 10.0)
```

**Parameters:**
- `poll_interval` (float): Seconds between directory scans (default: 10.0)

**Behavior:**
- Polls `archive_directory` for new *_iq.npz files
- Processes files in chronological order
- Writes status files periodically
- Runs until stopped

---

## DRF Writer Service API

### `DRFWriterService`

**Location:** `src/signal_recorder/drf_writer_service.py`

**Purpose:** Converts 10 Hz decimated NPZ files to Digital RF HDF5 format for upload.

#### Constructor

```python
DRFWriterService(
    input_dir: Path,
    output_dir: Path,
    channel_name: str,
    frequency_hz: float,
    analytics_state_file: Path,
    station_config: dict
)
```

**Parameters:**
- `input_dir` (Path): Directory containing *_iq_10hz.npz files
- `output_dir` (Path): Output directory for Digital RF files
- `channel_name` (str): Channel name
- `frequency_hz` (float): Center frequency in Hz
- `analytics_state_file` (Path): Path to analytics state JSON (for time_snap)
- `station_config` (dict): Station configuration (same as Analytics Service)

**Example:**
```python
from pathlib import Path

service = DRFWriterService(
    input_dir=Path("/tmp/grape-test/archives/WWV_5_MHz"),
    output_dir=Path("/tmp/grape-test/digital_rf/WWV_5_MHz"),
    channel_name="WWV 5 MHz",
    frequency_hz=5_000_000,
    analytics_state_file=Path("/tmp/grape-test/analytics/WWV_5_MHz/analytics_state.json"),
    station_config={
        'callsign': 'W1ABC',
        'grid_square': 'FN42',
        'receiver_name': 'grape_v2_receiver_1',
        'psws_station_id': 'station_001',
        'psws_instrument_id': 'grape_v2'
    }
)
```

#### Methods

##### `write_to_drf()`

```python
write_to_drf(
    archive: DecimatedArchive,
    time_snap: Optional[TimeSnapReference]
)
```

**Parameters:**
- `archive` (DecimatedArchive): Loaded 10 Hz decimated archive
- `time_snap` (TimeSnapReference | None): Current time_snap for UTC conversion

**Behavior:**
- Creates DRF writer if needed (new day)
- Calculates UTC timestamp from time_snap or file creation time
- Writes IQ samples with monotonic sample indexing
- Writes optional metadata channels
- Detects and skips backwards-time writes

##### `run()`

```python
run(poll_interval: float = 10.0)
```

**Parameters:**
- `poll_interval` (float): Seconds between directory scans (default: 10.0)

**Behavior:**
- Polls `input_dir` for new *_iq_10hz.npz files
- Loads time_snap from analytics state
- Processes files in chronological order
- Writes Digital RF + metadata channels

---

## Data Models

### `ToneDetectionResult`

**Location:** `src/signal_recorder/interfaces/data_models.py`

```python
@dataclass
class ToneDetectionResult:
    station: StationType          # WWV, WWVH, or CHU
    timestamp: float              # Precise tone onset time (UTC)
    timing_error_ms: float        # Error relative to minute boundary (ms)
    snr_db: float                 # Signal-to-noise ratio (dB)
    confidence: float             # Detection confidence (0.0-1.0)
    tone_power_db: float          # FFT-based tone power (dB)
    use_for_time_snap: bool       # Whether suitable for time_snap
```

### `DiscriminationResult`

**Location:** `src/signal_recorder/wwvh_discrimination.py`

```python
@dataclass
class DiscriminationResult:
    minute_timestamp: float                    # UTC timestamp of minute
    wwv_detected: bool                         # WWV 1000 Hz detected
    wwvh_detected: bool                        # WWVH 1200 Hz detected
    wwv_power_db: Optional[float]              # WWV tone power (dB)
    wwvh_power_db: Optional[float]             # WWVH tone power (dB)
    power_ratio_db: Optional[float]            # WWV - WWVH (dB)
    differential_delay_ms: Optional[float]     # Arrival time diff (ms)
    dominant_station: Optional[str]            # 'WWV', 'WWVH', 'BALANCED'
    confidence: str                            # 'high', 'medium', 'low'
    tone_440hz_wwv_detected: bool              # 440 Hz in minute 2
    tone_440hz_wwv_power_db: Optional[float]   # Power (dB)
    tone_440hz_wwvh_detected: bool             # 440 Hz in minute 1
    tone_440hz_wwvh_power_db: Optional[float]  # Power (dB)
```

### `NPZArchive`

**Location:** `src/signal_recorder/interfaces/data_models.py`

```python
@dataclass
class NPZArchive:
    file_path: Path
    iq_samples: np.ndarray         # Complex IQ samples
    rtp_timestamp: int             # RTP timestamp of first sample
    sample_rate: int               # Sample rate (Hz)
    unix_timestamp: float          # File creation time (UTC)
    packets_received: int          # Packets successfully received
    packets_expected: int          # Expected packets
    gaps_filled: int               # Samples filled due to gaps
    gaps_count: int                # Number of gaps
    # ... gap details arrays ...
    
    @classmethod
    def load(cls, file_path: Path) -> 'NPZArchive':
        """Load NPZ archive from disk"""
```

### `DecimatedArchive`

**Location:** `src/signal_recorder/drf_writer_service.py`

```python
@dataclass
class DecimatedArchive:
    file_path: Path
    iq_samples: np.ndarray         # Decimated IQ samples (10 Hz)
    rtp_timestamp: int             # RTP timestamp (original rate)
    sample_rate_original: int      # Original rate (16000 Hz)
    sample_rate_decimated: int     # Decimated rate (10 Hz)
    decimation_factor: int         # Ratio (1600)
    created_timestamp: float       # Creation time (UTC)
    source_file: str               # Original filename
    
    # Optional metadata (future expansion)
    timing_metadata: Optional[Dict]
    quality_metadata: Optional[Dict]
    discrimination_metadata: Optional[Dict]
    
    @classmethod
    def load(cls, file_path: Path) -> 'DecimatedArchive':
        """Load 10 Hz decimated NPZ file"""
```

### `TimeSnapReference`

**Location:** `src/signal_recorder/drf_writer_service.py`

```python
@dataclass
class TimeSnapReference:
    rtp_timestamp: int      # RTP timestamp at tone onset
    utc_timestamp: float    # UTC timestamp at tone onset
    sample_rate: int        # Sample rate for RTP conversion
    source: str             # "WWV" or "CHU"
    confidence: float       # Detection confidence
    station: str            # Station identifier
    
    def calculate_sample_time(self, rtp_timestamp: int) -> float:
        """Convert RTP timestamp to UTC using this time_snap"""
```

---

## Configuration

### Station Config Dictionary

Required for both Analytics and DRF Writer services:

```python
station_config = {
    'callsign': 'W1ABC',                      # Station callsign
    'grid_square': 'FN42',                    # Maidenhead grid square
    'receiver_name': 'grape_v2_receiver_1',   # Unique receiver name
    'psws_station_id': 'station_001',         # PSWS/HamSCI station ID
    'psws_instrument_id': 'grape_v2'          # Instrument type ID
}
```

### File Naming Conventions

**Raw NPZ Archives:**
```
{YYYYMMDDTHHMMSS}Z_{frequency_hz}_iq.npz
Example: 20251116T120000Z_5000000_iq.npz
```

**Decimated NPZ Archives:**
```
{YYYYMMDDTHHMMSS}Z_{frequency_hz}_iq_10hz.npz
Example: 20251116T120000Z_5000000_iq_10hz.npz
```

**Discrimination CSV:**
```
{channel_name}_discrimination_{YYYYMMDD}.csv
Example: WWV_5_MHz_discrimination_20251116.csv
```

### Directory Structure

```
/tmp/grape-test/
├── archives/
│   └── WWV_5_MHz/
│       ├── 20251116T120000Z_5000000_iq.npz       # Raw 16 kHz
│       └── 20251116T120000Z_5000000_iq_10hz.npz  # Decimated 10 Hz
├── analytics/
│   └── WWV_5_MHz/
│       ├── analytics_state.json                   # Time_snap, state
│       ├── discrimination_logs/
│       │   └── WWV_5_MHz_discrimination_20251116.csv
│       └── status_WWV_5_MHz.json                  # Live status
└── digital_rf/
    └── WWV_5_MHz/
        └── 20251116/                              # Daily directories
            ├── rf_data/                           # IQ samples
            └── metadata/                          # Metadata channels
                ├── timing_quality/
                ├── data_quality/
                └── wwvh_discrimination/
```

---

## Quick Reference

### Minimal Working Example - Full Pipeline

```python
from pathlib import Path
from signal_recorder.tone_detector import MultiStationToneDetector
from signal_recorder.wwvh_discrimination import WWVHDiscriminator
from signal_recorder.interfaces.data_models import NPZArchive

# Configuration
channel_name = "WWV 5 MHz"
archive_file = Path("/tmp/grape-test/archives/WWV_5_MHz/20251116T120100Z_5000000_iq.npz")

# Initialize components
detector = MultiStationToneDetector(channel_name)
discriminator = WWVHDiscriminator(channel_name)

# Load data
archive = NPZArchive.load(archive_file)

# Detect tones
detections = detector.detect_tones(
    iq_samples=archive.iq_samples,
    sample_rate=archive.sample_rate,
    minute_timestamp=archive.unix_timestamp
)

# Discriminate WWV/WWVH (includes 440 Hz analysis)
discrimination = discriminator.analyze_minute_with_440hz(
    iq_samples=archive.iq_samples,
    sample_rate=archive.sample_rate,
    minute_timestamp=archive.unix_timestamp,
    detections=detections
)

# Results
print(f"Detections: {len(detections)}")
for det in detections:
    print(f"  {det.station.value}: {det.timing_error_ms:+.1f}ms, SNR={det.snr_db:.1f}dB")

print(f"\nDiscrimination:")
print(f"  WWV: {discrimination.wwv_detected}, WWVH: {discrimination.wwvh_detected}")
print(f"  Power ratio: {discrimination.power_ratio_db:+.1f} dB")
print(f"  Dominant: {discrimination.dominant_station} ({discrimination.confidence})")
print(f"  440 Hz WWV: {discrimination.tone_440hz_wwv_detected}")
print(f"  440 Hz WWVH: {discrimination.tone_440hz_wwvh_detected}")
```

---

## Common Patterns

### Pattern 1: Check if WWVH detection is enabled

```python
detector = MultiStationToneDetector("WWV 5 MHz")
has_wwvh = StationType.WWVH in detector.templates
# True for 2.5, 5, 10, 15 MHz; False for 20, 25 MHz
```

### Pattern 2: Load time_snap from analytics state

```python
import json
from signal_recorder.drf_writer_service import TimeSnapReference

state_file = Path("/tmp/grape-test/analytics/WWV_5_MHz/analytics_state.json")
if state_file.exists():
    with open(state_file) as f:
        state = json.load(f)
        if 'time_snap' in state:
            ts = state['time_snap']
            time_snap = TimeSnapReference(
                rtp_timestamp=ts['rtp_timestamp'],
                utc_timestamp=ts['utc_timestamp'],
                sample_rate=ts['sample_rate'],
                source=ts['source'],
                confidence=ts['confidence'],
                station=ts['station']
            )
```

### Pattern 3: Batch process archives

```python
from pathlib import Path
import numpy as np

archive_dir = Path("/tmp/grape-test/archives/WWV_5_MHz")
detector = MultiStationToneDetector("WWV 5 MHz")

for npz_file in sorted(archive_dir.glob("*_iq.npz")):
    archive = NPZArchive.load(npz_file)
    detections = detector.detect_tones(
        archive.iq_samples,
        archive.sample_rate,
        archive.unix_timestamp
    )
    print(f"{npz_file.name}: {len(detections)} detections")
```

---

## Version History

- **v1.0** (2025-11-16): Initial API reference
  - Frequency-aware WWVH detection
  - 440 Hz integration
  - Complete discrimination pipeline
