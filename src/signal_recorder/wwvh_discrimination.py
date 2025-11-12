#!/usr/bin/env python3
"""
WWV/WWVH Discrimination Module

Improves discrimination between WWV and WWVH on shared frequencies (2.5, 5, 10, 15 MHz)
by combining multiple signal characteristics:

1. Frequency-domain: Relative power of 1000 Hz (WWV) vs 1200 Hz (WWVH) tones
2. Time-domain: Arrival time difference (differential propagation delay)
3. 440 Hz tone analysis: Detection in minute 1 (WWVH) and minute 2 (WWV)

This module processes tone detection results and additional signal analysis
to provide confident discrimination between the two stations.
"""

import logging
import numpy as np
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from datetime import datetime
from scipy import signal as scipy_signal
from scipy.fft import rfft, rfftfreq

from .interfaces.data_models import ToneDetectionResult, StationType

logger = logging.getLogger(__name__)


@dataclass
class DiscriminationResult:
    """
    Result of WWV/WWVH discrimination analysis
    
    Attributes:
        minute_timestamp: UTC timestamp of minute boundary
        wwv_detected: Whether WWV (1000 Hz) was detected
        wwvh_detected: Whether WWVH (1200 Hz) was detected
        wwv_power_db: Power of WWV 1000 Hz tone (dB relative to noise)
        wwvh_power_db: Power of WWVH 1200 Hz tone (dB relative to noise)
        power_ratio_db: WWV power - WWVH power (positive = WWV stronger)
        differential_delay_ms: WWV arrival time - WWVH arrival time (ms)
        dominant_station: 'WWV', 'WWVH', or 'BALANCED'
        confidence: 'high', 'medium', 'low' based on SNR and power difference
        tone_440hz_wwv_detected: Whether 440 Hz tone detected in minute 2
        tone_440hz_wwvh_detected: Whether 440 Hz tone detected in minute 1
        tone_440hz_wwv_power_db: Power of 440 Hz tone in minute 2 (if detected)
        tone_440hz_wwvh_power_db: Power of 440 Hz tone in minute 1 (if detected)
    """
    minute_timestamp: float
    wwv_detected: bool
    wwvh_detected: bool
    wwv_power_db: Optional[float] = None
    wwvh_power_db: Optional[float] = None
    power_ratio_db: Optional[float] = None
    differential_delay_ms: Optional[float] = None
    dominant_station: Optional[str] = None
    confidence: str = 'low'
    tone_440hz_wwv_detected: bool = False
    tone_440hz_wwvh_detected: bool = False
    tone_440hz_wwv_power_db: Optional[float] = None
    tone_440hz_wwvh_power_db: Optional[float] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for logging/storage"""
        return {
            'minute_timestamp': self.minute_timestamp,
            'wwv_detected': self.wwv_detected,
            'wwvh_detected': self.wwvh_detected,
            'wwv_power_db': self.wwv_power_db,
            'wwvh_power_db': self.wwvh_power_db,
            'power_ratio_db': self.power_ratio_db,
            'differential_delay_ms': self.differential_delay_ms,
            'dominant_station': self.dominant_station,
            'confidence': self.confidence,
            'tone_440hz_wwv_detected': self.tone_440hz_wwv_detected,
            'tone_440hz_wwvh_detected': self.tone_440hz_wwvh_detected,
            'tone_440hz_wwv_power_db': self.tone_440hz_wwv_power_db,
            'tone_440hz_wwvh_power_db': self.tone_440hz_wwvh_power_db
        }


class WWVHDiscriminator:
    """
    Discriminate between WWV and WWVH using multiple signal characteristics
    
    Combines:
    1. Per-minute 1000 Hz vs 1200 Hz power ratio
    2. Arrival time difference (differential propagation delay)
    3. 440 Hz tone presence in minutes 1 and 2
    """
    
    def __init__(self, channel_name: str):
        """
        Initialize discriminator
        
        Args:
            channel_name: Channel name for logging
        """
        self.channel_name = channel_name
        self.measurements: List[DiscriminationResult] = []
        
        # Keep last 1000 measurements
        self.max_history = 1000
        
        logger.info(f"{channel_name}: WWVHDiscriminator initialized")
    
    def compute_discrimination(
        self,
        detections: List[ToneDetectionResult],
        minute_timestamp: float
    ) -> DiscriminationResult:
        """
        Compute discrimination from tone detection results
        
        ALWAYS returns a result - uses noise floor when tones not detected.
        Differential delay is only set when BOTH tones are detected.
        
        Args:
            detections: List of ToneDetectionResult objects from same minute
            minute_timestamp: UTC timestamp of minute boundary
            
        Returns:
            DiscriminationResult (never None - always records SNR/noise)
        """
        wwv_det = None
        wwvh_det = None
        
        # Handle None or empty detections
        if not detections:
            detections = []
        
        for det in detections:
            if det.station == StationType.WWV:
                wwv_det = det
            elif det.station == StationType.WWVH:
                wwvh_det = det
        
        # Extract power/SNR measurements (use noise floor if not detected)
        wwv_detected = wwv_det is not None
        wwvh_detected = wwvh_det is not None
        
        if wwv_detected:
            wwv_power_db = getattr(wwv_det, 'tone_power_db', wwv_det.snr_db)
        else:
            # No WWV detection - record noise floor (assume ~0 dB SNR = noise)
            wwv_power_db = 0.0
        
        if wwvh_detected:
            wwvh_power_db = getattr(wwvh_det, 'tone_power_db', wwvh_det.snr_db)
        else:
            # No WWVH detection - record noise floor
            wwvh_power_db = 0.0
        
        # Calculate power ratio (always computed, even with noise floor)
        power_ratio_db = wwv_power_db - wwvh_power_db
        
        # Calculate differential delay ONLY if BOTH detected
        # Otherwise null (creates gap in time-series graph)
        differential_delay_ms = None
        if wwv_detected and wwvh_detected:
            differential_delay_ms = wwv_det.timing_error_ms - wwvh_det.timing_error_ms
            
            # Reject outliers: Ionospheric differential delay should be < ±1 second
            # Values outside this range indicate detection errors
            if abs(differential_delay_ms) > 1000:
                logger.warning(f"{self.channel_name}: Rejecting outlier differential delay: {differential_delay_ms:.1f}ms "
                              f"(WWV: {wwv_det.timing_error_ms:.1f}ms, WWVH: {wwvh_det.timing_error_ms:.1f}ms)")
                differential_delay_ms = None
        
        # Determine dominant station
        if not wwv_detected and not wwvh_detected:
            dominant_station = 'NONE'
        elif not wwv_detected:
            dominant_station = 'WWVH'  # Only WWVH detected
        elif not wwvh_detected:
            dominant_station = 'WWV'  # Only WWV detected
        elif abs(power_ratio_db) < 3.0:  # Within 3 dB = balanced
            dominant_station = 'BALANCED'
        elif power_ratio_db > 0:
            dominant_station = 'WWV'
        else:
            dominant_station = 'WWVH'
        
        # Determine confidence based on actual detections
        if wwv_detected and wwvh_detected:
            min_snr = min(wwv_det.snr_db, wwvh_det.snr_db)
            power_diff = abs(power_ratio_db)
            
            if min_snr > 20 and power_diff > 6.0:
                confidence = 'high'
            elif min_snr > 10 and power_diff > 3.0:
                confidence = 'medium'
            else:
                confidence = 'low'
        else:
            # Only one or neither detected - low confidence
            confidence = 'low'
        
        result = DiscriminationResult(
            minute_timestamp=minute_timestamp,
            wwv_detected=wwv_detected,
            wwvh_detected=wwvh_detected,
            wwv_power_db=wwv_power_db,
            wwvh_power_db=wwvh_power_db,
            power_ratio_db=power_ratio_db,
            differential_delay_ms=differential_delay_ms,  # None if either missing
            dominant_station=dominant_station,
            confidence=confidence
        )
        
        # Store measurement
        self.measurements.append(result)
        if len(self.measurements) > self.max_history:
            self.measurements = self.measurements[-self.max_history:]
        
        # Log appropriately based on detection status
        if wwv_detected and wwvh_detected:
            logger.info(f"{self.channel_name}: Discrimination - "
                       f"WWV: {wwv_power_db:.1f}dB, WWVH: {wwvh_power_db:.1f}dB, "
                       f"Ratio: {power_ratio_db:+.1f}dB, Delay: {differential_delay_ms:+.1f}ms, "
                       f"Dominant: {dominant_station}, Confidence: {confidence}")
        else:
            logger.debug(f"{self.channel_name}: Discrimination (partial) - "
                        f"WWV: {'detected' if wwv_detected else 'noise'} ({wwv_power_db:.1f}dB), "
                        f"WWVH: {'detected' if wwvh_detected else 'noise'} ({wwvh_power_db:.1f}dB)")
        
        return result
    
    def detect_440hz_tone(
        self,
        iq_samples: np.ndarray,
        sample_rate: int,
        minute_number: int
    ) -> Tuple[bool, Optional[float]]:
        """
        Detect 440 Hz tone in AM-demodulated signal
        
        Args:
            iq_samples: Complex IQ samples at sample_rate
            sample_rate: Sample rate in Hz (typically 16000)
            minute_number: Minute number (0-59), should be 1 or 2 for 440 Hz
            
        Returns:
            (detected: bool, power_db: Optional[float])
        """
        # 440 Hz tone is only in minutes 1 (WWVH) and 2 (WWV)
        if minute_number not in [1, 2]:
            return False, None
        
        # AM demodulation
        magnitude = np.abs(iq_samples)
        audio_signal = magnitude - np.mean(magnitude)  # AC coupling
        
        # Extract window :15-:59 (44 seconds) where 440 Hz tone is present
        # For a full minute at 16 kHz, that's samples 240000 to 960000
        start_sample = int(15.0 * sample_rate)
        end_sample = int(59.0 * sample_rate)
        
        if len(audio_signal) < end_sample:
            # If we don't have full minute, use what we have
            end_sample = len(audio_signal)
            if end_sample < start_sample + int(10.0 * sample_rate):  # Need at least 10 seconds
                return False, None
        
        tone_window = audio_signal[start_sample:end_sample]
        
        # Resample to higher rate for better frequency resolution if needed
        # 440 Hz needs at least 880 Hz sample rate (Nyquist), but we'll use FFT
        # For 16 kHz, we have plenty of resolution
        
        # Use FFT to measure power at 440 Hz
        # Window the signal to reduce spectral leakage
        windowed = tone_window * scipy_signal.windows.hann(len(tone_window))
        
        # Compute FFT
        fft_result = rfft(windowed)
        freqs = rfftfreq(len(windowed), 1/sample_rate)
        
        # Find bin closest to 440 Hz
        target_freq = 440.0
        freq_idx = np.argmin(np.abs(freqs - target_freq))
        actual_freq = freqs[freq_idx]
        
        # Measure power at 440 Hz
        power_at_440 = np.abs(fft_result[freq_idx])**2
        
        # Measure noise floor (average power in nearby bins, excluding 440 Hz)
        # Use bins ±50 Hz around 440 Hz, excluding ±5 Hz
        noise_low = max(0, freq_idx - int(50.0 * len(windowed) / sample_rate))
        noise_high = min(len(fft_result), freq_idx + int(50.0 * len(windowed) / sample_rate))
        exclude_low = max(0, freq_idx - int(5.0 * len(windowed) / sample_rate))
        exclude_high = min(len(fft_result), freq_idx + int(5.0 * len(windowed) / sample_rate))
        
        noise_bins = np.concatenate([
            np.arange(noise_low, exclude_low),
            np.arange(exclude_high, noise_high)
        ])
        
        if len(noise_bins) > 10:
            noise_power = np.mean(np.abs(fft_result[noise_bins])**2)
        else:
            # Fallback: use overall average
            noise_power = np.mean(np.abs(fft_result)**2)
        
        # Calculate SNR
        if noise_power > 0:
            snr_linear = power_at_440 / noise_power
            snr_db = 10 * np.log10(snr_linear)
            power_db = 10 * np.log10(power_at_440 + 1e-12)  # Relative power
        else:
            snr_db = 0.0
            power_db = -np.inf
        
        # Detection threshold: SNR > 10 dB
        detected = snr_db > 10.0
        
        if detected:
            logger.debug(f"{self.channel_name}: 440 Hz tone detected in minute {minute_number} - "
                        f"Power: {power_db:.1f}dB, SNR: {snr_db:.1f}dB, "
                        f"Freq: {actual_freq:.1f}Hz")
        
        return detected, power_db if detected else None
    
    def analyze_minute_with_440hz(
        self,
        iq_samples: np.ndarray,
        sample_rate: int,
        minute_timestamp: float,
        detections: List[ToneDetectionResult]
    ) -> Optional[DiscriminationResult]:
        """
        Complete discrimination analysis including 440 Hz tone
        
        Args:
            iq_samples: Full minute of IQ samples
            sample_rate: Sample rate in Hz
            minute_timestamp: UTC timestamp of minute boundary
            detections: Tone detection results for this minute
            
        Returns:
            Enhanced DiscriminationResult with 440 Hz analysis
        """
        # First compute basic discrimination
        result = self.compute_discrimination(detections, minute_timestamp)
        
        if result is None:
            return None
        
        # Get minute number (0-59)
        dt = datetime.utcfromtimestamp(minute_timestamp)
        minute_number = dt.minute
        
        # Detect 440 Hz tone if in minutes 1 or 2
        if minute_number == 1:
            # WWVH should have 440 Hz tone
            detected, power_db = self.detect_440hz_tone(iq_samples, sample_rate, 1)
            result.tone_440hz_wwvh_detected = detected
            result.tone_440hz_wwvh_power_db = power_db
            
            # If 440 Hz detected, increases confidence that WWVH is present
            if detected and result.confidence == 'low':
                result.confidence = 'medium'
        
        elif minute_number == 2:
            # WWV should have 440 Hz tone
            detected, power_db = self.detect_440hz_tone(iq_samples, sample_rate, 2)
            result.tone_440hz_wwv_detected = detected
            result.tone_440hz_wwv_power_db = power_db
            
            # If 440 Hz detected, increases confidence that WWV is present
            if detected and result.confidence == 'low':
                result.confidence = 'medium'
        
        return result
    
    def get_recent_measurements(self, count: int = 10) -> List[DiscriminationResult]:
        """Get most recent discrimination measurements"""
        return self.measurements[-count:]
    
    def get_statistics(self) -> Dict:
        """Get statistics over recent measurements"""
        if not self.measurements:
            return {
                'count': 0,
                'mean_power_ratio_db': 0.0,
                'mean_differential_delay_ms': 0.0,
                'wwv_dominant_count': 0,
                'wwvh_dominant_count': 0,
                'balanced_count': 0
            }
        
        power_ratios = [m.power_ratio_db for m in self.measurements if m.power_ratio_db is not None]
        delays = [m.differential_delay_ms for m in self.measurements if m.differential_delay_ms is not None]
        
        wwv_count = sum(1 for m in self.measurements if m.dominant_station == 'WWV')
        wwvh_count = sum(1 for m in self.measurements if m.dominant_station == 'WWVH')
        balanced_count = sum(1 for m in self.measurements if m.dominant_station == 'BALANCED')
        
        return {
            'count': len(self.measurements),
            'mean_power_ratio_db': float(np.mean(power_ratios)) if power_ratios else 0.0,
            'std_power_ratio_db': float(np.std(power_ratios)) if power_ratios else 0.0,
            'mean_differential_delay_ms': float(np.mean(delays)) if delays else 0.0,
            'std_differential_delay_ms': float(np.std(delays)) if delays else 0.0,
            'wwv_dominant_count': wwv_count,
            'wwvh_dominant_count': wwvh_count,
            'balanced_count': balanced_count
        }


