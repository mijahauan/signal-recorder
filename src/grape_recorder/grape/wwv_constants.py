#!/usr/bin/env python3
"""
WWV/WWVH/CHU Shared Constants

Centralizes timing constants, frequency schedules, and configuration values
used across the Phase 2 analytics modules.

Reference: NIST Special Publication 432 (WWV and WWVH specifications)
"""

from typing import Dict, Set, Optional

# =============================================================================
# SAMPLE RATE CONSTANTS
# =============================================================================

SAMPLE_RATE_FULL = 20000  # Hz - Full rate from radiod RTP stream
SAMPLE_RATE_LEGACY = 16000  # Hz - Legacy 16 kHz mode (deprecated)

# =============================================================================
# STATION BROADCAST SCHEDULES
# =============================================================================

# Minutes where only one station broadcasts 500/600 Hz tones (ground truth)
# These provide unambiguous station identification
WWV_ONLY_TONE_MINUTES: Set[int] = {1, 16, 17, 19}
WWVH_ONLY_TONE_MINUTES: Set[int] = {2, 43, 44, 45, 46, 47, 48, 49, 50, 51}

# 440 Hz tone schedule (for station discrimination)
# Minute 1: WWVH broadcasts 440 Hz
# Minute 2: WWV broadcasts 440 Hz
MINUTE_440HZ_WWVH = 1
MINUTE_440HZ_WWV = 2

# Test signal minutes (scientific modulation test)
# Note: Test signal is IDENTICAL for WWV/WWVH - discrimination from schedule
WWV_TEST_SIGNAL_MINUTE = 8
WWVH_TEST_SIGNAL_MINUTE = 44

# =============================================================================
# 500/600 Hz TONE SCHEDULE (Complete 60-minute cycle)
# =============================================================================

# Per-minute schedule: {minute: {'WWV': freq_or_None, 'WWVH': freq_or_None}}
TONE_SCHEDULE_500_600: Dict[int, Dict[str, Optional[int]]] = {
    0: {'WWV': None, 'WWVH': None},
    1: {'WWV': 600, 'WWVH': 440},   # 440 Hz ground truth minutes
    2: {'WWV': 440, 'WWVH': 600},
    3: {'WWV': 600, 'WWVH': 500},
    4: {'WWV': 500, 'WWVH': 600},
    5: {'WWV': 600, 'WWVH': 500},
    6: {'WWV': 500, 'WWVH': 600},
    7: {'WWV': 600, 'WWVH': 500},
    8: {'WWV': None, 'WWVH': None},   # Test signal minute (WWV)
    9: {'WWV': None, 'WWVH': None},
    10: {'WWV': None, 'WWVH': None},
    11: {'WWV': 600, 'WWVH': 500},
    12: {'WWV': 500, 'WWVH': 600},
    13: {'WWV': 600, 'WWVH': 500},
    14: {'WWV': None, 'WWVH': None},
    15: {'WWV': None, 'WWVH': None},
    16: {'WWV': 500, 'WWVH': None},   # WWV-only
    17: {'WWV': 600, 'WWVH': None},   # WWV-only
    18: {'WWV': None, 'WWVH': None},
    19: {'WWV': 600, 'WWVH': None},   # WWV-only
    20: {'WWV': 500, 'WWVH': 600},
    21: {'WWV': 600, 'WWVH': 500},
    22: {'WWV': 500, 'WWVH': 600},
    23: {'WWV': 600, 'WWVH': 500},
    24: {'WWV': 500, 'WWVH': 600},
    25: {'WWV': 600, 'WWVH': 500},
    26: {'WWV': 500, 'WWVH': 600},
    27: {'WWV': 600, 'WWVH': 500},
    28: {'WWV': 500, 'WWVH': 600},
    29: {'WWV': None, 'WWVH': None},
    30: {'WWV': None, 'WWVH': None},
    31: {'WWV': 600, 'WWVH': 500},
    32: {'WWV': 500, 'WWVH': 600},
    33: {'WWV': 600, 'WWVH': 500},
    34: {'WWV': 500, 'WWVH': 600},
    35: {'WWV': 600, 'WWVH': 500},
    36: {'WWV': 500, 'WWVH': 600},
    37: {'WWV': 600, 'WWVH': 500},
    38: {'WWV': 500, 'WWVH': 600},
    39: {'WWV': 600, 'WWVH': 500},
    40: {'WWV': 500, 'WWVH': 600},
    41: {'WWV': 600, 'WWVH': 500},
    42: {'WWV': 500, 'WWVH': 600},
    43: {'WWV': None, 'WWVH': 500},   # WWVH-only
    44: {'WWV': None, 'WWVH': 600},   # WWVH-only (+ test signal)
    45: {'WWV': None, 'WWVH': 500},   # WWVH-only
    46: {'WWV': None, 'WWVH': 600},   # WWVH-only
    47: {'WWV': None, 'WWVH': 500},   # WWVH-only
    48: {'WWV': None, 'WWVH': 600},   # WWVH-only
    49: {'WWV': None, 'WWVH': 500},   # WWVH-only
    50: {'WWV': None, 'WWVH': 600},   # WWVH-only
    51: {'WWV': None, 'WWVH': 500},   # WWVH-only
    52: {'WWV': 500, 'WWVH': 600},
    53: {'WWV': 600, 'WWVH': 500},
    54: {'WWV': 500, 'WWVH': 600},
    55: {'WWV': 600, 'WWVH': 500},
    56: {'WWV': 500, 'WWVH': 600},
    57: {'WWV': 600, 'WWVH': 500},
    58: {'WWV': 500, 'WWVH': 600},
    59: {'WWV': None, 'WWVH': None}
}

# =============================================================================
# STATION LOCATIONS (for propagation delay calculations)
# =============================================================================

# WWV - Fort Collins, Colorado, USA
WWV_LAT = 40.6775
WWV_LON = -105.0472

# WWVH - Kekaha, Kauai, Hawaii, USA  
WWVH_LAT = 21.9886
WWVH_LON = -159.7639

# CHU - Ottawa, Ontario, Canada
CHU_LAT = 45.2925
CHU_LON = -75.7542

# =============================================================================
# TONE FREQUENCIES (Hz)
# =============================================================================

# Fundamental timing markers
WWV_TICK_FREQ = 1000   # Hz - WWV uses 1000 Hz tick
WWVH_TICK_FREQ = 1200  # Hz - WWVH uses 1200 Hz tick
CHU_TICK_FREQ = 1000   # Hz - CHU uses 1000 Hz tick

# =============================================================================
# CHU TIMING STRUCTURE (Reference: NRC CHU Technical Specifications)
# =============================================================================

# CHU 1000 Hz tone pattern per minute:
# - Second 00: 0.5s tone (minute marker) - 1.0s at top of hour
# - Seconds 01-08: 0.3s tones (or DUT1 split tones for positive DUT1)
# - Seconds 09-16: 0.3s tones (or DUT1 split tones for negative DUT1)
# - Seconds 17-28: 0.3s tones (regular)
# - Second 29: ALWAYS SILENT (distinguishes CHU from WWV)
# - Second 30: 0.3s tone
# - Seconds 31-39: 10ms ticks only (FSK digital time code transmitted)
# - Seconds 40-49: 0.3s tones (regular)
# - Seconds 50-59: 10ms ticks only (voice announcements)

CHU_MINUTE_MARKER_DURATION = 0.5   # seconds (0.5s at :00, 1.0s at top of hour)
CHU_REGULAR_TONE_DURATION = 0.3    # seconds
CHU_TICK_DURATION = 0.01           # seconds (10ms during FSK/voice)
CHU_SILENT_SECOND = 29             # Always omitted
CHU_FSK_SECONDS = set(range(31, 40))    # Digital time code (Bell 103 AFSK)
CHU_VOICE_SECONDS = set(range(50, 60))  # Voice announcements

# DUT1 encoding seconds (split tones: 0.1s + 0.1s silence + 0.1s)
CHU_DUT1_POSITIVE_SECONDS = set(range(1, 9))   # +0.1s to +0.8s
CHU_DUT1_NEGATIVE_SECONDS = set(range(9, 17))  # -0.1s to -0.8s

# CHU FSK parameters (Bell 103 AFSK)
CHU_FSK_MARK_FREQ = 2225   # Hz (bit 1)
CHU_FSK_SPACE_FREQ = 2025  # Hz (bit 0)
CHU_FSK_BAUD_RATE = 300    # bits per second

# Extended tones for discrimination
TONE_440_HZ = 440
TONE_500_HZ = 500
TONE_600_HZ = 600

# =============================================================================
# DETECTION THRESHOLDS
# =============================================================================

# SNR thresholds for anchor quality (dB)
ANCHOR_SNR_HIGH = 15.0      # Very confident anchor
ANCHOR_SNR_MEDIUM = 10.0    # Usable anchor
ANCHOR_SNR_LOW = 6.0        # Marginal anchor

# Confidence thresholds for transmission time solver
SOLVER_MIN_CONFIDENCE = 0.3     # Minimum confidence for valid solution
UTC_VERIFICATION_THRESHOLD_MS = 2.0  # Maximum UTC offset for verification

# =============================================================================
# PROPAGATION CONSTANTS
# =============================================================================

# Speed of light (km/s) for propagation delay calculations
SPEED_OF_LIGHT_KM_S = 299792.458

# Earth radius (km) for path length calculations
EARTH_RADIUS_KM = 6371.0

# Ionospheric layer heights (km)
E_LAYER_HEIGHT_KM = 110.0
F_LAYER_HEIGHT_KM = 300.0

# Ionospheric delay per hop (ms) - empirical average
IONOSPHERIC_DELAY_PER_HOP_MS = 0.15

# Maximum frequency-dependent dispersion (ms)
MAX_DISPERSION_MS = 3.0

# Minimum WWV-WWVH time separation (ms)
STATION_SEPARATION_MS = 15.0

# =============================================================================
# PROPAGATION PLAUSIBILITY BOUNDS (ms)
# =============================================================================
# 
# These define the plausible range of propagation delays for each station.
# Used to reject false detections outside reasonable ionospheric paths.
#
# Conservative bounds that should work for continental US receivers:
# - Ground wave: ~3-7 ms/1000km
# - 1-hop F: adds ~2-5 ms over ground wave
# - Multi-hop: each additional hop adds ~2-3 ms
#
# Station                Distance (typical US)    Plausible delay range
# ------                 --------------------     ---------------------
# WWV (Fort Collins)     500-3000 km             3-25 ms
# CHU (Ottawa)           1000-4000 km            5-30 ms  
# WWVH (Hawaii)          4000-6000 km            15-50 ms

# Propagation delay bounds by station (ms)
# Format: (min_delay_ms, max_delay_ms)
PROPAGATION_BOUNDS_MS = {
    'WWV': (2.0, 35.0),    # Continental US to Fort Collins
    'WWVH': (12.0, 60.0),  # Continental US to Hawaii (longer path)
    'CHU': (3.0, 40.0),    # Continental US to Ottawa
}

# Default bounds for unknown stations
DEFAULT_PROPAGATION_BOUNDS_MS = (0.0, 100.0)
