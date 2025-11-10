#!/usr/bin/env python3
"""
Multi-Station Tone Detector - Standalone Implementation

Detects WWV/WWVH/CHU time signal tones using phase-invariant quadrature
matched filtering. Extracted from grape_rtp_recorder.py for reusability.

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
import numpy as np
from typing import Optional, List, Dict, Tuple
from scipy import signal as scipy_signal
from scipy.signal import correlate

from .interfaces.tone_detection import ToneDetector, MultiStationToneDetector as IMultiStationToneDetector
from .interfaces.data_models import ToneDetectionResult, StationType

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
            # Detect BOTH WWV and WWVH
            self.templates[StationType.WWV] = self._create_template(1000, 0.8)
            self.templates[StationType.WWVH] = self._create_template(1200, 0.8)
        
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
        rtp_timestamp: Optional[int] = None
    ) -> Optional[List[ToneDetectionResult]]:
        """
        Process samples and detect tones (ToneDetector interface).
        
        Args:
            timestamp: UTC timestamp of samples (from time_snap if available)
            samples: Complex IQ samples at self.sample_rate
            rtp_timestamp: Optional RTP timestamp for provenance
            
        Returns:
            List of ToneDetectionResult objects (may contain WWV + WWVH),
            or None if no tones detected
        """
        self.total_attempts += 1
        detections = self._detect_tones_internal(samples, timestamp)
        
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
        current_unix_time: float
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
        buffer_duration_sec = len(iq_samples) / self.sample_rate
        minute_boundary = int((current_unix_time + buffer_duration_sec/2) / 60) * 60
        
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
                minute_boundary
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
        minute_boundary: int
    ) -> Optional[ToneDetectionResult]:
        """
        Correlate audio signal with station template
        
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
            logger.warning(f"{station_type.value} @ {frequency}Hz: Correlation failed: {e}")
            return None
        
        if len(corr_sin) == 0 or len(corr_cos) == 0:
            logger.warning(f"{station_type.value} @ {frequency}Hz: Empty correlation result")
            return None
        
        # Combine to get phase-invariant magnitude: sqrt(sin^2 + cos^2)
        min_len = min(len(corr_sin), len(corr_cos))
        correlation = np.sqrt(corr_sin[:min_len]**2 + corr_cos[:min_len]**2)
        
        # Expected position: tone should be at start of minute
        buffer_offset_sec = current_unix_time - minute_boundary
        expected_pos_samples = int(-buffer_offset_sec * self.sample_rate)
        
        # Search window: ±500ms around expected position
        search_window = int(0.5 * self.sample_rate)
        search_start = max(0, expected_pos_samples - search_window)
        search_end = min(len(correlation), expected_pos_samples + search_window)
        
        logger.debug(f"{station_type.value} @ {frequency}Hz: corr_len={len(correlation)}, "
                    f"expected_pos={expected_pos_samples}, search_window=[{search_start}:{search_end}]")
        
        if search_start >= search_end:
            logger.warning(f"{station_type.value} @ {frequency}Hz: Invalid search window!")
            return None
        
        # Find peak within search window
        search_region = correlation[search_start:search_end]
        local_peak_idx = np.argmax(search_region)
        peak_idx = search_start + local_peak_idx
        peak_val = correlation[peak_idx]
        
        # Noise-adaptive threshold: Use noise from OUTSIDE the search window
        noise_samples = np.concatenate([
            correlation[:max(0, search_start - 100)],
            correlation[min(len(correlation), search_end + 100):]
        ])
        
        if len(noise_samples) > 100:
            noise_mean = np.mean(noise_samples)
            noise_std = np.std(noise_samples)
            noise_floor = noise_mean + 2.0 * noise_std
        else:
            noise_mean = np.mean(correlation)
            noise_std = np.std(correlation)
            noise_floor = noise_mean + 2.0 * noise_std
        
        # Calculate timing relative to minute boundary
        onset_sample_idx = peak_idx
        onset_time = current_unix_time + (onset_sample_idx / self.sample_rate)
        timing_error_sec = onset_time - minute_boundary
        
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
        
        # Diagnostic logging BEFORE threshold check
        logger.debug(f"{station_type.value} @ {frequency}Hz: peak={peak_val:.2f}, "
                    f"noise_floor={noise_floor:.2f}, SNR={snr_db:.1f}dB, "
                    f"timing_err={timing_error_ms:+.1f}ms")
        
        # Check if peak is significant
        if peak_val <= noise_floor:
            logger.debug(f"  -> REJECTED (peak <= threshold)")
            return None
        
        # Calculate confidence (normalized correlation)
        confidence = min(1.0, peak_val / (noise_floor * 2.0))
        
        # Determine if this station should be used for time_snap
        # CRITICAL: Only WWV and CHU, NEVER WWVH
        use_for_time_snap = station_type in [StationType.WWV, StationType.CHU]
        
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
            noise_floor=float(noise_floor)
        )
        
        logger.info(f"{self.channel_name}: ✅ {station_type.value} DETECTED! "
                   f"Freq: {frequency}Hz, Duration: {duration:.1f}s, "
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
    
    # ===== Legacy Compatibility =====
    
    def detect_tone_onset(
        self,
        iq_samples: np.ndarray,
        buffer_start_time: float
    ) -> Tuple[bool, int, float]:
        """
        Compatibility wrapper for V2 recorder's old API
        
        Returns:
            tuple: (detected: bool, onset_idx: int, timing_error_ms: float)
        """
        detections = self._detect_tones_internal(iq_samples, buffer_start_time)
        
        if detections:
            # Return first (strongest) detection
            det = detections[0]
            # Calculate onset index (approximate from timing error)
            onset_idx = int((det.timestamp_utc - buffer_start_time) * self.sample_rate)
            return (True, onset_idx, det.timing_error_ms)
        else:
            return (False, 0, 0.0)
