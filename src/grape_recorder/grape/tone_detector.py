#!/usr/bin/env python3
"""
Multi-Station Tone Detector - Standalone Implementation

Detects WWV/WWVH/CHU time signal tones using phase-invariant quadrature
matched filtering. Standalone implementation for reusability.

Stations:
- WWV (Fort Collins): 1000 Hz, 0.8s → Primary time_snap reference
- WWVH (Hawaii): 1200 Hz, 0.8s → Propagation analysis ONLY
- CHU (Canada): 1000 Hz, 0.5s → Alternate time_snap reference

Design:
- Phase-invariant: Works with arbitrary phase shifts
- Noise-adaptive: Threshold adjusts to local noise floor
- Station-aware: Sets use_for_time_snap correctly for each station
"""

import logging
import re
import numpy as np
from typing import Optional, List, Dict, Tuple
from scipy import signal as scipy_signal
from scipy.signal import correlate
from scipy.fft import rfft, rfftfreq

from ..interfaces.tone_detection import ToneDetector, MultiStationToneDetector as IMultiStationToneDetector
from ..interfaces.data_models import ToneDetectionResult, StationType
from .wwv_constants import (
    WWV_ONLY_TONE_MINUTES,
    WWVH_ONLY_TONE_MINUTES,
    PROPAGATION_BOUNDS_MS,
    DEFAULT_PROPAGATION_BOUNDS_MS
)

logger = logging.getLogger(__name__)


class MultiStationToneDetector(IMultiStationToneDetector):
    """
    Detect time signal tones from multiple stations using matched filtering
    
    Stations:
    - WWV (Fort Collins): 1000 Hz, 0.8s duration - PRIMARY for time_snap
    - WWVH (Hawaii): 1200 Hz, 0.8s duration - Propagation analysis ONLY
    - CHU (Canada): 1000 Hz, 0.5s duration - Alternate time_snap
    
    Uses phase-invariant quadrature matched filtering for robust detection
    in poor SNR conditions and with phase-shifted signals.
    """
    
    def __init__(self, channel_name: str, sample_rate: int = 3000):
        """
        Initialize multi-station tone detector
        
        Args:
            channel_name: Channel name to determine which stations to detect
            sample_rate: Processing sample rate (Hz), default 3000 Hz
        """
        self.channel_name = channel_name
        self.sample_rate = sample_rate
        self.is_chu_channel = 'CHU' in channel_name.upper()
        
        # Determine channel frequency from name
        self.channel_frequency_mhz = self._extract_frequency_mhz(channel_name)
        
        # Detection threshold (configurable)
        self.detection_threshold = 0.5
        
        # Create matched filter templates (quadrature for phase-invariance)
        self.templates: Dict[StationType, dict] = {}
        
        if self.is_chu_channel:
            # CHU frequencies: 3.33, 7.85, 14.67 MHz
            # Only detect CHU 1000 Hz (0.5s)
            self.templates[StationType.CHU] = self._create_template(1000, 0.5)
        else:
            # WWV frequencies: 2.5, 5, 10, 15, 20, 25 MHz
            # Always detect WWV 1000 Hz tone
            self.templates[StationType.WWV] = self._create_template(1000, 0.8)
            
            # WWVH only broadcasts on 2.5, 5, 10, 15 MHz (NOT on 20 or 25 MHz)
            wwvh_frequencies = [2.5, 5.0, 10.0, 15.0]
            if self.channel_frequency_mhz in wwvh_frequencies:
                self.templates[StationType.WWVH] = self._create_template(1200, 0.8)
                logger.info(f"{channel_name}: WWVH detection enabled (shared frequency)")
            else:
                logger.info(f"{channel_name}: WWVH detection disabled (WWV-only frequency)")
        
        # State tracking
        self.last_detections_by_minute: Dict[int, List[ToneDetectionResult]] = {}
        self.detection_count = 0
        self.last_detection_time: Optional[float] = None
        
        # Statistics tracking
        self.detection_stats: Dict[StationType, int] = {
            StationType.WWV: 0,
            StationType.WWVH: 0,
            StationType.CHU: 0
        }
        self.total_attempts = 0
        self.timing_errors: List[float] = []
        
        # Differential delay tracking (WWV - WWVH)
        self.differential_delay_history: List[Dict[str, float]] = []
        
        # Station priorities (for time_snap selection when multiple detected)
        self.station_priorities: Dict[StationType, int] = {
            StationType.WWV: 100,   # Highest priority
            StationType.CHU: 50,    # Medium priority
            StationType.WWVH: 0     # Never used for time_snap
        }
        
        logger.info(f"{channel_name}: MultiStationToneDetector initialized - "
                   f"stations={list(self.templates.keys())}, sample_rate={sample_rate}Hz")
    
    def _extract_frequency_mhz(self, channel_name: str) -> Optional[float]:
        """
        Extract frequency in MHz from channel name
        
        Args:
            channel_name: Channel name like "WWV 2.5 MHz", "WWV_10_MHz", "WWV 10 MHz"
            
        Returns:
            Frequency in MHz, or None if not found
        """
        # Match patterns like "WWV 2.5 MHz", "WWV_10_MHz", "WWV 10 MHz", etc.
        # Allow underscore or space before MHz
        match = re.search(r'(\d+(?:\.\d+)?)[_\s]*MHz', channel_name, re.IGNORECASE)
        if match:
            return float(match.group(1))
        return None
    
    def _create_template(self, frequency_hz: float, duration_sec: float) -> dict:
        """
        Create quadrature matched filter templates (sin and cos)
        
        Args:
            frequency_hz: Tone frequency (1000 or 1200 Hz)
            duration_sec: Tone duration (0.5 or 0.8 seconds)
            
        Returns:
            dict with 'sin', 'cos', 'frequency', 'duration'
        """
        t = np.arange(0, duration_sec, 1/self.sample_rate)
        
        # Apply Tukey window for smooth edges
        window = scipy_signal.windows.tukey(len(t), alpha=0.1)
        
        # Create quadrature pair
        template_sin = np.sin(2 * np.pi * frequency_hz * t) * window
        template_cos = np.cos(2 * np.pi * frequency_hz * t) * window
        
        # Normalize to unit energy for proper matched filtering
        template_sin /= np.linalg.norm(template_sin)
        template_cos /= np.linalg.norm(template_cos)
        
        return {
            'sin': template_sin,
            'cos': template_cos,
            'frequency': frequency_hz,
            'duration': duration_sec
        }
    
    def process_samples(
        self,
        timestamp: float,
        samples: np.ndarray,
        rtp_timestamp: Optional[int] = None,
        original_sample_rate: Optional[int] = None,
        buffer_rtp_start: Optional[int] = None,
        search_window_ms: Optional[float] = None,
        expected_offset_ms: Optional[float] = None
    ) -> Optional[List[ToneDetectionResult]]:
        """
        Process samples and detect tones (ToneDetector interface).
        
        Args:
            timestamp: UTC timestamp of samples (from time_snap if available)
            samples: Complex IQ samples at self.sample_rate
            rtp_timestamp: Optional RTP timestamp for provenance
            original_sample_rate: Original sample rate before decimation (e.g., 20000)
            buffer_rtp_start: RTP timestamp at start of original buffer
            search_window_ms: Search window in milliseconds (default 500ms)
                Pass 0: Use default ±500ms for initial wide search
                Pass 1+: Use guided narrow window (e.g., ±30ms) from anchor
            expected_offset_ms: Expected offset from minute boundary (default 0)
                Pass 0: Use 0 (search around minute boundary)
                Pass 1+: Use expected propagation delay (e.g., +20ms for CHU)
                This centers the search window at minute_boundary + expected_offset
            
        Returns:
            List of ToneDetectionResult objects (may contain WWV + WWVH),
            or None if no tones detected
        """
        self.total_attempts += 1
        detections = self._detect_tones_internal(
            samples, timestamp, original_sample_rate, buffer_rtp_start, 
            search_window_ms, expected_offset_ms
        )
        
        if detections:
            self.last_detection_time = timestamp
            
            # Update statistics
            for det in detections:
                self.detection_stats[det.station] += 1
                if det.use_for_time_snap:
                    self.timing_errors.append(det.timing_error_ms)
                    
                    # Keep last 1000 timing errors for statistics
                    if len(self.timing_errors) > 1000:
                        self.timing_errors = self.timing_errors[-1000:]
            
            # Calculate differential delay if both WWV and WWVH detected
            self._update_differential_delay(detections, timestamp)
            
            return detections
        
        return None
    
    def _detect_tones_internal(
        self,
        iq_samples: np.ndarray,
        current_unix_time: float,
        original_sample_rate: Optional[int] = None,
        buffer_rtp_start: Optional[int] = None,
        search_window_ms: Optional[float] = None,
        expected_offset_ms: Optional[float] = None
    ) -> List[ToneDetectionResult]:
        """
        Internal tone detection implementation
        
        Args:
            iq_samples: Complex IQ samples at self.sample_rate
            current_unix_time: UTC time for first sample
            
        Returns:
            List of ToneDetectionResult objects, sorted by SNR (strongest first)
        """
        # Get minute boundary for the EXPECTED tone (around :00.0)
        # Calculate buffer start time (current_unix_time is buffer MIDPOINT)
        buffer_duration_sec = len(iq_samples) / self.sample_rate
        buffer_start_time = current_unix_time - (buffer_duration_sec / 2)
        
        # Use floor to find the minute boundary that the buffer START falls in
        # IMPORTANT: Add small epsilon to handle floating point precision issues
        # Without this, 1764932339.9999999 would floor to 1764932280 instead of 1764932340
        minute_boundary = int((buffer_start_time + 0.5) / 60) * 60
        
        # Check if we already detected this minute (prevent duplicates)
        if minute_boundary in self.last_detections_by_minute:
            return []
        
        # Step 1: AM demodulation (extract envelope)
        magnitude = np.abs(iq_samples)
        audio_signal = magnitude - np.mean(magnitude)  # AC coupling
        
        # Diagnostic: Check signal energy
        audio_rms = np.sqrt(np.mean(audio_signal**2))
        logger.debug(f"AM demod: iq_len={len(iq_samples)}, audio_rms={audio_rms:.6f}, "
                    f"mag_mean={np.mean(magnitude):.6f}")
        
        detections: List[ToneDetectionResult] = []
        
        # Step 2: Correlate with each station template
        for station_type, template in self.templates.items():
            detection = self._correlate_with_template(
                audio_signal,
                station_type,
                template,
                current_unix_time,
                minute_boundary,
                original_sample_rate,
                buffer_rtp_start,
                search_window_ms,
                expected_offset_ms
            )
            
            if detection:
                detections.append(detection)
        
        # Sort by SNR (strongest signal first)
        detections.sort(key=lambda d: d.snr_db, reverse=True)
        
        # Cache detections for this minute
        if detections:
            self.last_detections_by_minute[minute_boundary] = detections
            self.detection_count += len(detections)
            
            # Cleanup old minutes (keep last 10)
            if len(self.last_detections_by_minute) > 10:
                oldest_minute = min(self.last_detections_by_minute.keys())
                del self.last_detections_by_minute[oldest_minute]
        
        return detections
    
    def _correlate_with_template(
        self,
        audio_signal: np.ndarray,
        station_type: StationType,
        template: dict,
        current_unix_time: float,
        minute_boundary: int,
        original_sample_rate: Optional[int] = None,
        buffer_rtp_start: Optional[int] = None,
        search_window_ms: Optional[float] = None,
        expected_offset_ms: Optional[float] = None
    ) -> Optional[ToneDetectionResult]:
        """
        Correlate audio signal with station template
        
        Args:
            search_window_ms: Search window in milliseconds
                - None or 500: Wide search for Pass 0 (default)
                - 30-50: Medium for Pass 1 with geographic constraint
                - 3-10: Tight for guided search from anchor
            expected_offset_ms: Expected offset from minute boundary
                - None or 0: Search centered at minute boundary (Pass 0)
                - +20: Search centered at minute_boundary + 20ms (e.g., CHU propagation)
                - This allows narrow windows to find signals at expected arrival times
        
        Returns:
            ToneDetectionResult if detection successful, None otherwise
        """
        template_sin = template['sin']
        template_cos = template['cos']
        frequency = template['frequency']
        duration = template['duration']
        
        # Perform quadrature correlation (phase-invariant)
        try:
            corr_sin = correlate(audio_signal, template_sin, mode='valid')
            corr_cos = correlate(audio_signal, template_cos, mode='valid')
        except ValueError as e:
            freq_str = f"{frequency}Hz" if frequency is not None else "??Hz"
            logger.warning(f"{station_type.value} @ {freq_str}: Correlation failed: {e}")
            return None
        
        if len(corr_sin) == 0 or len(corr_cos) == 0:
            freq_str = f"{frequency}Hz" if frequency is not None else "??Hz"
            logger.warning(f"{station_type.value} @ {freq_str}: Empty correlation result")
            return None
        
        # Combine to get phase-invariant magnitude: sqrt(sin^2 + cos^2)
        min_len = min(len(corr_sin), len(corr_cos))
        correlation = np.sqrt(corr_sin[:min_len]**2 + corr_cos[:min_len]**2)
        
        # Expected position: all stations use minute boundary (second 0)
        # - WWV: 1000 Hz, 0.8s tone at :00.0
        # - WWVH: 1200 Hz, 0.8s tone at :00.0  
        # - CHU: 1000 Hz, 0.5s tone at :00.0 (1.0s at top of hour)
        #   Note: CHU second 29 is always silent, seconds 31-39 and 50-59 have
        #   only 10ms ticks (FSK data and voice). But second 00 has full tone.
        buffer_len_sec = len(audio_signal) / self.sample_rate
        buffer_start_time = current_unix_time - (buffer_len_sec / 2)
        
        # All stations reference the minute boundary
        reference_time = minute_boundary
        
        # Tone position in buffer (samples from start)
        # For Pass 0: search around minute boundary (expected_offset = 0)
        # For Pass 1+: search around expected arrival (minute_boundary + expected_offset)
        offset_ms = expected_offset_ms if expected_offset_ms is not None else 0.0
        offset_sec = offset_ms / 1000.0
        
        tone_offset_from_start = (reference_time + offset_sec) - buffer_start_time
        expected_pos_samples = int(tone_offset_from_start * self.sample_rate)
        
        # Search window: configurable, default ±500ms
        # Pass 0 (wide): 500ms - initial detection, centered at minute boundary
        # Pass 1 (geographic): 30-50ms - centered at expected propagation delay
        # Guided (anchor): 3-10ms - centered at anchor's detected position
        window_ms = search_window_ms if search_window_ms is not None else 500.0
        search_window = int(window_ms * self.sample_rate / 1000)
        search_start = max(0, expected_pos_samples - search_window)
        search_end = min(len(correlation), expected_pos_samples + search_window)
        
        freq_str = f"{frequency}Hz" if frequency is not None else "??Hz"
        logger.debug(f"{station_type.value} @ {freq_str}: ref=min@{reference_time}, "
                    f"expected_offset={offset_ms:+.1f}ms, "
                    f"expected_pos={expected_pos_samples}, window=±{window_ms:.0f}ms, search=[{search_start}:{search_end}]")
        
        if search_start >= search_end:
            logger.warning(f"{station_type.value} @ {freq_str}: Invalid search window! "
                          f"expected_pos={expected_pos_samples}, tone_offset={tone_offset_from_start:.2f}s")
            return None
        
        # Find peak within search window
        search_region = correlation[search_start:search_end]
        local_peak_idx = np.argmax(search_region)
        peak_idx = search_start + local_peak_idx
        peak_val = correlation[peak_idx]
        
        # Parabolic (quadratic) interpolation for sub-sample precision
        # Uses the peak and its two neighbors to fit a parabola
        sub_sample_offset = 0.0
        if 0 < peak_idx < len(correlation) - 1:
            y_m1 = correlation[peak_idx - 1]
            y_0 = correlation[peak_idx]
            y_p1 = correlation[peak_idx + 1]
            
            denominator = y_m1 - 2*y_0 + y_p1
            if abs(denominator) > 1e-10:
                sub_sample_offset = 0.5 * (y_m1 - y_p1) / denominator
                sub_sample_offset = max(-0.5, min(0.5, sub_sample_offset))
                peak_val = y_0 - 0.25 * (y_m1 - y_p1) * sub_sample_offset
        
        precise_peak_idx = peak_idx + sub_sample_offset
        
        # Noise-adaptive threshold: Use noise from OUTSIDE the search window
        noise_samples = np.concatenate([
            correlation[:max(0, search_start - 100)],
            correlation[min(len(correlation), search_end + 100):]
        ])
        
        if len(noise_samples) > 100:
            # IMPROVED: Percentile-based noise floor (more robust than mean)
            # Validated 2025-11-17: +6-11% detection improvement across all frequencies
            # See scripts/compare_tone_detectors.py for multi-frequency validation
            noise_floor_base = np.percentile(noise_samples, 10)  # 10th percentile
            noise_std = np.std(noise_samples[noise_samples < np.median(noise_samples)])
            noise_floor = noise_floor_base + 3.0 * noise_std  # 3-sigma (was 2.0)
            noise_mean = np.mean(noise_samples)  # Still compute for SNR calculation
        else:
            # Fallback for short buffers (use old method)
            noise_mean = np.mean(correlation)
            noise_std = np.std(correlation)
            noise_floor = noise_mean + 2.0 * noise_std
        
        # Calculate timing relative to minute boundary (all stations)
        # CRITICAL: Use precise sub-sample position for timing
        onset_sample_idx = precise_peak_idx  # Now includes sub-sample precision
        onset_time = buffer_start_time + (onset_sample_idx / self.sample_rate)
        timing_error_sec = onset_time - reference_time
        
        # Handle wraparound
        if timing_error_sec > 30:
            timing_error_sec -= 60
        elif timing_error_sec < -30:
            timing_error_sec += 60
        
        timing_error_ms = timing_error_sec * 1000
        
        # Calculate SNR
        if noise_mean > 0 and peak_val > noise_mean:
            snr_db = 20 * np.log10(peak_val / noise_mean)
        else:
            snr_db = 0.0
        
        # Calculate actual tone power using FFT on the detected tone segment
        # Extract the tone segment (0.8s for WWV/WWVH, 0.5s for CHU)
        # Use integer index for slicing (onset_sample_idx may be float from sub-sample interpolation)
        tone_start_idx = max(0, int(onset_sample_idx))
        tone_end_idx = min(len(audio_signal), tone_start_idx + int(duration * self.sample_rate))
        tone_segment = audio_signal[tone_start_idx:tone_end_idx]
        
        tone_power_db = None
        if len(tone_segment) > int(0.1 * self.sample_rate):  # Need at least 100ms
            # Use FFT to measure power at the specific frequency
            windowed = tone_segment * scipy_signal.windows.hann(len(tone_segment))
            fft_result = rfft(windowed)
            freqs = rfftfreq(len(windowed), 1/self.sample_rate)
            
            # Find bin closest to target frequency
            freq_idx = np.argmin(np.abs(freqs - frequency))
            power_at_freq = np.abs(fft_result[freq_idx])**2
            
            # Measure noise floor in nearby bins (excluding the tone)
            noise_low = max(0, freq_idx - int(50.0 * len(windowed) / self.sample_rate))
            noise_high = min(len(fft_result), freq_idx + int(50.0 * len(windowed) / self.sample_rate))
            exclude_low = max(0, freq_idx - int(10.0 * len(windowed) / self.sample_rate))
            exclude_high = min(len(fft_result), freq_idx + int(10.0 * len(windowed) / self.sample_rate))
            
            noise_bins = np.concatenate([
                np.arange(noise_low, exclude_low),
                np.arange(exclude_high, noise_high)
            ])
            
            if len(noise_bins) > 10:
                noise_power = np.mean(np.abs(fft_result[noise_bins])**2)
            else:
                noise_power = np.mean(np.abs(fft_result)**2)
            
            # Calculate power relative to noise floor
            if noise_power > 0:
                tone_power_db = 10 * np.log10(power_at_freq / noise_power)
            else:
                tone_power_db = snr_db  # Fallback to SNR estimate
        
        # Diagnostic logging BEFORE threshold check
        freq_str = f"{frequency}Hz" if frequency is not None else "??Hz"
        peak_str = f"{peak_val:.2f}" if peak_val is not None else "None"
        noise_str = f"{noise_floor:.2f}" if noise_floor is not None else "None"
        snr_str = f"{snr_db:.1f}dB" if snr_db is not None else "None"
        power_str = f"{tone_power_db:.1f}dB" if tone_power_db is not None else "None"
        timing_str = f"{timing_error_ms:+.1f}ms" if timing_error_ms is not None else "None"
        logger.debug(f"{station_type.value} @ {freq_str}: peak={peak_str}, "
                    f"noise_floor={noise_str}, SNR={snr_str}, "
                    f"tone_power={power_str}, timing_err={timing_str}")
        
        # Check if we have valid values
        if peak_val is None or noise_floor is None:
            logger.warning(f"  -> REJECTED (invalid peak or noise values)")
            return None
        
        # Check if peak is significant
        if peak_val <= noise_floor:
            logger.debug(f"  -> REJECTED (peak <= threshold)")
            return None
        
        # Calculate confidence (normalized correlation)
        confidence = min(1.0, peak_val / (noise_floor * 2.0))
        
        # PROPAGATION PLAUSIBILITY CHECK
        # Reject detections outside reasonable ionospheric path delays
        # This filters out interference peaks that happen to be stronger than the actual tone
        station_name = station_type.value  # 'WWV', 'WWVH', 'CHU'
        min_delay_ms, max_delay_ms = PROPAGATION_BOUNDS_MS.get(
            station_name, DEFAULT_PROPAGATION_BOUNDS_MS
        )
        
        if timing_error_ms < min_delay_ms or timing_error_ms > max_delay_ms:
            logger.debug(f"  -> REJECTED (timing {timing_error_ms:+.1f}ms outside "
                        f"plausible range [{min_delay_ms:.0f}, {max_delay_ms:.0f}]ms for {station_name})")
            return None
        
        # Determine if this station should be used for time_snap
        # 
        # TIMING PHILOSOPHY (Updated):
        # - WWV and CHU: Primary references (direct UTC(NIST) source)
        # - WWVH: Eligible AFTER back-calculation subtracts propagation delay
        #
        # At this detection level, we mark WWVH as "eligible" but with lower
        # initial preference. The TransmissionTimeSolver does the back-calculation
        # to make WWVH's timing as accurate as WWV.
        #
        # Priority order for TimeSnapReference creation:
        #   1. WWV (direct, ~5-6ms propagation from Fort Collins)
        #   2. CHU (direct, ~4ms propagation from Ottawa)  
        #   3. WWVH (requires back-calculation, ~21ms from Hawaii)
        #
        # All three become valid once propagation delay is subtracted.
        use_for_time_snap = station_type in [StationType.WWV, StationType.CHU, StationType.WWVH]
        
        # Calculate sample position in ORIGINAL sample rate (for precise RTP calculation)
        # onset_sample_idx is at self.sample_rate (detection rate)
        # Scale to original_sample_rate if different (e.g., 20 kHz archive rate)
        sample_position_original = None
        if original_sample_rate is not None:
            scale_factor = original_sample_rate / self.sample_rate
            sample_position_original = round(onset_sample_idx * scale_factor)
            logger.debug(f"Sample position: decimated={onset_sample_idx}, "
                        f"original={sample_position_original} (scale={scale_factor:.2f})")
        
        # Create ToneDetectionResult
        result = ToneDetectionResult(
            station=station_type,
            frequency_hz=frequency,
            duration_sec=duration,
            timestamp_utc=onset_time,
            timing_error_ms=timing_error_ms,
            snr_db=snr_db,
            confidence=confidence,
            use_for_time_snap=use_for_time_snap,
            correlation_peak=float(peak_val),
            noise_floor=float(noise_floor),
            tone_power_db=tone_power_db,
            sample_position_original=sample_position_original,
            original_sample_rate=original_sample_rate,
            buffer_rtp_start=buffer_rtp_start
        )
        
        freq_str = f"{frequency}Hz" if frequency is not None else "??Hz"
        logger.info(f"{self.channel_name}: ✅ {station_type.value} DETECTED! "
                   f"Freq: {freq_str}, Duration: {duration:.1f}s, "
                   f"Timing error: {timing_error_ms:+.1f}ms, SNR: {snr_db:.1f}dB, "
                   f"use_for_time_snap={use_for_time_snap}")
        
        return result
    
    def _update_differential_delay(
        self,
        detections: List[ToneDetectionResult],
        timestamp: float
    ) -> None:
        """
        Update differential delay history if both WWV and WWVH detected
        """
        wwv_det = None
        wwvh_det = None
        
        for det in detections:
            if det.station == StationType.WWV:
                wwv_det = det
            elif det.station == StationType.WWVH:
                wwvh_det = det
        
        if wwv_det and wwvh_det:
            differential_ms = wwv_det.timing_error_ms - wwvh_det.timing_error_ms
            
            self.differential_delay_history.append({
                'timestamp': timestamp,
                'differential_ms': differential_ms,
                'wwv_snr_db': wwv_det.snr_db,
                'wwvh_snr_db': wwvh_det.snr_db
            })
            
            # Keep last 1000 measurements
            if len(self.differential_delay_history) > 1000:
                self.differential_delay_history = self.differential_delay_history[-1000:]
            
            logger.info(f"Differential delay (WWV-WWVH): {differential_ms:+.1f}ms "
                       f"(WWV SNR={wwv_det.snr_db:.1f}dB, WWVH SNR={wwvh_det.snr_db:.1f}dB)")
    
    # ===== ToneDetector Interface Methods =====
    
    def get_differential_delay(self) -> Optional[float]:
        """Get most recent WWV-WWVH differential propagation delay (ms)"""
        if self.differential_delay_history:
            return self.differential_delay_history[-1]['differential_ms']
        return None
    
    def get_detection_statistics(self) -> Dict[str, int]:
        """Get detection counts by station"""
        total_detections = sum(self.detection_stats.values())
        detection_rate = (total_detections / self.total_attempts * 100) if self.total_attempts > 0 else 0.0
        
        return {
            'wwv_detections': self.detection_stats[StationType.WWV],
            'wwvh_detections': self.detection_stats[StationType.WWVH],
            'chu_detections': self.detection_stats[StationType.CHU],
            'total_attempts': self.total_attempts,
            'detection_rate_pct': detection_rate
        }
    
    def get_station_active_list(self) -> List[StationType]:
        """Get list of stations that have been detected"""
        return [station for station, count in self.detection_stats.items() if count > 0]
    
    def set_detection_threshold(self, threshold: float) -> None:
        """Set detection confidence threshold (0.0-1.0)"""
        if not 0.0 <= threshold <= 1.0:
            raise ValueError(f"Threshold must be 0.0-1.0, got {threshold}")
        self.detection_threshold = threshold
        logger.info(f"Detection threshold set to {threshold:.2f}")
    
    def get_last_detection_time(self) -> Optional[float]:
        """Get UTC timestamp of most recent detection"""
        return self.last_detection_time
    
    def get_timing_accuracy_stats(self) -> Dict[str, float]:
        """Get timing accuracy statistics for time_snap-eligible stations"""
        if not self.timing_errors:
            return {
                'mean_error_ms': 0.0,
                'std_error_ms': 0.0,
                'max_error_ms': 0.0,
                'min_error_ms': 0.0,
                'sample_count': 0
            }
        
        errors = np.array(self.timing_errors)
        return {
            'mean_error_ms': float(np.mean(errors)),
            'std_error_ms': float(np.std(errors)),
            'max_error_ms': float(np.max(errors)),
            'min_error_ms': float(np.min(errors)),
            'sample_count': len(errors)
        }
    
    def reset_statistics(self) -> None:
        """Reset detection statistics"""
        self.detection_stats = {
            StationType.WWV: 0,
            StationType.WWVH: 0,
            StationType.CHU: 0
        }
        self.total_attempts = 0
        self.timing_errors = []
        logger.info("Detection statistics reset")
    
    # ===== MultiStationToneDetector Interface Methods =====
    
    def get_detections_by_station(
        self,
        station: StationType
    ) -> List[ToneDetectionResult]:
        """Get recent detections for specific station"""
        results = []
        for detections in self.last_detections_by_minute.values():
            for det in detections:
                if det.station == station:
                    results.append(det)
        return results
    
    def get_differential_delay_history(
        self,
        count: int = 10
    ) -> List[Dict[str, float]]:
        """Get recent WWV-WWVH differential delay measurements"""
        return self.differential_delay_history[-count:]
    
    def configure_station_priorities(
        self,
        priorities: Dict[StationType, int]
    ) -> None:
        """Configure station priorities for time_snap selection"""
        self.station_priorities.update(priorities)
        logger.info(f"Station priorities updated: {self.station_priorities}")
    
    # ===== Extended Tone Analysis (440/500/600 Hz) =====
    
    def analyze_extended_tones(
        self,
        iq_samples: np.ndarray,
        buffer_start_time: float
    ) -> Dict[str, any]:
        """
        Analyze extended WWV/WWVH tones for STATION DISCRIMINATION.
        
        KEY INSIGHT: 500 Hz and 600 Hz are STATION IDENTIFIERS:
        - WWV broadcasts 500 Hz during seconds 1-44 (except voice/silent)
        - WWVH broadcasts 600 Hz during seconds 1-44 (except voice/silent)
        
        This provides DIRECT station identification without timing analysis!
        If 500 Hz > 600 Hz → WWV dominant
        If 600 Hz > 500 Hz → WWVH dominant
        
        Conditions for valid discrimination:
        - Buffer must contain mid-minute data (seconds 1-44)
        - Avoid seconds 0, 29-30 (minute markers), 45-59 (voice/announcements)
        - Both tones should be checked - ratio determines station
        
        Also analyzes:
        - 440 Hz: Test tone (seconds 1-2 on some minutes)
        - 1000 Hz: Reference for comparison
        
        Args:
            iq_samples: Complex IQ samples
            buffer_start_time: UTC timestamp of buffer start
            
        Returns:
            Dict with discrimination results and tone analysis
        """
        if self.is_chu_channel:
            return {'status': 'CHU channel - WWV tones not applicable'}
        
        # Check if buffer is in valid discrimination window
        # 500/600 Hz discrimination only valid when ONE station broadcasts alone
        # (otherwise BCD 100 Hz intermod creates 500/600 Hz products)
        buffer_second = int(buffer_start_time) % 60
        buffer_minute = int(buffer_start_time / 60) % 60
        
        # Use shared constants for station-exclusive broadcast minutes
        # WWV-only: 1, 16, 17, 19 (WWVH silent - 500 Hz is pure WWV)
        # WWVH-only: 2, 43-51 (WWV silent - 600 Hz is pure WWVH)
        
        # Valid for discrimination only during single-station minutes
        is_wwv_only_minute = buffer_minute in WWV_ONLY_TONE_MINUTES
        is_wwvh_only_minute = buffer_minute in WWVH_ONLY_TONE_MINUTES
        valid_for_discrimination = (is_wwv_only_minute or is_wwvh_only_minute) and (1 <= buffer_second <= 44)
        
        results = {
            'buffer_time': buffer_start_time,
            'buffer_second': buffer_second,
            'buffer_minute': buffer_minute,
            'valid_for_discrimination': valid_for_discrimination,
            'is_wwv_only_minute': is_wwv_only_minute,
            'is_wwvh_only_minute': is_wwvh_only_minute,
            'expected_station': 'WWV' if is_wwv_only_minute else ('WWVH' if is_wwvh_only_minute else 'BOTH'),
            'tones': {},
            'dominant_tone': None,
            'frequency_spread_db': 0.0,
            # Station discrimination results
            'wwv_indicator_snr': None,      # 500 Hz SNR
            'wwvh_indicator_snr': None,     # 600 Hz SNR  
            'discrimination_ratio_db': None, # 500 Hz - 600 Hz (positive = WWV)
            'indicated_station': None,       # 'WWV', 'WWVH', or 'AMBIGUOUS'
            'discrimination_confidence': 0.0
        }
        
        # Convert to audio (envelope detection)
        audio_signal = np.abs(iq_samples)
        audio_signal = audio_signal - np.mean(audio_signal)  # Remove DC
        
        # Extended tone frequencies to analyze
        extended_tones = {
            '440Hz': 440,
            '500Hz': 500,
            '600Hz': 600,
            '1000Hz': 1000,  # Include for comparison
        }
        
        tone_powers = {}
        
        for tone_name, freq_hz in extended_tones.items():
            # Create matched filter template (short duration for mid-second tones)
            duration = 0.5  # 500ms analysis window
            t = np.arange(0, duration, 1/self.sample_rate)
            template_sin = np.sin(2 * np.pi * freq_hz * t)
            template_cos = np.cos(2 * np.pi * freq_hz * t)
            
            # Correlate with audio
            # Use only the middle portion of the buffer to avoid edge effects
            mid_start = len(audio_signal) // 4
            mid_end = 3 * len(audio_signal) // 4
            audio_segment = audio_signal[mid_start:mid_end]
            
            if len(audio_segment) < len(template_sin):
                continue
            
            corr_sin = correlate(audio_segment, template_sin, mode='valid')
            corr_cos = correlate(audio_segment, template_cos, mode='valid')
            
            # Phase-invariant magnitude
            magnitude = np.sqrt(corr_sin**2 + corr_cos**2)
            peak_power = np.max(magnitude)
            
            # Estimate noise floor
            noise_floor = np.median(magnitude)
            
            # SNR estimate
            if noise_floor > 0:
                snr_db = 10 * np.log10(peak_power / noise_floor)
            else:
                snr_db = 0.0
            
            tone_powers[tone_name] = peak_power
            results['tones'][tone_name] = {
                'frequency_hz': freq_hz,
                'peak_power': float(peak_power),
                'snr_db': float(snr_db),
                'detected': snr_db > 6.0  # 6 dB threshold
            }
        
        # Find dominant tone
        if tone_powers:
            dominant = max(tone_powers, key=tone_powers.get)
            results['dominant_tone'] = dominant
            
            # Calculate frequency spread (max - min power ratio)
            max_power = max(tone_powers.values())
            min_power = min(tone_powers.values()) if min(tone_powers.values()) > 0 else 1e-10
            results['frequency_spread_db'] = float(10 * np.log10(max_power / min_power))
        
        # === STATION DISCRIMINATION via 500/600 Hz ===
        # Only valid during single-station minutes (avoids BCD 100 Hz intermod)
        if '500Hz' in results['tones'] and '600Hz' in results['tones']:
            snr_500 = results['tones']['500Hz']['snr_db']
            snr_600 = results['tones']['600Hz']['snr_db']
            
            results['wwv_indicator_snr'] = snr_500
            results['wwvh_indicator_snr'] = snr_600
            results['discrimination_ratio_db'] = snr_500 - snr_600
            
            if valid_for_discrimination:
                if is_wwv_only_minute:
                    # WWV broadcasting alone - check for 500 Hz presence
                    # If 500 Hz detected, confirms WWV propagation to receiver
                    if snr_500 > 6.0:
                        results['indicated_station'] = 'WWV'
                        results['discrimination_confidence'] = min(1.0, snr_500 / 15.0)
                    else:
                        results['indicated_station'] = 'WEAK_OR_ABSENT'
                        results['discrimination_confidence'] = 0.0
                        
                elif is_wwvh_only_minute:
                    # WWVH broadcasting alone - check for 600 Hz presence
                    # If 600 Hz detected, confirms WWVH propagation to receiver
                    if snr_600 > 6.0:
                        results['indicated_station'] = 'WWVH'
                        results['discrimination_confidence'] = min(1.0, snr_600 / 15.0)
                    else:
                        results['indicated_station'] = 'WEAK_OR_ABSENT'
                        results['discrimination_confidence'] = 0.0
            else:
                # Both stations may be broadcasting - ratio method unreliable due to BCD intermod
                results['indicated_station'] = 'INTERMOD_RISK'
                results['discrimination_confidence'] = 0.0
        
        return results
    
    # ===== Legacy Compatibility =====
    
