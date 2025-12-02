#!/usr/bin/env python3
"""
Global Station Voter - Cross-Channel Coherent Processing

Leverages the GPS-disciplined RTP timestamps shared across all channels to
implement "Station Lock" - using strong detections on one frequency to guide
detection on weaker frequencies.

Key Insight:
------------
Because radiod's RTP timestamps are GPS-disciplined, all channels share a common
"ruler". A strong WWVH detection on 15 MHz tells us EXACTLY where to look for
WWVH on 2.5 MHz (within ionospheric dispersion ~3ms).

This enables:
1. **Anchor Discovery**: Find high-confidence detections on any frequency
2. **Guided Search**: Narrow the search window on weak channels from ±500ms to ±3ms
3. **Coherent Stacking**: Sum correlation arrays across frequencies for virtual SNR boost

Physics Caveat:
---------------
Group delay (dispersion) varies by frequency:
- 15 MHz vs 5 MHz: Typically < 2-3 ms differential
- WWV vs WWVH: ~15-20 ms separation (path length difference)

The dispersion uncertainty (3ms) << station separation (15ms), so a strong
detection of one station unambiguously identifies the search window on all bands.

Usage:
------
    voter = GlobalStationVoter(channels=['WWV_2.5_MHz', 'WWV_5_MHz', ...])
    
    # Each channel reports its minute's detection
    voter.report_detection('WWV_10_MHz', minute_rtp, result)
    voter.report_detection('WWV_15_MHz', minute_rtp, result)
    ...
    
    # Get guided search window for weak channel
    window = voter.get_search_window('WWV_2.5_MHz', minute_rtp, station='WWVH')
    # Returns: {'center_rtp': 1000000, 'window_samples': 48, 'source_channel': 'WWV_15_MHz'}
    
    # Or get stacked correlation for maximum sensitivity
    stacked = voter.get_stacked_correlation(minute_rtp, station='WWVH')
"""

import logging
import numpy as np
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import defaultdict
from enum import Enum

logger = logging.getLogger(__name__)

# Dispersion constants (empirical, can be refined)
MAX_DISPERSION_MS = 3.0  # Maximum frequency-dependent group delay difference
STATION_SEPARATION_MS = 15.0  # Minimum WWV-WWVH time separation
SAMPLES_PER_MS_16KHZ = 16  # 16 kHz sample rate

# SNR thresholds for anchor quality
ANCHOR_SNR_HIGH = 15.0  # dB - very confident anchor
ANCHOR_SNR_MEDIUM = 10.0  # dB - usable anchor
ANCHOR_SNR_LOW = 6.0  # dB - marginal anchor


class AnchorQuality(Enum):
    """Quality level of an anchor detection"""
    HIGH = "high"  # SNR > 15 dB, high confidence
    MEDIUM = "medium"  # SNR 10-15 dB, usable
    LOW = "low"  # SNR 6-10 dB, marginal
    NONE = "none"  # No valid anchor


@dataclass
class StationAnchor:
    """
    A high-confidence detection that can guide weaker channels.
    
    The RTP timestamp is the "ruler" position where we found the signal.
    """
    station: str  # 'WWV', 'WWVH', or 'CHU'
    channel: str  # Source channel (e.g., 'WWV_10_MHz')
    frequency_mhz: float  # Center frequency
    rtp_timestamp: int  # RTP timestamp of detection (GPS-locked)
    snr_db: float  # Detection SNR
    quality: AnchorQuality
    confidence: float  # 0-1 confidence score
    toa_offset_samples: int  # Offset from minute boundary in samples
    correlation_array: Optional[np.ndarray] = None  # Raw correlation for stacking
    
    def search_window_samples(self, target_freq_mhz: float) -> int:
        """
        Calculate search window size accounting for dispersion.
        
        Higher frequency difference = more dispersion uncertainty.
        """
        freq_diff_mhz = abs(self.frequency_mhz - target_freq_mhz)
        
        # Empirical model: dispersion scales roughly with frequency difference
        # At HF, typical dispersion is ~0.1 ms/MHz (varies with ionosphere)
        dispersion_ms = min(MAX_DISPERSION_MS, 0.1 * freq_diff_mhz + 1.0)
        
        # Convert to samples (± window)
        window_samples = int(dispersion_ms * SAMPLES_PER_MS_16KHZ)
        
        # Minimum window of 16 samples (1 ms) for timing jitter
        return max(16, window_samples)


@dataclass
class MinuteState:
    """
    State for a single minute across all channels.
    
    Tracks anchor detections and enables cross-channel coordination.
    """
    minute_rtp: int  # RTP timestamp at minute boundary
    utc_timestamp: float  # UTC time of minute start
    
    # Anchors by station
    wwv_anchor: Optional[StationAnchor] = None
    wwvh_anchor: Optional[StationAnchor] = None
    chu_anchor: Optional[StationAnchor] = None
    
    # Per-channel results
    channel_results: Dict[str, Any] = field(default_factory=dict)
    
    # Correlation arrays for stacking (channel -> array)
    wwv_correlations: Dict[str, np.ndarray] = field(default_factory=dict)
    wwvh_correlations: Dict[str, np.ndarray] = field(default_factory=dict)
    
    # Stacking results (computed on demand)
    stacked_wwv_correlation: Optional[np.ndarray] = None
    stacked_wwvh_correlation: Optional[np.ndarray] = None
    
    def get_anchor(self, station: str) -> Optional[StationAnchor]:
        """Get anchor for specified station"""
        if station == 'WWV':
            return self.wwv_anchor
        elif station == 'WWVH':
            return self.wwvh_anchor
        elif station == 'CHU':
            return self.chu_anchor
        return None
    
    def set_anchor(self, anchor: StationAnchor):
        """Set anchor if it's better than current"""
        current = self.get_anchor(anchor.station)
        
        # Replace if no current anchor or new one is better
        if current is None or anchor.snr_db > current.snr_db:
            if anchor.station == 'WWV':
                self.wwv_anchor = anchor
            elif anchor.station == 'WWVH':
                self.wwvh_anchor = anchor
            elif anchor.station == 'CHU':
                self.chu_anchor = anchor


class GlobalStationVoter:
    """
    Cross-channel coordination for coherent station detection.
    
    Uses GPS-disciplined RTP timestamps as a shared "ruler" to:
    1. Find strong detections (anchors) on any channel
    2. Guide detection on weak channels using anchor timing
    3. Stack correlations across channels for maximum sensitivity
    """
    
    def __init__(
        self,
        channels: List[str],
        sample_rate: int = 20000,
        history_minutes: int = 60
    ):
        """
        Initialize global voter.
        
        Args:
            channels: List of channel names to coordinate
            sample_rate: Sample rate for RTP calculations
            history_minutes: Number of minutes to keep in history
        """
        self.channels = set(channels)
        self.sample_rate = sample_rate
        self.history_minutes = history_minutes
        
        # Minute state keyed by minute_rtp (floored to minute boundary)
        self.minute_states: Dict[int, MinuteState] = {}
        
        # Channel -> frequency mapping (extracted from channel name)
        self.channel_frequencies: Dict[str, float] = {}
        for ch in channels:
            freq = self._extract_frequency(ch)
            if freq:
                self.channel_frequencies[ch] = freq
        
        # Statistics
        self.stats = {
            'anchors_found': 0,
            'guided_searches': 0,
            'stacked_detections': 0,
            'weak_channel_rescues': 0  # Detections that wouldn't exist without guidance
        }
        
        logger.info(f"GlobalStationVoter initialized with {len(channels)} channels")
        logger.info(f"Frequency map: {self.channel_frequencies}")
    
    def _extract_frequency(self, channel_name: str) -> Optional[float]:
        """Extract frequency in MHz from channel name"""
        # Pattern: "WWV 10 MHz" or "WWV_10_MHz" or "CHU 7.85 MHz"
        import re
        match = re.search(r'(\d+\.?\d*)\s*MHz', channel_name, re.IGNORECASE)
        if match:
            return float(match.group(1))
        return None
    
    def _minute_rtp_key(self, rtp_timestamp: int) -> int:
        """
        Convert RTP timestamp to minute boundary key.
        
        At 16 kHz, one minute = 960,000 samples.
        Floor to minute boundary.
        """
        samples_per_minute = self.sample_rate * 60
        return (rtp_timestamp // samples_per_minute) * samples_per_minute
    
    def _get_or_create_minute(self, minute_rtp: int, utc_timestamp: Optional[float] = None) -> MinuteState:
        """Get existing minute state or create new one"""
        if minute_rtp not in self.minute_states:
            utc = utc_timestamp or datetime.now(timezone.utc).timestamp()
            self.minute_states[minute_rtp] = MinuteState(
                minute_rtp=minute_rtp,
                utc_timestamp=utc
            )
            
            # Prune old minutes
            self._prune_history()
        
        return self.minute_states[minute_rtp]
    
    def _prune_history(self):
        """Remove old minute states beyond history limit"""
        if len(self.minute_states) > self.history_minutes:
            # Sort by minute_rtp and keep only recent ones
            sorted_keys = sorted(self.minute_states.keys())
            to_remove = sorted_keys[:-self.history_minutes]
            for key in to_remove:
                del self.minute_states[key]
    
    def report_detection(
        self,
        channel: str,
        rtp_timestamp: int,
        station: str,
        snr_db: float,
        toa_offset_samples: int,
        confidence: float,
        correlation_array: Optional[np.ndarray] = None,
        utc_timestamp: Optional[float] = None
    ):
        """
        Report a detection from a channel.
        
        If detection is strong enough, it becomes an anchor for other channels.
        
        Args:
            channel: Channel name (e.g., 'WWV_10_MHz')
            rtp_timestamp: RTP timestamp of detection
            station: Detected station ('WWV', 'WWVH', 'CHU')
            snr_db: Detection SNR in dB
            toa_offset_samples: Offset from minute boundary in samples
            confidence: Detection confidence (0-1)
            correlation_array: Raw correlation array for potential stacking
            utc_timestamp: UTC time of minute (optional)
        """
        minute_rtp = self._minute_rtp_key(rtp_timestamp)
        minute_state = self._get_or_create_minute(minute_rtp, utc_timestamp)
        
        # Determine anchor quality
        if snr_db >= ANCHOR_SNR_HIGH:
            quality = AnchorQuality.HIGH
        elif snr_db >= ANCHOR_SNR_MEDIUM:
            quality = AnchorQuality.MEDIUM
        elif snr_db >= ANCHOR_SNR_LOW:
            quality = AnchorQuality.LOW
        else:
            quality = AnchorQuality.NONE
        
        # Create anchor if quality is sufficient
        if quality != AnchorQuality.NONE:
            freq = self.channel_frequencies.get(channel, 0.0)
            anchor = StationAnchor(
                station=station,
                channel=channel,
                frequency_mhz=freq,
                rtp_timestamp=rtp_timestamp,
                snr_db=snr_db,
                quality=quality,
                confidence=confidence,
                toa_offset_samples=toa_offset_samples,
                correlation_array=correlation_array
            )
            
            minute_state.set_anchor(anchor)
            self.stats['anchors_found'] += 1
            
            logger.debug(
                f"Anchor set: {station} on {channel} @ {snr_db:.1f} dB "
                f"(quality={quality.value}, offset={toa_offset_samples} samples)"
            )
        
        # Store correlation for stacking
        if correlation_array is not None:
            if station == 'WWV':
                minute_state.wwv_correlations[channel] = correlation_array
            elif station == 'WWVH':
                minute_state.wwvh_correlations[channel] = correlation_array
    
    def get_search_window(
        self,
        channel: str,
        minute_rtp: int,
        station: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get guided search window for a weak channel.
        
        Returns the RTP position and window size to search, based on
        an anchor from a stronger channel.
        
        Args:
            channel: Target channel needing guidance
            minute_rtp: Minute RTP timestamp
            station: Station to search for ('WWV', 'WWVH', 'CHU')
            
        Returns:
            Dict with:
                - center_rtp: RTP timestamp to center search on
                - window_samples: ± samples to search
                - source_channel: Which channel provided the anchor
                - anchor_snr_db: SNR of the anchor detection
            Or None if no suitable anchor found.
        """
        minute_key = self._minute_rtp_key(minute_rtp)
        
        if minute_key not in self.minute_states:
            return None
        
        minute_state = self.minute_states[minute_key]
        anchor = minute_state.get_anchor(station)
        
        if anchor is None:
            return None
        
        # Don't use same channel as anchor
        if anchor.channel == channel:
            return None
        
        # Calculate search window accounting for dispersion
        target_freq = self.channel_frequencies.get(channel, 0.0)
        window_samples = anchor.search_window_samples(target_freq)
        
        self.stats['guided_searches'] += 1
        
        return {
            'center_rtp': anchor.rtp_timestamp,
            'center_offset_samples': anchor.toa_offset_samples,
            'window_samples': window_samples,
            'source_channel': anchor.channel,
            'source_freq_mhz': anchor.frequency_mhz,
            'anchor_snr_db': anchor.snr_db,
            'anchor_quality': anchor.quality.value
        }
    
    def get_stacked_correlation(
        self,
        minute_rtp: int,
        station: str,
        normalize: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Get coherently stacked correlation across all channels.
        
        Sums correlation arrays from all channels, exploiting the fact
        that signal adds linearly while noise adds as sqrt(N).
        
        Args:
            minute_rtp: Minute RTP timestamp
            station: Station to stack for ('WWV' or 'WWVH')
            normalize: Whether to normalize by number of channels
            
        Returns:
            Dict with:
                - stacked_correlation: Combined correlation array
                - channels_used: List of channels included
                - snr_improvement_db: Theoretical SNR improvement
            Or None if insufficient data.
        """
        minute_key = self._minute_rtp_key(minute_rtp)
        
        if minute_key not in self.minute_states:
            return None
        
        minute_state = self.minute_states[minute_key]
        
        # Get correlation arrays for this station
        if station == 'WWV':
            correlations = minute_state.wwv_correlations
        elif station == 'WWVH':
            correlations = minute_state.wwvh_correlations
        else:
            return None
        
        if len(correlations) < 2:
            # Need at least 2 channels to stack
            return None
        
        # Find common length (trim to shortest)
        min_len = min(len(arr) for arr in correlations.values())
        
        # Stack correlations
        stacked = np.zeros(min_len, dtype=np.float64)
        for channel, arr in correlations.items():
            # Normalize each channel's correlation to unit peak
            arr_trimmed = arr[:min_len]
            if normalize:
                peak = np.max(np.abs(arr_trimmed))
                if peak > 0:
                    arr_trimmed = arr_trimmed / peak
            stacked += arr_trimmed
        
        # Theoretical SNR improvement: sqrt(N) for incoherent stacking
        # (actual improvement depends on noise correlation between channels)
        n_channels = len(correlations)
        snr_improvement_db = 10 * np.log10(n_channels)  # Best case
        
        self.stats['stacked_detections'] += 1
        
        return {
            'stacked_correlation': stacked,
            'channels_used': list(correlations.keys()),
            'n_channels': n_channels,
            'snr_improvement_db': snr_improvement_db,
            'peak_index': int(np.argmax(stacked)),
            'peak_value': float(np.max(stacked))
        }
    
    def get_minute_summary(self, minute_rtp: int) -> Optional[Dict[str, Any]]:
        """
        Get summary of all detections for a minute.
        
        Returns:
            Dict with anchor info for each station and channel status.
        """
        minute_key = self._minute_rtp_key(minute_rtp)
        
        if minute_key not in self.minute_states:
            return None
        
        minute_state = self.minute_states[minute_key]
        
        def anchor_to_dict(anchor: Optional[StationAnchor]) -> Optional[Dict]:
            if anchor is None:
                return None
            return {
                'channel': anchor.channel,
                'frequency_mhz': anchor.frequency_mhz,
                'snr_db': anchor.snr_db,
                'quality': anchor.quality.value,
                'toa_offset_samples': anchor.toa_offset_samples
            }
        
        return {
            'minute_rtp': minute_rtp,
            'utc_timestamp': minute_state.utc_timestamp,
            'wwv_anchor': anchor_to_dict(minute_state.wwv_anchor),
            'wwvh_anchor': anchor_to_dict(minute_state.wwvh_anchor),
            'chu_anchor': anchor_to_dict(minute_state.chu_anchor),
            'wwv_channels_with_correlation': list(minute_state.wwv_correlations.keys()),
            'wwvh_channels_with_correlation': list(minute_state.wwvh_correlations.keys())
        }
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get voter statistics"""
        return {
            **self.stats,
            'minutes_tracked': len(self.minute_states),
            'channels': list(self.channels)
        }
    
    def get_best_time_snap_anchor(
        self,
        minute_rtp: int,
        prefer_wwv_chu: bool = True,
        min_snr_db: float = 8.0
    ) -> Optional[Dict[str, Any]]:
        """
        Get the best anchor across ALL channels for time_snap establishment.
        
        Implements dynamic RTP anchor selection using ensemble voting:
        - Selects the strongest SNR detection across all frequencies
        - Prefers WWV/CHU over WWVH (for timing reference)
        - Returns the anchor with lowest timing uncertainty
        
        Args:
            minute_rtp: Minute RTP timestamp
            prefer_wwv_chu: If True, prefer WWV/CHU over WWVH for timing
            min_snr_db: Minimum SNR required for consideration
            
        Returns:
            Dict with best anchor info for time_snap, or None if no good anchor
        """
        minute_key = self._minute_rtp_key(minute_rtp)
        
        if minute_key not in self.minute_states:
            return None
        
        minute_state = self.minute_states[minute_key]
        
        # Collect all valid anchors
        candidates = []
        
        # WWV anchor (preferred for timing)
        if minute_state.wwv_anchor and minute_state.wwv_anchor.snr_db >= min_snr_db:
            candidates.append({
                'anchor': minute_state.wwv_anchor,
                'station': 'WWV',
                'timing_preference': 1.0 if prefer_wwv_chu else 0.5
            })
        
        # CHU anchor (also preferred for timing)  
        if minute_state.chu_anchor and minute_state.chu_anchor.snr_db >= min_snr_db:
            candidates.append({
                'anchor': minute_state.chu_anchor,
                'station': 'CHU',
                'timing_preference': 1.0 if prefer_wwv_chu else 0.5
            })
        
        # WWVH anchor (lower timing preference - WWVH tones are at different offsets)
        if minute_state.wwvh_anchor and minute_state.wwvh_anchor.snr_db >= min_snr_db:
            candidates.append({
                'anchor': minute_state.wwvh_anchor,
                'station': 'WWVH',
                'timing_preference': 0.3 if prefer_wwv_chu else 0.5
            })
        
        if not candidates:
            return None
        
        # Score each candidate: SNR + timing preference bonus
        def score_candidate(c):
            anchor = c['anchor']
            snr_score = anchor.snr_db  # Higher SNR = better
            preference_bonus = c['timing_preference'] * 5.0  # Up to 5 dB equivalent
            
            # Quality bonus
            quality_bonus = {
                AnchorQuality.HIGH: 3.0,
                AnchorQuality.MEDIUM: 1.0,
                AnchorQuality.LOW: 0.0,
                AnchorQuality.NONE: -5.0
            }.get(anchor.quality, 0.0)
            
            return snr_score + preference_bonus + quality_bonus
        
        # Select best candidate
        best = max(candidates, key=score_candidate)
        anchor = best['anchor']
        
        logger.info(
            f"🏆 Best time_snap anchor: {anchor.station} @ {anchor.channel} "
            f"({anchor.snr_db:.1f} dB, quality={anchor.quality.value})"
        )
        
        return {
            'station': anchor.station,
            'channel': anchor.channel,
            'frequency_mhz': anchor.frequency_mhz,
            'rtp_timestamp': anchor.rtp_timestamp,
            'toa_offset_samples': anchor.toa_offset_samples,
            'snr_db': anchor.snr_db,
            'confidence': anchor.confidence,
            'quality': anchor.quality.value,
            'use_for_time_snap': anchor.station in ('WWV', 'CHU'),
            'all_candidates': len(candidates)
        }
    
    def report_detection_result(
        self,
        channel: str,
        detection_result: Any,  # ToneDetectionResult
        minute_rtp: int,
        correlation_array: Optional[np.ndarray] = None
    ):
        """
        Convenience method to report a ToneDetectionResult.
        
        Args:
            channel: Channel name
            detection_result: ToneDetectionResult object
            minute_rtp: Minute boundary RTP
            correlation_array: Optional correlation array for stacking
        """
        # Extract station name handling both string and enum
        station = detection_result.station
        if hasattr(station, 'value'):
            station = station.value
        
        self.report_detection(
            channel=channel,
            rtp_timestamp=minute_rtp,
            station=station,
            snr_db=detection_result.snr_db,
            toa_offset_samples=int(detection_result.timing_error_ms * self.sample_rate / 1000),
            confidence=detection_result.confidence,
            correlation_array=correlation_array,
            utc_timestamp=detection_result.timestamp_utc
        )


# Convenience function for testing
def create_test_voter():
    """Create a voter with standard WWV/WWVH channel configuration"""
    channels = [
        'WWV 2.5 MHz',
        'WWV 5 MHz',
        'WWV 10 MHz',
        'WWV 15 MHz',
        'WWV 20 MHz',
        'WWV 25 MHz',
        'CHU 3.33 MHz',
        'CHU 7.85 MHz',
        'CHU 14.67 MHz'
    ]
    return GlobalStationVoter(channels=channels)
