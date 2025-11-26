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
from scipy.signal import iirnotch, filtfilt

from .interfaces.data_models import ToneDetectionResult, StationType
from .tone_detector import MultiStationToneDetector
from .wwv_bcd_encoder import WWVBCDEncoder
from .wwv_geographic_predictor import WWVGeographicPredictor
from .wwv_test_signal import WWVTestSignalDetector, TestSignalDetection

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
        tick_windows_10sec: High-resolution 10-second windowed tick analysis (6 windows per minute)
            Each window contains both coherent and incoherent integration results:
            - coherent_wwv_snr_db, coherent_wwvh_snr_db: Phase-aligned amplitude sum (10 dB gain)
            - incoherent_wwv_snr_db, incoherent_wwvh_snr_db: Power sum (5 dB gain)
            - coherence_quality: 0-1 metric indicating phase stability
            - integration_method: 'coherent' or 'incoherent' (chosen based on quality)
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
    tick_windows_10sec: Optional[List[Dict[str, float]]] = None
    # BCD-based discrimination (100 Hz cross-correlation method)
    bcd_wwv_amplitude: Optional[float] = None
    bcd_wwvh_amplitude: Optional[float] = None
    bcd_differential_delay_ms: Optional[float] = None
    bcd_correlation_quality: Optional[float] = None
    bcd_windows: Optional[List[Dict[str, float]]] = None  # Time-series data from sliding windows
    # Test signal discrimination (minute 8/44 scientific modulation test)
    test_signal_detected: bool = False
    test_signal_station: Optional[str] = None  # 'WWV' or 'WWVH'
    test_signal_confidence: Optional[float] = None
    test_signal_multitone_score: Optional[float] = None
    test_signal_chirp_score: Optional[float] = None
    test_signal_snr_db: Optional[float] = None
    
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
            'tone_440hz_wwvh_power_db': self.tone_440hz_wwvh_power_db,
            'tick_windows_10sec': self.tick_windows_10sec
        }


class WWVHDiscriminator:
    """
    Discriminate between WWV and WWVH using multiple signal characteristics
    
    Combines:
    1. Per-minute 1000 Hz vs 1200 Hz power ratio
    2. Arrival time difference (differential propagation delay)
    3. 440 Hz tone presence in minutes 1 and 2
    """
    
    def __init__(
        self,
        channel_name: str,
        receiver_grid: Optional[str] = None,
        history_dir: Optional[str] = None
    ):
        """
        Initialize discriminator
        
        Args:
            channel_name: Channel name for logging
            receiver_grid: Maidenhead grid square (e.g., "EM38ww") for geographic ToA prediction
            history_dir: Directory for persisting ToA history (optional)
        """
        self.channel_name = channel_name
        self.measurements: List[DiscriminationResult] = []
        
        # Keep last 1000 measurements
        self.max_history = 1000
        
        # Initialize BCD encoder for template generation
        self.bcd_encoder = WWVBCDEncoder(sample_rate=16000)
        
        # Initialize test signal detector for minute 8/44 discrimination
        self.test_signal_detector = WWVTestSignalDetector(sample_rate=16000)
        logger.info(f"{channel_name}: Test signal detector initialized for minutes 8/44")
        
        # Initialize geographic predictor if grid square provided
        self.geo_predictor: Optional[WWVGeographicPredictor] = None
        if receiver_grid:
            from pathlib import Path
            history_file = None
            if history_dir:
                history_file = Path(history_dir) / f"toa_history_{channel_name.replace(' ', '_')}.json"
            
            self.geo_predictor = WWVGeographicPredictor(
                receiver_grid=receiver_grid,
                history_file=history_file,
                max_history=1000
            )
            logger.info(f"{channel_name}: Geographic ToA prediction enabled for {receiver_grid}")
        else:
            logger.info(f"{channel_name}: Geographic ToA prediction disabled (no grid square configured)")
        
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
            # Ensure we have a valid number
            if wwv_power_db is None:
                wwv_power_db = wwv_det.snr_db if wwv_det.snr_db is not None else 0.0
        else:
            # No WWV detection - record noise floor (assume ~0 dB SNR = noise)
            wwv_power_db = 0.0
        
        if wwvh_detected:
            wwvh_power_db = getattr(wwvh_det, 'tone_power_db', wwvh_det.snr_db)
            # Ensure we have a valid number
            if wwvh_power_db is None:
                wwvh_power_db = wwvh_det.snr_db if wwvh_det.snr_db is not None else 0.0
        else:
            # No WWVH detection - record noise floor
            wwvh_power_db = 0.0
        
        # Calculate power ratio (always computed, even with noise floor)
        # Safety check for None values
        if wwv_power_db is None or wwvh_power_db is None:
            power_ratio_db = 0.0
        else:
            power_ratio_db = wwv_power_db - wwvh_power_db
        
        # Calculate differential delay ONLY if BOTH detected
        # Otherwise null (creates gap in time-series graph)
        differential_delay_ms = None
        if wwv_detected and wwvh_detected:
            # Safety check for None timing errors
            if wwv_det.timing_error_ms is not None and wwvh_det.timing_error_ms is not None:
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
            max_snr = max(wwv_det.snr_db, wwvh_det.snr_db)
            power_diff = abs(power_ratio_db)
            
            # Improved confidence logic:
            # High confidence: Strong dominant station OR both stations strong with clear separation
            if (max_snr > 25 and power_diff > 15):  # One very strong, other clearly weaker
                confidence = 'high'
            elif (min_snr > 20 and power_diff > 6.0):  # Both strong with good separation
                confidence = 'high'
            elif (max_snr > 15 and power_diff > 10):  # One strong with clear dominance
                confidence = 'medium'
            elif (min_snr > 10 and power_diff > 3.0):  # Both moderate with separation
                confidence = 'medium'
            else:
                confidence = 'low'
        elif wwv_detected or wwvh_detected:
            # Single station detected - confidence based on SNR of detected station
            detected_snr = wwv_det.snr_db if wwv_detected else wwvh_det.snr_db
            if detected_snr > 20:
                confidence = 'high'  # Strong single station is high confidence
            elif detected_snr > 10:
                confidence = 'medium'
            else:
                confidence = 'low'
        else:
            # Neither detected - low confidence
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
            # Safely format values that might be None
            wwv_str = f"{wwv_power_db:.1f}dB" if wwv_power_db is not None else "N/A"
            wwvh_str = f"{wwvh_power_db:.1f}dB" if wwvh_power_db is not None else "N/A"
            ratio_str = f"{power_ratio_db:+.1f}dB" if power_ratio_db is not None else "N/A"
            delay_str = f"{differential_delay_ms:+.1f}ms" if differential_delay_ms is not None else "N/A"
            
            logger.info(f"{self.channel_name}: Discrimination - "
                       f"WWV: {wwv_str}, WWVH: {wwvh_str}, "
                       f"Ratio: {ratio_str}, Delay: {delay_str}, "
                       f"Dominant: {dominant_station or 'N/A'}, Confidence: {confidence or 'N/A'}")
        else:
            wwv_str = f"{wwv_power_db:.1f}dB" if wwv_power_db is not None else "N/A"
            wwvh_str = f"{wwvh_power_db:.1f}dB" if wwvh_power_db is not None else "N/A"
            logger.debug(f"{self.channel_name}: Discrimination (partial) - "
                        f"WWV: {'detected' if wwv_detected else 'noise'} ({wwv_str}), "
                        f"WWVH: {'detected' if wwvh_detected else 'noise'} ({wwvh_str})")
        
        return result
    
    def detect_timing_tones(
        self,
        iq_samples: np.ndarray,
        sample_rate: int,
        minute_timestamp: float
    ) -> Tuple[Optional[float], Optional[float], Optional[float], List[ToneDetectionResult]]:
        """
        Detect 800ms timing tones from IQ samples - INDEPENDENT METHOD
        
        This method integrates ToneDetector to make tone detection independent
        and reprocessable from archived IQ data. It extracts WWV/WWVH power
        measurements and differential delay for discrimination.
        
        Args:
            iq_samples: Complex IQ samples at sample_rate (typically 16 kHz, 60 seconds)
            sample_rate: Sample rate in Hz
            minute_timestamp: UTC timestamp of minute boundary
            
        Returns:
            Tuple of:
            - wwv_power_db: WWV 1000 Hz tone power (dB), or None if not detected
            - wwvh_power_db: WWVH 1200 Hz tone power (dB), or None if not detected
            - differential_delay_ms: Propagation delay difference (ms), or None if not both detected
            - detections: List of ToneDetectionResult objects (for full provenance)
        """
        # Initialize tone detector if not already present
        if not hasattr(self, 'tone_detector'):
            self.tone_detector = MultiStationToneDetector(
                channel_name=self.channel_name,
                sample_rate=sample_rate
            )
        elif self.tone_detector.sample_rate != sample_rate:
            # Reinitialize if sample rate changed
            self.tone_detector = MultiStationToneDetector(
                channel_name=self.channel_name,
                sample_rate=sample_rate
            )
        
        # Detect tones using process_samples() method
        try:
            detections = self.tone_detector.process_samples(
                timestamp=minute_timestamp,
                samples=iq_samples
            )
            if detections is None:
                detections = []
        except Exception as e:
            logger.warning(f"{self.channel_name}: Tone detection failed: {e}")
            return None, None, None, []
        
        # Extract WWV and WWVH detections
        wwv_det = None
        wwvh_det = None
        
        for det in detections:
            if det.station == StationType.WWV:
                wwv_det = det
            elif det.station == StationType.WWVH:
                wwvh_det = det
        
        # Extract power measurements
        wwv_power_db = None
        wwvh_power_db = None
        differential_delay_ms = None
        
        if wwv_det:
            # Prefer tone_power_db, fall back to snr_db
            wwv_power_db = getattr(wwv_det, 'tone_power_db', None)
            if wwv_power_db is None:
                wwv_power_db = wwv_det.snr_db if wwv_det.snr_db is not None else 0.0
        
        if wwvh_det:
            wwvh_power_db = getattr(wwvh_det, 'tone_power_db', None)
            if wwvh_power_db is None:
                wwvh_power_db = wwvh_det.snr_db if wwvh_det.snr_db is not None else 0.0
        
        # Calculate differential delay only if both detected
        if wwv_det and wwvh_det:
            if wwv_det.timing_error_ms is not None and wwvh_det.timing_error_ms is not None:
                differential_delay_ms = wwv_det.timing_error_ms - wwvh_det.timing_error_ms
                
                # Sanity check: reject outliers beyond ±1 second
                if abs(differential_delay_ms) > 1000:
                    logger.warning(
                        f"{self.channel_name}: Rejecting outlier differential delay: "
                        f"{differential_delay_ms:.1f}ms (WWV: {wwv_det.timing_error_ms:.1f}ms, "
                        f"WWVH: {wwvh_det.timing_error_ms:.1f}ms)"
                    )
                    differential_delay_ms = None
        
        return wwv_power_db, wwvh_power_db, differential_delay_ms, detections
    
    def finalize_discrimination(
        self,
        result: DiscriminationResult,
        minute_number: int,
        bcd_wwv_amp: Optional[float],
        bcd_wwvh_amp: Optional[float],
        tone_440_wwv_detected: bool,
        tone_440_wwvh_detected: bool,
        tick_results: Optional[List[dict]] = None
    ) -> DiscriminationResult:
        """
        Finalize discrimination using weighted voting based on minute-specific confidence
        
        Weighting hierarchy:
        - Minutes 1/2: 440 Hz tone (highest weight) → Tick SNR → BCD (if available)
        - Minutes 0/8-10/29-30: BCD amplitude (highest weight) → Tick SNR → 1000/1200 Hz
        - All other minutes: 1000/1200 Hz power (highest weight) → Tick SNR
        
        Args:
            result: Base discrimination result from 1000/1200 Hz tones
            minute_number: Minute of hour (0-59)
            bcd_wwv_amp: WWV amplitude from BCD correlation
            bcd_wwvh_amp: WWVH amplitude from BCD correlation
            tone_440_wwv_detected: 440 Hz detected in minute 2
            tone_440_wwvh_detected: 440 Hz detected in minute 1
            tick_results: Per-second tick discrimination results
            
        Returns:
            Enhanced DiscriminationResult with weighted voting
        """
        # BCD-dominant minutes (0, 8-10, 29-30)
        bcd_minutes = [0, 8, 9, 10, 29, 30]
        # 440 Hz tone minutes
        tone_440_minutes = [1, 2]
        
        # Initialize voting scores
        wwv_score = 0.0
        wwvh_score = 0.0
        total_weight = 0.0
        
        # Weight factors
        if minute_number in tone_440_minutes:
            w_440 = 10.0  # Highest weight for 440 Hz
            w_tick = 5.0
            w_bcd = 2.0
            w_carrier = 1.0
        elif minute_number in bcd_minutes:
            w_bcd = 10.0  # Highest weight for BCD
            w_tick = 5.0
            w_carrier = 2.0
            w_440 = 0.0
        else:
            w_carrier = 10.0  # Highest weight for carrier tones
            w_tick = 5.0
            w_bcd = 2.0
            w_440 = 0.0
        
        # === VOTE 1: 440 Hz Tone Detection ===
        if w_440 > 0:
            if tone_440_wwv_detected and not tone_440_wwvh_detected:
                wwv_score += w_440
                total_weight += w_440
            elif tone_440_wwvh_detected and not tone_440_wwv_detected:
                wwvh_score += w_440
                total_weight += w_440
            elif tone_440_wwv_detected and tone_440_wwvh_detected:
                # Both detected (shouldn't happen) - ignore
                pass
        
        # === VOTE 2: BCD Amplitude Ratio ===
        if w_bcd > 0 and bcd_wwv_amp is not None and bcd_wwvh_amp is not None:
            if bcd_wwv_amp > 0 and bcd_wwvh_amp > 0:
                bcd_ratio_db = 20 * np.log10(bcd_wwv_amp / bcd_wwvh_amp)
                
                if abs(bcd_ratio_db) >= 3.0:  # Significant difference
                    if bcd_ratio_db > 0:
                        wwv_score += w_bcd
                    else:
                        wwvh_score += w_bcd
                    total_weight += w_bcd
        
        # === VOTE 3: 1000/1200 Hz Carrier Power Ratio ===
        if w_carrier > 0 and result.power_ratio_db is not None:
            if abs(result.power_ratio_db) >= 3.0:  # Significant difference
                if result.power_ratio_db > 0:
                    wwv_score += w_carrier
                else:
                    wwvh_score += w_carrier
                total_weight += w_carrier
        
        # === VOTE 4: Per-Second Tick SNR Average ===
        if w_tick > 0 and tick_results:
            wwv_tick_snr = []
            wwvh_tick_snr = []
            
            for tick in tick_results:
                if 'wwv_snr_db' in tick and 'wwvh_snr_db' in tick:
                    wwv_tick_snr.append(tick['wwv_snr_db'])
                    wwvh_tick_snr.append(tick['wwvh_snr_db'])
            
            if wwv_tick_snr and wwvh_tick_snr:
                avg_wwv_tick = np.mean(wwv_tick_snr)
                avg_wwvh_tick = np.mean(wwvh_tick_snr)
                tick_ratio_db = avg_wwv_tick - avg_wwvh_tick
                
                if abs(tick_ratio_db) >= 3.0:
                    if tick_ratio_db > 0:
                        wwv_score += w_tick
                    else:
                        wwvh_score += w_tick
                    total_weight += w_tick
        
        # === FINAL DECISION ===
        if total_weight > 0:
            # Normalize scores
            wwv_norm = wwv_score / total_weight
            wwvh_norm = wwvh_score / total_weight
            
            # Determine dominant station
            if abs(wwv_norm - wwvh_norm) < 0.15:  # Within ~15% of each other
                dominant_station = 'BALANCED'
                confidence = 'medium'
            elif wwv_norm > wwvh_norm:
                dominant_station = 'WWV'
                # Confidence based on score margin
                margin = wwv_norm - wwvh_norm
                if margin > 0.7:
                    confidence = 'high'
                elif margin > 0.4:
                    confidence = 'medium'
                else:
                    confidence = 'low'
            else:
                dominant_station = 'WWVH'
                margin = wwvh_norm - wwv_norm
                if margin > 0.7:
                    confidence = 'high'
                elif margin > 0.4:
                    confidence = 'medium'
                else:
                    confidence = 'low'
            
            # Update result
            result.dominant_station = dominant_station
            result.confidence = confidence
        
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
        
        # Measure noise floor using the 825-875 Hz guard band (consistent with tick detection)
        # This band is guaranteed clean (no station tones or harmonics)
        # High-pass filter at 200 Hz is already implicit in AM demod DC removal
        guard_low = 825.0  # Hz
        guard_high = 875.0  # Hz
        
        guard_low_idx = np.argmin(np.abs(freqs - guard_low))
        guard_high_idx = np.argmin(np.abs(freqs - guard_high))
        
        if guard_high_idx > guard_low_idx and guard_high_idx < len(fft_result):
            # Measure noise power density (N₀) in guard band
            guard_band_power = np.abs(fft_result[guard_low_idx:guard_high_idx])**2
            N0 = np.mean(guard_band_power)  # W/Hz (average power per bin)
            
            # For 440 Hz tone, use ENBW = 1.5 Hz (Hann window)
            B_signal = 1.5  # Hz
            noise_power = N0 * B_signal
        else:
            # Fallback: use overall average (shouldn't happen)
            noise_power = np.mean(np.abs(fft_result)**2)
        
        # Calculate SNR
        if noise_power > 0:
            snr_linear = power_at_440 / noise_power
            snr_db = 10 * np.log10(snr_linear)
            power_db = 10 * np.log10(power_at_440 + 1e-12)  # Relative power
        else:
            snr_db = 0.0
            power_db = -np.inf
        
        # Detection threshold: SNR > 6 dB (aligned with tone detector threshold)
        # NOTE: This threshold could be made adaptive based on the 1000/1200 Hz tone SNRs
        # 6 dB matches the sensitivity used for 1000/1200 Hz tone detection
        detected = snr_db > 6.0
        
        if detected:
            logger.debug(f"{self.channel_name}: 440 Hz tone detected in minute {minute_number} - "
                        f"Power: {power_db:.1f}dB, SNR: {snr_db:.1f}dB, "
                        f"Freq: {actual_freq:.1f}Hz")
        
        return detected, power_db if detected else None
    
    def detect_tick_windows(
        self,
        iq_samples: np.ndarray,
        sample_rate: int,
        window_seconds: int = 60
    ) -> List[Dict[str, float]]:
        """
        Detect 5ms tick tones with coherent integration
        
        DISCRIMINATION-FIRST PHILOSOPHY:
        Default uses 60-second window (full minute) for maximum tick stacking.
        This provides √59 ≈ 7.7x SNR improvement over 10-second windows (+8.9 dB).
        
        Implements true coherent integration with phase tracking:
        - Coherent: Phase-aligned amplitude sum → 10*log10(N) dB gain
        - Incoherent: Power sum → 5*log10(N) dB gain
        - Automatically selects best method based on phase stability
        
        Args:
            iq_samples: Full minute of complex IQ samples at sample_rate
            sample_rate: Sample rate in Hz (typically 16000)
            window_seconds: Integration window (60=full minute baseline, 10=legacy)
            
        Returns:
            List of dictionaries (1 for 60s, 6 for 10s windows):
            {
                'second': start second in minute (1 for 60s, varies for 10s),
                    NOTE: Second 0 is EXCLUDED (contains 800ms tone marker)
                'coherent_wwv_snr_db': Coherent integration SNR,
                'coherent_wwvh_snr_db': Coherent integration SNR,
                'incoherent_wwv_snr_db': Incoherent integration SNR,
                'incoherent_wwvh_snr_db': Incoherent integration SNR,
                'coherence_quality_wwv': Phase stability metric (0-1),
                'coherence_quality_wwvh': Phase stability metric (0-1),
                'integration_method': 'coherent' or 'incoherent' (chosen),
                'wwv_snr_db': Best SNR (from chosen method),
                'wwvh_snr_db': Best SNR (from chosen method),
                'ratio_db': wwv_snr - wwvh_snr,
                'tick_count': number of ticks analyzed (59 for 60s, 10 or 9 for 10s)
            }
        """
        # AM demodulation for entire minute
        magnitude = np.abs(iq_samples)
        audio_signal = magnitude - np.mean(magnitude)  # AC coupling
        
        # CRITICAL: Remove station ID tones before tick detection to prevent harmonic contamination
        # WWV/WWVH broadcast 440/500/600 Hz tones throughout each minute per schedule.
        # Receiver 2nd/3rd order nonlinearity creates spurious signals at tick frequencies:
        #   500 Hz × 2 = 1000 Hz (contaminates WWV ticks)
        #   600 Hz × 2 = 1200 Hz (contaminates WWVH ticks)
        #   440 Hz × 3 = 1320 Hz (near WWVH 1200 Hz)
        # Must remove fundamentals to ensure clean, unbiased power measurements.
        
        # 440 Hz notch (Q=20, ~22 Hz width) - prevents 3rd harmonic at 1320 Hz
        b_440, a_440 = iirnotch(440, 20, sample_rate)
        audio_signal = filtfilt(b_440, a_440, audio_signal)
        
        # 500 Hz notch (Q=20, ~25 Hz width) - prevents 2nd harmonic at 1000 Hz
        b_500, a_500 = iirnotch(500, 20, sample_rate)
        audio_signal = filtfilt(b_500, a_500, audio_signal)
        
        # 600 Hz notch (Q=20, ~30 Hz width) - prevents 2nd harmonic at 1200 Hz
        b_600, a_600 = iirnotch(600, 20, sample_rate)
        audio_signal = filtfilt(b_600, a_600, audio_signal)
        
        samples_per_window = window_seconds * sample_rate
        
        # CRITICAL: Skip second 0 (contains 800ms tone marker)
        # For 60s: Single window covering seconds 1-59 (59 ticks)
        # For 10s: Six windows 1-10, 11-20, 21-30, 31-40, 41-50, 51-59
        if window_seconds >= 60:
            num_windows = 1
        else:
            num_windows = 6  # Legacy 10-second windows
        
        results = []
        
        for window_idx in range(num_windows):
            # Start at second 1 (not 0) to avoid 800ms tone marker
            if window_seconds >= 60:
                # Full minute: seconds 1-59 (59 ticks)
                window_start_second = 1
                window_end_second = 60
                actual_window_seconds = 59
            else:
                # Legacy 10-second windows
                window_start_second = 1 + (window_idx * window_seconds)
                # Last window is only 9 seconds (51-59)
                if window_idx == 5:
                    window_end_second = 60
                    actual_window_seconds = 9
                else:
                    window_end_second = window_start_second + window_seconds
                    actual_window_seconds = window_seconds
                    
            window_start_sample = window_start_second * sample_rate
            
            window_end_sample = window_end_second * sample_rate
            
            # Check if we have enough data
            if window_end_sample > len(audio_signal):
                logger.debug(f"{self.channel_name}: Tick window {window_idx} incomplete "
                            f"({len(audio_signal)} < {window_end_sample} samples)")
                break
            
            window_data = audio_signal[window_start_sample:window_end_sample]
            
            # Track both coherent (complex amplitude) and incoherent (power) integration
            wwv_complex_sum = 0.0 + 0.0j  # Coherent sum
            wwvh_complex_sum = 0.0 + 0.0j
            wwv_energy_sum = 0.0  # Incoherent sum
            wwvh_energy_sum = 0.0
            noise_estimate_sum = 0.0
            
            # Track phase for coherence quality measurement
            wwv_phases = []
            wwvh_phases = []
            
            valid_ticks = 0
            
            for tick_idx in range(actual_window_seconds):
                # Extract 100ms window around each tick (±50ms)
                # Ticks occur at :XX.0 seconds within the window
                tick_center_sample = tick_idx * sample_rate
                tick_window_start = max(0, tick_center_sample - int(0.05 * sample_rate))
                tick_window_end = min(len(window_data), tick_center_sample + int(0.05 * sample_rate))
                
                if tick_window_end - tick_window_start < int(0.08 * sample_rate):
                    continue  # Need at least 80ms
                
                tick_window = window_data[tick_window_start:tick_window_end]
                
                # Apply Hann window to reduce spectral leakage
                windowed_tick = tick_window * scipy_signal.windows.hann(len(tick_window))
                
                # Zero-pad to achieve 1 Hz frequency resolution
                # 1 second at sample_rate = 1 Hz bins
                padded_length = sample_rate  # 16000 samples → 1 Hz resolution
                padded_tick = np.pad(windowed_tick, (0, padded_length - len(windowed_tick)), mode='constant')
                
                # FFT to extract complex amplitudes with fine frequency resolution
                fft_result = rfft(padded_tick)
                freqs = rfftfreq(padded_length, 1/sample_rate)
                
                # Extract complex values at WWV (1000 Hz) and WWVH (1200 Hz)
                wwv_freq_idx = np.argmin(np.abs(freqs - 1000.0))
                wwvh_freq_idx = np.argmin(np.abs(freqs - 1200.0))
                
                wwv_complex = fft_result[wwv_freq_idx]  # Complex amplitude
                wwvh_complex = fft_result[wwvh_freq_idx]
                
                # Phase tracking for coherence quality
                wwv_phase = np.angle(wwv_complex)
                wwvh_phase = np.angle(wwvh_complex)
                
                # Phase correction: align to first tick's phase
                if valid_ticks == 0:
                    # Reference phase from first tick
                    wwv_ref_phase = wwv_phase
                    wwvh_ref_phase = wwvh_phase
                else:
                    # Correct phase drift (simple first-order correction)
                    wwv_phase_correction = np.exp(-1j * (wwv_phase - wwv_ref_phase))
                    wwvh_phase_correction = np.exp(-1j * (wwvh_phase - wwvh_ref_phase))
                    
                    wwv_complex *= wwv_phase_correction
                    wwvh_complex *= wwvh_phase_correction
                
                # Coherent integration: sum complex amplitudes
                wwv_complex_sum += wwv_complex
                wwvh_complex_sum += wwvh_complex
                
                # Incoherent integration: sum power
                wwv_energy = np.abs(wwv_complex)**2
                wwvh_energy = np.abs(wwvh_complex)**2
                wwv_energy_sum += wwv_energy
                wwvh_energy_sum += wwvh_energy
                
                # Track phases for coherence quality
                wwv_phases.append(wwv_phase)
                wwvh_phases.append(wwvh_phase)
                
                # Measure noise power density in clean guard band
                # Use 825-875 Hz (50 Hz band, below both signals and modulation sidebands)
                # Avoids:
                #   WWV: 1000 ± 100 Hz = 900-1100 Hz
                #   WWVH: 1200 ± 100 Hz = 1100-1300 Hz
                noise_low_idx = np.argmin(np.abs(freqs - 825.0))
                noise_high_idx = np.argmin(np.abs(freqs - 875.0))
                noise_bins = fft_result[noise_low_idx:noise_high_idx]
                
                if len(noise_bins) > 0:
                    # Total noise power in 50 Hz band
                    total_noise_power = np.mean(np.abs(noise_bins)**2)
                    # Normalize to power spectral density (W/Hz)
                    noise_bandwidth_hz = 50.0
                    noise_power_density = total_noise_power / noise_bandwidth_hz
                    noise_estimate_sum += noise_power_density
                else:
                    noise_estimate_sum += 1e-12
                
                valid_ticks += 1
            
            # Calculate average noise power density per tick
            if valid_ticks > 0 and noise_estimate_sum > 0:
                N0 = noise_estimate_sum / valid_ticks  # Average noise power density (W/Hz)
                
                # Signal filter bandwidth (effective)
                # Hann window ENBW = 1.5 × frequency resolution
                # With 1 Hz FFT bins (1 second zero-padding), ENBW = 1.5 Hz
                B_signal = 1.5  # Hz (Hann window ENBW)
                
                # ===== COHERENT INTEGRATION (10 dB gain) =====
                # Power from coherent sum of complex amplitudes
                wwv_coherent_power = np.abs(wwv_complex_sum)**2
                wwvh_coherent_power = np.abs(wwvh_complex_sum)**2
                
                # SNR with proper bandwidth normalization
                # SNR = S / (N₀ × B_signal × N_ticks)
                noise_power_coherent = N0 * B_signal * valid_ticks
                coherent_wwv_snr = 10 * np.log10(wwv_coherent_power / noise_power_coherent) if wwv_coherent_power > 0 else -100
                coherent_wwvh_snr = 10 * np.log10(wwvh_coherent_power / noise_power_coherent) if wwvh_coherent_power > 0 else -100
                
                # ===== INCOHERENT INTEGRATION (5 dB gain) =====
                # Sum of power (energy)
                noise_power_incoherent = N0 * B_signal * valid_ticks
                incoherent_wwv_snr = 10 * np.log10(wwv_energy_sum / noise_power_incoherent) if wwv_energy_sum > 0 else -100
                incoherent_wwvh_snr = 10 * np.log10(wwvh_energy_sum / noise_power_incoherent) if wwvh_energy_sum > 0 else -100
                
                # ===== COHERENCE QUALITY METRIC =====
                # Measure phase stability: low variance = high coherence
                # Quality = 1 - (phase_variance / π²)  → ranges 0 (random) to 1 (stable)
                wwv_coherence_quality = 0.0
                wwvh_coherence_quality = 0.0
                
                if len(wwv_phases) > 1:
                    # Unwrap phases to handle 2π discontinuities
                    wwv_phases_unwrapped = np.unwrap(wwv_phases)
                    wwv_phase_variance = np.var(wwv_phases_unwrapped)
                    # Normalize: perfect coherence = 0 variance, random = π²/3 variance
                    wwv_coherence_quality = max(0.0, min(1.0, 1.0 - (wwv_phase_variance / (np.pi**2 / 3))))
                
                if len(wwvh_phases) > 1:
                    wwvh_phases_unwrapped = np.unwrap(wwvh_phases)
                    wwvh_phase_variance = np.var(wwvh_phases_unwrapped)
                    wwvh_coherence_quality = max(0.0, min(1.0, 1.0 - (wwvh_phase_variance / (np.pi**2 / 3))))
                
                # ===== CHOOSE INTEGRATION METHOD =====
                # Use coherent integration if it yields significantly higher SNR
                # If coherent SNR > incoherent SNR + threshold, coherence is real
                # Otherwise fall back to incoherent (more robust)
                coherent_snr_advantage_threshold = 3.0  # dB
                
                # Check if coherent method provides real SNR improvement
                wwv_coherent_advantage = coherent_wwv_snr - incoherent_wwv_snr
                wwvh_coherent_advantage = coherent_wwvh_snr - incoherent_wwvh_snr
                
                # Use coherent if BOTH stations show coherent advantage
                if (wwv_coherent_advantage >= coherent_snr_advantage_threshold and 
                    wwvh_coherent_advantage >= coherent_snr_advantage_threshold):
                    integration_method = 'coherent'
                    wwv_snr = coherent_wwv_snr
                    wwvh_snr = coherent_wwvh_snr
                else:
                    integration_method = 'incoherent'
                    wwv_snr = incoherent_wwv_snr
                    wwvh_snr = incoherent_wwvh_snr
                
                ratio_db = wwv_snr - wwvh_snr
                
                # Convert noise power density to dB (relative to 1.0 = 0 dB)
                # This is N₀ in dBW/Hz
                noise_power_density_db = 10 * np.log10(N0) if N0 > 0 else -100
                
                # Calculate mean phase for Doppler estimation
                wwv_mean_phase = float(np.mean(wwv_phases_unwrapped)) if len(wwv_phases) > 1 else 0.0
                wwvh_mean_phase = float(np.mean(wwvh_phases_unwrapped)) if len(wwvh_phases) > 1 else 0.0
                
                results.append({
                    'second': window_start_second,  # Actual start second (skips second 0)
                    # Best SNR (chosen method)
                    'wwv_snr_db': float(wwv_snr),
                    'wwvh_snr_db': float(wwvh_snr),
                    'ratio_db': float(ratio_db),
                    # Coherent results
                    'coherent_wwv_snr_db': float(coherent_wwv_snr),
                    'coherent_wwvh_snr_db': float(coherent_wwvh_snr),
                    # Incoherent results
                    'incoherent_wwv_snr_db': float(incoherent_wwv_snr),
                    'incoherent_wwvh_snr_db': float(incoherent_wwvh_snr),
                    # Coherence quality
                    'coherence_quality_wwv': float(wwv_coherence_quality),
                    'coherence_quality_wwvh': float(wwvh_coherence_quality),
                    # Phase for Doppler tracking (unwrapped mean)
                    'wwv_phase_rad': wwv_mean_phase,
                    'wwvh_phase_rad': wwvh_mean_phase,
                    # Integration method selection
                    'integration_method': integration_method,
                    'tick_count': valid_ticks,
                    # Noise floor for this window
                    'noise_power_density_db': float(noise_power_density_db),
                    # Signal filter bandwidth for diagnostics
                    'signal_bandwidth_hz': float(B_signal)
                })
                
                logger.info(f"{self.channel_name}: Tick window {window_idx} (sec {window_start_second}-{window_end_second-1}): "
                           f"{integration_method.upper()} - WWV={wwv_snr:.1f}dB, WWVH={wwvh_snr:.1f}dB, Ratio={ratio_db:+.1f}dB "
                           f"(coherence: WWV={wwv_coherence_quality:.2f}, WWVH={wwvh_coherence_quality:.2f}, {valid_ticks} ticks)")
            else:
                # No valid ticks in this window
                results.append({
                    'second': window_start_second,  # Actual start second (skips second 0)
                    'wwv_snr_db': -100.0,
                    'wwvh_snr_db': -100.0,
                    'ratio_db': 0.0,
                    'coherent_wwv_snr_db': -100.0,
                    'coherent_wwvh_snr_db': -100.0,
                    'incoherent_wwv_snr_db': -100.0,
                    'incoherent_wwvh_snr_db': -100.0,
                    'coherence_quality_wwv': 0.0,
                    'coherence_quality_wwvh': 0.0,
                    'integration_method': 'none',
                    'tick_count': 0,
                    'noise_power_density_db': -100.0
                })
        
        return results
    
    def estimate_doppler_shift(
        self,
        tick_results: List[Dict[str, float]]
    ) -> Optional[Dict[str, float]]:
        """
        Estimate instantaneous Doppler shift from tick phase progression.
        
        Uses phase tracking of 1000 Hz (WWV) and 1200 Hz (WWVH) tones across
        consecutive ticks to measure ionospheric Doppler shift. This determines
        the maximum coherent integration window before phase rotation degrades SNR.
        
        Args:
            tick_results: List of tick window dictionaries from detect_tick_windows()
        
        Returns:
            Dictionary with:
                - wwv_doppler_hz: Doppler shift for WWV signal (Hz)
                - wwvh_doppler_hz: Doppler shift for WWVH signal (Hz)
                - max_coherent_window_sec: Maximum window for π/4 phase error
                - doppler_quality: Confidence metric (0-1, based on fit residuals)
                - phase_variance_rad: RMS phase deviation from linear fit
            Returns None if insufficient high-SNR ticks available
        """
        if not tick_results or len(tick_results) < 10:
            return None
        
        # Extract WWV phases from high-SNR ticks (need clean phase measurements)
        wwv_phases = []
        wwvh_phases = []
        times_sec = []
        
        for i, tick in enumerate(tick_results):
            # Require high SNR for reliable phase tracking (noise doesn't dominate phase)
            if tick.get('wwv_snr_db', -100) > 10.0:
                times_sec.append(tick.get('second', i))
                wwv_phases.append(tick.get('wwv_phase_rad', 0.0))
            
            if tick.get('wwvh_snr_db', -100) > 10.0:
                if len(wwvh_phases) < len(wwv_phases):  # Keep arrays aligned
                    wwvh_phases.append(tick.get('wwvh_phase_rad', 0.0))
        
        if len(wwv_phases) < 10:
            logger.debug(f"{self.channel_name}: Insufficient high-SNR ticks for Doppler estimation")
            return None
        
        # Unwrap phase to handle 2π discontinuities
        wwv_unwrapped = np.unwrap(wwv_phases)
        
        # Linear regression: φ(t) = 2π·Δf_D·t + φ₀
        # Slope gives Doppler shift in rad/s, convert to Hz
        wwv_coeffs = np.polyfit(times_sec, wwv_unwrapped, deg=1)
        wwv_doppler_hz = wwv_coeffs[0] / (2 * np.pi)
        
        # Repeat for WWVH
        wwvh_unwrapped = np.unwrap(wwvh_phases) if len(wwvh_phases) >= 10 else wwv_unwrapped
        wwvh_coeffs = np.polyfit(times_sec, wwvh_unwrapped, deg=1) if len(wwvh_phases) >= 10 else wwv_coeffs
        wwvh_doppler_hz = wwvh_coeffs[1] / (2 * np.pi)
        
        # Calculate maximum coherent integration window
        # Limit phase error to π/4 (45°) for <3 dB coherent loss
        max_doppler = max(abs(wwv_doppler_hz), abs(wwvh_doppler_hz))
        if max_doppler > 0.001:  # Avoid division by zero
            max_coherent_window = 1.0 / (8.0 * max_doppler)
        else:
            max_coherent_window = 60.0  # Stable channel, no Doppler limit
        
        # Quality metric from phase fit residuals
        wwv_fit = np.polyval(wwv_coeffs, times_sec)
        phase_residuals = wwv_unwrapped - wwv_fit
        phase_variance = np.var(phase_residuals)
        
        # Quality: 1.0 = perfect fit, 0.0 = random phase (variance = π²/3)
        doppler_quality = max(0.0, min(1.0, 1.0 - (phase_variance / (np.pi**2 / 3))))
        
        logger.info(f"{self.channel_name}: Doppler estimate: "
                   f"WWV={wwv_doppler_hz:+.3f} Hz, WWVH={wwvh_doppler_hz:+.3f} Hz, "
                   f"max_window={max_coherent_window:.1f}s, quality={doppler_quality:.2f}")
        
        return {
            'wwv_doppler_hz': float(wwv_doppler_hz),
            'wwvh_doppler_hz': float(wwvh_doppler_hz),
            'max_coherent_window_sec': float(max_coherent_window),
            'doppler_quality': float(doppler_quality),
            'phase_variance_rad': float(np.sqrt(phase_variance))
        }
    
    def bcd_correlation_discrimination(
        self,
        iq_samples: np.ndarray,
        sample_rate: int,
        minute_timestamp: float,
        frequency_mhz: Optional[float] = None,
        window_seconds: float = 10,
        step_seconds: float = 3,
        adaptive: bool = True,
        enable_single_station_detection: bool = True
    ) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float], List[Dict[str, float]]]:
        """
        Discriminate WWV/WWVH using 100 Hz BCD cross-correlation with sliding windows
        
        Both WWV and WWVH transmit the IDENTICAL 100 Hz BCD time code simultaneously.
        By cross-correlating the received 100 Hz signal against the expected template,
        we get two peaks separated by the ionospheric differential delay (~10-20ms).
        
        DISCRIMINATION-FIRST PHILOSOPHY:
        Default uses 60-second windows (full minute) for maximum discrimination sensitivity.
        This provides √36 = 6x SNR improvement over 10-second windows (+7.8 dB), critical for
        weak signal discrimination. Temporal resolution is secondary to confident discrimination.
        
        BASELINE (60 seconds):
        - Maximizes SNR for weak signal discrimination
        - Single measurement per minute (non-overlapping)
        - Aligns with station timing (full BCD time code)
        - All 60 second-ticks available for correlation
        
        FUTURE ADAPTIVE WINDOWING:
        Once confident discrimination established (confidence >0.7 for 5+ minutes),
        system may progressively shorten windows (60→30→20→15→10 sec) to increase
        granularity while monitoring confidence. Reverts to 60 sec if confidence drops.
        
        This method completely avoids the 1000/1200 Hz time marker tone separation problem!
        The 100 Hz BCD signal is the actual carrier.
        
        Args:
            iq_samples: Full minute of complex IQ samples
            sample_rate: Sample rate in Hz (typically 16000)
            minute_timestamp: UTC timestamp of minute boundary
            frequency_mhz: Operating frequency for geographic ToA prediction (optional)
            window_seconds: Integration window length (default 10s, adjust based on conditions)
            step_seconds: Sliding step size (default 3s for efficiency)
            adaptive: Enable adaptive window recommendations (default True)
            enable_single_station_detection: Use geographic predictor for single peaks (default True)
            
        Returns:
            Tuple of (wwv_amp_mean, wwvh_amp_mean, delay_mean, quality_mean, windows_list)
            Scalar values are means across all windows; windows_list contains time-series data
            Returns (None, None, None, None, None) if correlation fails
        """
        try:
            # Step 1: Extract 100 Hz BCD tone from the combined IQ signal
            # BCD is amplitude modulation of a 100 Hz subcarrier, independent of 1000/1200 Hz ID tones
            # Both WWV and WWVH transmit the same BCD pattern on 100 Hz
            
            # Bandpass filter around 100 Hz to isolate BCD subcarrier
            nyquist = sample_rate / 2
            bcd_low_norm = 50 / nyquist   # 50-150 Hz captures 100 Hz BCD
            bcd_high_norm = 150 / nyquist
            sos_bcd = scipy_signal.butter(4, [bcd_low_norm, bcd_high_norm], 'bandpass', output='sos')
            bcd_100hz = scipy_signal.sosfilt(sos_bcd, iq_samples)
            
            # Step 2: AM demodulate the 100 Hz tone to get BCD envelope
            bcd_envelope = np.abs(bcd_100hz)
            bcd_envelope = bcd_envelope - np.mean(bcd_envelope)
            
            # Step 3: Low-pass filter to get the BCD modulation pattern
            # BCD bit rate is ~1 Hz (1 bit per second), so keep 0-5 Hz
            lp_cutoff_norm = 5 / nyquist
            sos_lp = scipy_signal.butter(4, lp_cutoff_norm, 'low', output='sos')
            bcd_signal = scipy_signal.sosfilt(sos_lp, bcd_envelope)
            
            # Step 4: Generate expected BCD template for this minute (full 60 seconds)
            bcd_template_full = self._generate_bcd_template(minute_timestamp, sample_rate)
            
            if bcd_template_full is None:
                logger.warning(f"{self.channel_name}: Failed to generate BCD template")
                return None, None, None, None, None
            
            # Step 5: Sliding window correlation to find delay AND amplitudes
            # The 100 Hz BCD signal IS the carrier - both stations transmit on 100 Hz
            # Correlation peak heights give us the individual station amplitudes
            window_samples = int(window_seconds * sample_rate)
            step_samples = int(step_seconds * sample_rate)
            
            # Calculate number of windows
            total_samples = len(bcd_signal)
            num_windows = (total_samples - window_samples) // step_samples + 1
            
            windows_data = []
            
            for i in range(num_windows):
                start_sample = int(i * step_samples)
                end_sample = int(start_sample + window_samples)
                window_start_time = start_sample / sample_rate  # Seconds into the minute
                
                # Extract BCD signal window and template
                signal_window = bcd_signal[start_sample:end_sample]
                template_window = bcd_template_full[start_sample:end_sample]
                
                # Cross-correlate to find two peaks (WWV and WWVH arrivals)
                correlation = scipy_signal.correlate(signal_window, template_window, mode='full', method='fft')
                correlation = np.abs(correlation)
                
                # Find two strongest peaks
                mean_corr = np.mean(correlation)
                std_corr = np.std(correlation)
                # Lower threshold for better sensitivity with 53-second integration
                # 1.0*std instead of 2.0*std matches tone detector sensitivity
                threshold = mean_corr + 1.0 * std_corr
                
                min_peak_distance = int(0.005 * sample_rate)  # 5ms minimum
                
                peaks, properties = scipy_signal.find_peaks(
                    correlation,
                    height=threshold,
                    distance=min_peak_distance,
                    prominence=std_corr * 0.3  # Reduced from 0.5 for better sensitivity
                )
                
                # Handle both dual-peak (both stations) and single-peak (one station) scenarios
                if len(peaks) >= 2:
                    # DUAL PEAK: Both WWV and WWVH detected
                    peak_heights = properties['peak_heights']
                    sorted_indices = np.argsort(peak_heights)[-2:]
                    sorted_indices = np.sort(sorted_indices)
                    
                    peak1_idx = sorted_indices[0]
                    peak2_idx = sorted_indices[1]
                    
                    peak1_time = peaks[peak1_idx] / sample_rate
                    peak2_time = peaks[peak2_idx] / sample_rate
                    
                    delay_ms = (peak2_time - peak1_time) * 1000
                    
                    if 5 <= delay_ms <= 30:
                        # Joint Least Squares Estimation to overcome temporal leakage
                        # At each peak, we measure: C(τ) = A_WWV*R(τ-τ_WWV) + A_WWVH*R(τ-τ_WWVH)
                        # This forms a 2x2 linear system we solve for A_WWV and A_WWVH
                        
                        # Get correlation values at both peaks
                        c_peak1 = float(peak_heights[peak1_idx])
                        c_peak2 = float(peak_heights[peak2_idx])
                        
                        # Compute template autocorrelation at delay Δτ
                        delay_samples = int(delay_ms * sample_rate / 1000)
                        
                        # R(0) = template autocorrelation at zero lag (template energy)
                        R_0 = float(np.sum(template_window**2))
                        
                        # R(Δτ) = template autocorrelation at the measured delay
                        # Shift template and compute overlap
                        if delay_samples < len(template_window):
                            R_delta = float(np.sum(template_window[:-delay_samples] * 
                                                  template_window[delay_samples:]))
                        else:
                            R_delta = 0.0
                        
                        # Set up the 2x2 system: [R(0) R(Δτ)] [A_WWV  ] = [C(τ_WWV) ]
                        #                        [R(Δτ) R(0) ] [A_WWVH]   [C(τ_WWVH)]
                        # Note: R(-Δτ) = R(Δτ) due to autocorrelation symmetry
                        
                        if R_0 > 0:
                            # Solve the linear system
                            A_matrix = np.array([[R_0, R_delta],
                                               [R_delta, R_0]])
                            b_vector = np.array([c_peak1, c_peak2])
                            
                            try:
                                amplitudes = np.linalg.solve(A_matrix, b_vector)
                                wwv_amp = float(amplitudes[0])
                                wwvh_amp = float(amplitudes[1])
                                
                                # Normalize by sqrt(template energy) for physical units
                                wwv_amp = wwv_amp / np.sqrt(R_0)
                                wwvh_amp = wwvh_amp / np.sqrt(R_0)
                            except np.linalg.LinAlgError:
                                # Matrix is singular, fall back to naive method
                                wwv_amp = c_peak1 / np.sqrt(R_0)
                                wwvh_amp = c_peak2 / np.sqrt(R_0)
                        else:
                            wwv_amp = 0.0
                            wwvh_amp = 0.0
                        
                        # Safety check for NaN/Inf values (breaks JSON)
                        if not np.isfinite(wwv_amp):
                            wwv_amp = 0.0
                        if not np.isfinite(wwvh_amp):
                            wwvh_amp = 0.0
                        
                        # Quality from correlation SNR
                        noise_floor = np.median(correlation)
                        quality = (c_peak1 + c_peak2) / (2 * noise_floor) if noise_floor > 0 else 0.0
                        
                        if not np.isfinite(quality):
                            quality = 0.0
                        
                        # Measure delay spread (τD) from correlation peak widths (FWHM)
                        # This quantifies channel multipath time spreading
                        def measure_peak_width(correlation, peak_idx, sample_rate):
                            """Measure FWHM of correlation peak in milliseconds"""
                            peak_val = correlation[peak_idx]
                            half_max = peak_val / 2.0
                            
                            # Find left edge
                            left_idx = peak_idx
                            while left_idx > 0 and correlation[left_idx] > half_max:
                                left_idx -= 1
                            
                            # Find right edge
                            right_idx = peak_idx
                            while right_idx < len(correlation) - 1 and correlation[right_idx] > half_max:
                                right_idx += 1
                            
                            # Width in samples → milliseconds
                            width_samples = right_idx - left_idx
                            width_ms = (width_samples / sample_rate) * 1000.0
                            return width_ms
                        
                        wwv_delay_spread_ms = measure_peak_width(correlation, peaks[peak1_idx], sample_rate)
                        wwvh_delay_spread_ms = measure_peak_width(correlation, peaks[peak2_idx], sample_rate)
                        
                        windows_data.append({
                            'window_start_sec': float(window_start_time),
                            'wwv_amplitude': wwv_amp,
                            'wwvh_amplitude': wwvh_amp,
                            'differential_delay_ms': float(delay_ms),
                            'correlation_quality': float(quality),
                            'detection_type': 'dual_peak',
                            # Channel characterization: delay spread from peak width
                            'wwv_delay_spread_ms': float(wwv_delay_spread_ms),
                            'wwvh_delay_spread_ms': float(wwvh_delay_spread_ms)
                        })
                        
                        # Update geographic predictor history if available
                        if self.geo_predictor and frequency_mhz:
                            # Convert peak times to absolute delays from correlation zero
                            peak1_delay_ms = peak1_time * 1000
                            peak2_delay_ms = peak2_time * 1000
                            self.geo_predictor.update_dual_peak_history(
                                frequency_mhz,
                                peak1_delay_ms, peak2_delay_ms,
                                wwv_amp, wwvh_amp
                            )
                
                elif len(peaks) == 1 and enable_single_station_detection and self.geo_predictor and frequency_mhz:
                    # SINGLE PEAK: Try to classify using geographic ToA prediction
                    peak_idx = 0
                    peak_time = peaks[peak_idx] / sample_rate
                    peak_delay_ms = peak_time * 1000
                    peak_height = float(peak_heights[peak_idx])
                    
                    # Normalize amplitude
                    R_0 = float(np.sum(template_window**2))
                    if R_0 > 0:
                        peak_amplitude = peak_height / np.sqrt(R_0)
                    else:
                        continue  # Skip if template energy is zero
                    
                    # Quality from SNR
                    noise_floor = np.median(correlation)
                    quality = peak_height / noise_floor if noise_floor > 0 else 0.0
                    
                    # Classify the single peak
                    station = self.geo_predictor.classify_single_peak(
                        peak_delay_ms, peak_amplitude, frequency_mhz, quality
                    )
                    
                    if station == 'WWV':
                        windows_data.append({
                            'window_start_sec': float(window_start_time),
                            'wwv_amplitude': peak_amplitude,
                            'wwvh_amplitude': 0.0,
                            'differential_delay_ms': None,
                            'correlation_quality': float(quality),
                            'detection_type': 'single_peak_wwv',
                            'peak_delay_ms': float(peak_delay_ms)
                        })
                    elif station == 'WWVH':
                        windows_data.append({
                            'window_start_sec': float(window_start_time),
                            'wwv_amplitude': 0.0,
                            'wwvh_amplitude': peak_amplitude,
                            'differential_delay_ms': None,
                            'correlation_quality': float(quality),
                            'detection_type': 'single_peak_wwvh',
                            'peak_delay_ms': float(peak_delay_ms)
                        })
                    # else: station is None (ambiguous/unclassified), skip this window
            
            # Step 5: Compute summary statistics from all valid windows
            if not windows_data:
                logger.info(f"{self.channel_name}: No valid BCD correlation windows detected (threshold={threshold:.1f}, mean={mean_corr:.1f}, std={std_corr:.1f})")
                return None, None, None, None, []
            
            wwv_amps = [w['wwv_amplitude'] for w in windows_data]
            wwvh_amps = [w['wwvh_amplitude'] for w in windows_data]
            delays = [w['differential_delay_ms'] for w in windows_data]
            qualities = [w['correlation_quality'] for w in windows_data]
            
            wwv_amp_mean = float(np.mean(wwv_amps))
            wwvh_amp_mean = float(np.mean(wwvh_amps))
            delay_mean = float(np.mean(delays))
            quality_mean = float(np.mean(qualities))
            
            # Adaptive windowing: Adjust window size based on signal conditions
            window_adjustment = None
            if adaptive:
                # Calculate amplitude ratio (dB)
                amp_ratio_db = 20 * np.log10(max(wwv_amp_mean, 1e-10) / max(wwvh_amp_mean, 1e-10))
                
                # Determine if one station is dominant or both are similar
                if abs(amp_ratio_db) > 10:
                    # One station is 10+ dB stronger (dominant or alone)
                    # → Tighten window for better temporal resolution
                    if window_seconds > 5:
                        window_adjustment = "tighten"
                        logger.info(f"{self.channel_name}: One station dominant ({amp_ratio_db:+.1f}dB) "
                                   f"- consider 5-second windows for better resolution")
                
                elif abs(amp_ratio_db) < 3:
                    # Stations within 3 dB (similar strength, hard to discriminate)
                    # → Expand window for better SNR discrimination
                    if window_seconds < 15:
                        window_adjustment = "expand"
                        logger.info(f"{self.channel_name}: Similar amplitudes ({amp_ratio_db:+.1f}dB) "
                                   f"- consider 15-second windows for better discrimination")
                
                # Check overall signal strength (quality)
                if quality_mean < 3.0 and window_seconds < 20:
                    # Weak signals (poor SNR)
                    # → Expand window regardless of amplitude ratio
                    window_adjustment = "expand_weak"
                    logger.info(f"{self.channel_name}: Weak signals (quality={quality_mean:.1f}) "
                               f"- consider 15-20 second windows for better SNR")
            
            logger.info(f"{self.channel_name}: BCD correlation ({len(windows_data)} windows, {window_seconds}s) - "
                       f"WWV amp={wwv_amp_mean:.1f}±{np.std(wwv_amps):.1f}, "
                       f"WWVH amp={wwvh_amp_mean:.1f}±{np.std(wwvh_amps):.1f}, "
                       f"ratio={20*np.log10(max(wwv_amp_mean,1e-10)/max(wwvh_amp_mean,1e-10)):+.1f}dB, "
                       f"delay={delay_mean:.2f}±{np.std(delays):.2f}ms, "
                       f"quality={quality_mean:.1f}")
            
            return wwv_amp_mean, wwvh_amp_mean, delay_mean, quality_mean, windows_data
            
        except Exception as e:
            logger.error(f"{self.channel_name}: BCD discrimination failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None, None, None, None, None
    
    def detect_bcd_discrimination(
        self,
        iq_samples: np.ndarray,
        sample_rate: int,
        minute_timestamp: float,
        frequency_mhz: Optional[float] = None,
        doppler_info: Optional[Dict[str, float]] = None
    ) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float], List[Dict[str, float]]]:
        """
        Wrapper method for BCD discrimination with adaptive window sizing.
        
        Calls bcd_correlation_discrimination with Doppler-adaptive window selection.
        Uses ionospheric Doppler shift to determine maximum coherent integration
        window, preventing phase rotation from degrading correlation quality.
        
        Args:
            iq_samples: Full minute of complex IQ samples
            sample_rate: Sample rate in Hz
            minute_timestamp: UTC timestamp of minute boundary
            frequency_mhz: Operating frequency for geographic ToA prediction
            doppler_info: Optional Doppler estimation from tick phase tracking
            
        Returns:
            Tuple of (wwv_amp_mean, wwvh_amp_mean, delay_mean, quality_mean, windows_list)
        """
        # Adaptive window sizing based on Doppler limits
        window_seconds = 60.0  # Default: full minute for maximum SNR
        
        if doppler_info and 'max_coherent_window_sec' in doppler_info:
            # Limit window to prevent >π/4 phase rotation
            doppler_limit = doppler_info['max_coherent_window_sec']
            if doppler_limit < 60.0:
                window_seconds = max(10.0, min(doppler_limit, 60.0))  # Clamp to [10, 60] sec
                logger.info(f"{self.channel_name}: Doppler-limited BCD window to {window_seconds:.1f}s "
                           f"(Δf_D={doppler_info['wwv_doppler_hz']:+.3f} Hz, "
                           f"quality={doppler_info['doppler_quality']:.2f})")
        
        return self.bcd_correlation_discrimination(
            iq_samples=iq_samples,
            sample_rate=sample_rate,
            minute_timestamp=minute_timestamp,
            frequency_mhz=frequency_mhz,
            window_seconds=window_seconds,  # Doppler-adaptive!
            step_seconds=min(window_seconds, 60),  # Non-overlapping
            adaptive=False,  # Doppler adaptation replaces old adaptive logic
            enable_single_station_detection=True
        )
    
    def _generate_bcd_template(
        self,
        minute_timestamp: float,
        sample_rate: int
    ) -> Optional[np.ndarray]:
        """
        Generate expected 100 Hz BCD template for a given UTC minute
        
        Uses the WWVBCDEncoder to generate an accurate template based on
        Phil Karn's wwvsim.c implementation.
        
        Args:
            minute_timestamp: UTC timestamp of minute boundary
            sample_rate: Sample rate in Hz
            
        Returns:
            60-second BCD template as numpy array, or None if generation fails
        """
        try:
            # Use the encoder instance that was created during __init__
            template = self.bcd_encoder.encode_minute(minute_timestamp)
            return template
            
        except Exception as e:
            logger.error(f"{self.channel_name}: Failed to generate BCD template: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def analyze_minute_with_440hz(
        self,
        iq_samples: np.ndarray,
        sample_rate: int,
        minute_timestamp: float,
        frequency_mhz: Optional[float] = None,
        detections: Optional[List[ToneDetectionResult]] = None
    ) -> Optional[DiscriminationResult]:
        """
        Complete discrimination analysis including all methods - FULLY INDEPENDENT
        
        This method now detects timing tones directly from IQ samples, making it
        fully reprocessable from archived data without external dependencies.
        
        Args:
            iq_samples: Full minute of IQ samples (typically 16 kHz, 60 seconds)
            sample_rate: Sample rate in Hz
            minute_timestamp: UTC timestamp of minute boundary
            frequency_mhz: Operating frequency for geographic ToA prediction (optional)
            detections: DEPRECATED - Optional external tone detections (for backward compatibility).
                       If None, will detect tones internally using detect_timing_tones().
            
        Returns:
            Enhanced DiscriminationResult with all discrimination methods
        """
        # PHASE 1: Detect timing tones (800ms WWV/WWVH tones)
        # If detections not provided, detect them from IQ samples (NEW: fully independent)
        if detections is None or len(detections) == 0:
            logger.debug(f"{self.channel_name}: No external detections provided, detecting tones from IQ data")
            wwv_power_db, wwvh_power_db, differential_delay_ms, detections = self.detect_timing_tones(
                iq_samples, sample_rate, minute_timestamp
            )
            # Create result directly from detected values
            result = self.compute_discrimination(detections, minute_timestamp)
        else:
            # Legacy path: use provided detections
            logger.debug(f"{self.channel_name}: Using {len(detections)} external tone detections")
            result = self.compute_discrimination(detections, minute_timestamp)
        
        if result is None:
            return None
        
        # Get minute number (0-59)
        dt = datetime.utcfromtimestamp(minute_timestamp)
        minute_number = dt.minute
        
        # PHASE 2: Detect 440 Hz station ID tone (minutes 1 & 2 only)
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
        
        # PHASE 3: Detect 5ms tick marks with coherent integration (60-second baseline)
        # DISCRIMINATION-FIRST: Use full minute for maximum tick stacking sensitivity
        try:
            tick_windows = self.detect_tick_windows(iq_samples, sample_rate, window_seconds=60)
            result.tick_windows_10sec = tick_windows  # Field name unchanged for compatibility
            
            # Log summary with coherent integration statistics
            good_windows = [w for w in tick_windows if w['wwv_snr_db'] > 0 or w['wwvh_snr_db'] > 0]
            if good_windows:
                coherent_count = sum(1 for w in good_windows if w.get('integration_method') == 'coherent')
                avg_ratio = np.mean([w['ratio_db'] for w in good_windows])
                avg_coherence_wwv = np.mean([w.get('coherence_quality_wwv', 0) for w in good_windows])
                avg_coherence_wwvh = np.mean([w.get('coherence_quality_wwvh', 0) for w in good_windows])
                
                logger.info(f"{self.channel_name}: Tick analysis - {len(good_windows)}/{len(tick_windows)} windows valid, "
                           f"{coherent_count}/{len(good_windows)} coherent, avg ratio: {avg_ratio:+.1f}dB, "
                           f"coherence: WWV={avg_coherence_wwv:.2f} WWVH={avg_coherence_wwvh:.2f}")
        except Exception as e:
            logger.warning(f"{self.channel_name}: Tick detection failed: {e}")
            result.tick_windows_10sec = []
        
        # PHASE 3.5: Estimate Doppler shift from tick phase progression
        # This determines maximum coherent integration window for BCD analysis
        doppler_info = None
        if result.tick_windows_10sec:
            try:
                doppler_info = self.estimate_doppler_shift(result.tick_windows_10sec)
            except Exception as e:
                logger.debug(f"{self.channel_name}: Doppler estimation failed: {e}")
        
        # PHASE 4: BCD discrimination using 100 Hz subcarrier analysis
        # Adaptive window sizing based on Doppler limits
        # Amplitudes measured directly from 100 Hz BCD signal correlation peaks
        # Delay spread measurement quantifies channel multipath (complements Doppler spread)
        try:
            bcd_wwv, bcd_wwvh, bcd_delay, bcd_quality, bcd_windows = self.detect_bcd_discrimination(
                iq_samples, sample_rate, minute_timestamp, frequency_mhz, doppler_info
            )
            
            # Log 440 Hz reference measurements when available (hourly calibration anchor)
            # 440 Hz provides harmonic-free reference (WWV minute 2, WWVH minute 1)
            if minute_number == 1 and result.tone_440hz_wwvh_detected and result.tone_440hz_wwvh_power_db:
                logger.debug(f"{self.channel_name}: 440 Hz WWVH reference: {result.tone_440hz_wwvh_power_db:.1f} dB")
            elif minute_number == 2 and result.tone_440hz_wwv_detected and result.tone_440hz_wwv_power_db:
                logger.debug(f"{self.channel_name}: 440 Hz WWV reference: {result.tone_440hz_wwv_power_db:.1f} dB")
            
            result.bcd_wwv_amplitude = bcd_wwv
            result.bcd_wwvh_amplitude = bcd_wwvh
            result.bcd_differential_delay_ms = bcd_delay
            result.bcd_correlation_quality = bcd_quality
            result.bcd_windows = bcd_windows  # Time-series data (~50 windows/minute with 1s steps)
                    
        except Exception as e:
            logger.warning(f"{self.channel_name}: BCD discrimination failed: {e}")
            result.bcd_wwv_amplitude = None
            result.bcd_wwvh_amplitude = None
            result.bcd_differential_delay_ms = None
            result.bcd_correlation_quality = None
            result.bcd_windows = None
        
        # PHASE 4.5: Test Signal Discrimination (minutes 8 and 44 only)
        # Scientific modulation test provides strongest discrimination when present
        # Minute 8 = WWV, Minute 44 = WWVH
        if minute_number in [8, 44]:
            try:
                test_detection = self.test_signal_detector.detect(
                    iq_samples, minute_number, sample_rate
                )
                
                result.test_signal_detected = test_detection.detected
                result.test_signal_station = test_detection.station
                result.test_signal_confidence = test_detection.confidence
                result.test_signal_multitone_score = test_detection.multitone_score
                result.test_signal_chirp_score = test_detection.chirp_score
                result.test_signal_snr_db = test_detection.snr_db
                
                if test_detection.detected:
                    logger.info(f"{self.channel_name}: ✨ Test signal detected! "
                               f"Station={test_detection.station}, "
                               f"confidence={test_detection.confidence:.3f}, "
                               f"SNR={test_detection.snr_db:.1f}dB")
                    
                    # High-confidence test signal overrides other methods
                    if test_detection.confidence > 0.7:
                        result.dominant_station = test_detection.station
                        result.confidence = 'high'
                        logger.info(f"{self.channel_name}: Test signal confidence high, "
                                   f"overriding other discriminators → {test_detection.station}")
                        
            except Exception as e:
                logger.warning(f"{self.channel_name}: Test signal detection failed: {e}")
        
        # PHASE 5: Finalize discrimination with weighted voting combiner
        result = self.finalize_discrimination(
            result=result,
            minute_number=minute_number,
            bcd_wwv_amp=result.bcd_wwv_amplitude,
            bcd_wwvh_amp=result.bcd_wwvh_amplitude,
            tone_440_wwv_detected=result.tone_440hz_wwv_detected,
            tone_440_wwvh_detected=result.tone_440hz_wwvh_detected,
            tick_results=result.tick_windows_10sec
        )
        
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


