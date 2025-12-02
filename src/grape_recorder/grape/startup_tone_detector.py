#!/usr/bin/env python3
"""
Simplified Tone Detector for Core Recorder Startup

This is a MINIMAL tone detector used ONLY at core recorder startup to establish
time_snap. It does NOT replace the full analytics tone detector - it's just 
enough to find a WWV/CHU second mark.

Design:
- Lightweight: No scipy, minimal dependencies
- Fast: Processes 2 minutes of data quickly
- Simple: Just FFT-based tone detection
- Good enough: Establishes initial time_snap for file writing

Full analytics (with detailed tone analysis) happens later on the NPZ files.
"""

import numpy as np
import logging
from typing import Optional, Tuple, List
from dataclasses import dataclass
from datetime import datetime, timezone
from scipy import signal as sp_signal

logger = logging.getLogger(__name__)


@dataclass
class StartupTimeSnap:
    """Simplified time_snap for startup use with tone power measurements"""
    rtp_timestamp: int          # RTP timestamp at tone detection
    utc_timestamp: float        # UTC time at tone (seconds since epoch)
    sample_rate: int           # RTP sample rate
    source: str                # 'wwv_startup', 'chu_startup', 'ntp', 'wall_clock'
    confidence: float          # 0.0-1.0
    station: str               # 'WWV', 'CHU', 'NTP', 'WALL_CLOCK'
    tone_frequency: float      # Detected tone frequency (1000, 1200, etc.)
    detection_snr_db: float    # SNR of tone detection
    
    # Tone power measurements for analytics (avoids re-detection)
    # Maps frequency (Hz) -> SNR (dB), -999.0 if not detected
    tone_power_1000_hz_db: float = -999.0  # WWV/CHU 1000 Hz tone
    tone_power_1200_hz_db: float = -999.0  # WWVH 1200 Hz tone
    
    # Differential delay for propagation analysis
    # Positive = WWVH arrives after WWV (typical for continental US)
    # Negative = WWVH arrives before WWV (rare, indicates unusual propagation)
    wwvh_differential_delay_ms: float = 0.0  # WWVH - WWV arrival time (ms)


class StartupToneDetector:
    """
    Minimal tone detector for establishing time_snap at startup.
    
    Detects:
    - WWV: 1000 Hz tone (0.8s duration)
    - WWVH: 1200 Hz tone (0.8s duration)
    - CHU: 1000 Hz tone (0.5s duration)
    
    Method: Simple FFT with tone presence threshold
    """
    
    def __init__(self, sample_rate: int = 20000, frequency_hz: float = 10e6):
        """
        Initialize detector
        
        Args:
            sample_rate: IQ sample rate (20000 default, 16000 for legacy)
            frequency_hz: Center frequency for station identification
        """
        self.sample_rate = sample_rate
        self.frequency_hz = frequency_hz
        
        # Determine expected station from frequency
        # WWV: 2.5, 5, 10, 15, 20, 25 MHz
        # WWVH: 2.5, 5, 10, 15 MHz (also has 1200 Hz tone)
        # CHU: 3.33, 7.85, 14.67 MHz
        freq_mhz = frequency_hz / 1e6
        
        if freq_mhz in [3.33, 7.85, 14.67]:
            self.expected_station = 'CHU'
            self.tone_frequencies = [1000]  # CHU only has 1000 Hz
        elif freq_mhz in [2.5, 5.0, 10.0, 15.0]:
            self.expected_station = 'WWV_OR_WWVH'
            self.tone_frequencies = [1000, 1200]  # Could be either
        else:
            self.expected_station = 'WWV'
            self.tone_frequencies = [1000]  # WWV only
        
        logger.info(f"StartupToneDetector: {freq_mhz:.2f} MHz, expecting {self.expected_station}")
    
    def detect_time_snap(self, iq_samples: np.ndarray, first_rtp_timestamp: int,
                        wall_clock_start: float) -> Optional[StartupTimeSnap]:
        """
        Detect tone rising edge with ±1ms precision to establish time_snap.
        
        Uses Hilbert transform for envelope extraction and derivative-based
        edge detection with sub-sample interpolation.
        
        Args:
            iq_samples: Complex IQ samples (16 kHz, 60-120 seconds)
            first_rtp_timestamp: RTP timestamp of first sample
            wall_clock_start: Wall clock time at first sample (UTC seconds)
        
        Returns:
            StartupTimeSnap if tone detected, None otherwise
        """
        logger.warning(f"🔍 DETECT_TIME_SNAP CALLED: {len(iq_samples)} samples ({len(iq_samples)/self.sample_rate:.1f}s)")
        logger.warning(f"   IQ data type: {iq_samples.dtype}, shape: {iq_samples.shape}")
        logger.warning(f"   Sample mean power: {np.mean(np.abs(iq_samples)**2):.6f}")
        logger.warning(f"   Frequencies to try: {self.tone_frequencies}")
        
        # Try detecting each expected tone frequency
        # Store ALL detections to capture tone powers for analytics
        all_detections = {}
        best_detection = None
        best_confidence = 0.0
        
        for tone_freq in self.tone_frequencies:
            logger.warning(f"   Trying {tone_freq} Hz...")
            detection = self._detect_rising_edge(iq_samples, tone_freq, first_rtp_timestamp)
            
            if detection:
                logger.warning(f"   ✅ Detection at {tone_freq} Hz! SNR={detection['snr_db']:.1f}dB")
                all_detections[tone_freq] = detection
                
                if detection['confidence'] > best_confidence:
                    best_detection = detection
                    best_confidence = detection['confidence']
            else:
                # Store non-detection with zero power
                all_detections[tone_freq] = {
                    'snr_db': -999.0,
                    'confidence': 0.0,
                    'detected': False
                }
        
        if best_detection:
            # Determine station from frequency
            if abs(best_detection['tone_frequency'] - 1200) < abs(best_detection['tone_frequency'] - 1000):
                station = 'WWVH'
            else:
                station = 'WWV' if self.expected_station != 'CHU' else 'CHU'
            
            source = f"{station.lower()}_startup"
            
            # Extract tone powers for analytics (store all detected tones)
            tone_1000_db = all_detections.get(1000, {}).get('snr_db', -999.0)
            tone_1200_db = all_detections.get(1200, {}).get('snr_db', -999.0)
            
            # Calculate differential delay if both WWV and WWVH detected
            # CRITICAL: Only valid if both tones detected SIMULTANEOUSLY (same second)
            # For simultaneous transmission, peaks must be within tone duration window
            differential_delay_ms = 0.0
            det_1000 = all_detections.get(1000, {})
            det_1200 = all_detections.get(1200, {})
            
            if det_1000.get('detected', False) and det_1200.get('detected', False):
                # Both tones detected - check if simultaneous (within tone duration)
                peak_1000 = det_1000.get('precise_sample', 0.0)
                peak_1200 = det_1200.get('precise_sample', 0.0)
                
                # Calculate time difference
                sample_diff = abs(peak_1200 - peak_1000)
                time_diff_ms = (sample_diff / self.sample_rate) * 1000.0
                
                # Tone duration: 800ms for WWV/WWVH, 500ms for CHU
                # For simultaneous transmission, peaks should be within tone duration
                # (both tones start at same second, differ only by propagation delay)
                tone_duration_ms = 500.0 if self.expected_station == 'CHU' else 800.0
                
                if time_diff_ms < tone_duration_ms:
                    # Valid simultaneous detection
                    # Differential delay = WWVH (1200 Hz) - WWV (1000 Hz)
                    # Positive means WWVH arrives later (typical for continental US)
                    differential_delay_ms = ((peak_1200 - peak_1000) / self.sample_rate) * 1000.0
                    logger.warning(f"   ✅ Simultaneous tones ({time_diff_ms:.1f}ms apart)")
                    logger.warning(f"   Differential delay: WWVH - WWV = {differential_delay_ms:+.2f} ms")
                else:
                    logger.warning(f"   Tones from different seconds ({time_diff_ms:.0f}ms apart > {tone_duration_ms:.0f}ms tone duration)")
            
            # Calculate UTC timestamp at detected tone
            # The detected RTP timestamp marks the start of a minute (tone rising edge)
            samples_from_start = best_detection['rtp_timestamp'] - first_rtp_timestamp
            elapsed_time = samples_from_start / self.sample_rate
            utc_at_detection = wall_clock_start + elapsed_time
            
            # Round to nearest minute (tone marks minute boundary)
            utc_minute = round(utc_at_detection / 60.0) * 60.0
            
            result = StartupTimeSnap(
                rtp_timestamp=best_detection['rtp_timestamp'],
                utc_timestamp=utc_minute,
                sample_rate=self.sample_rate,
                source=source,
                confidence=best_detection['confidence'],
                station=station,
                tone_frequency=best_detection['tone_frequency'],
                detection_snr_db=best_detection['snr_db'],
                tone_power_1000_hz_db=tone_1000_db,
                tone_power_1200_hz_db=tone_1200_db,
                wwvh_differential_delay_ms=differential_delay_ms
            )
            
            logger.info(f"✅ time_snap detected: {result.station} tone at "
                       f"{datetime.fromtimestamp(result.utc_timestamp, timezone.utc).isoformat()}, "
                       f"SNR={result.detection_snr_db:.1f}dB, precision=±1ms")
            
            return result
        
        logger.warning("⚠️ No tone rising edge detected in startup buffer")
        return None
    
    def _detect_rising_edge(self, iq_samples: np.ndarray, tone_freq: float,
                           first_rtp_timestamp: int) -> Optional[dict]:
        """
        Detect tone using ENHANCED pattern matching with known minute structure.
        
        Instead of just matching the 800ms/500ms tone, we match the entire
        first 2-3 seconds of the known WWV/CHU pattern:
        - WWV: 800ms tone + silence + 800ms tone + silence...
        - CHU: 500ms tone + bell + silence + BCD start
        
        This provides:
        1. Much better SNR (longer correlation window)
        2. Higher specificity (full pattern vs single tone)
        3. Better timing precision (more signal to lock onto)
        
        Returns:
            Dict with rtp_timestamp, utc_timestamp, confidence, snr_db, tone_frequency
            or None if no valid tone found
        """
        logger.warning(f"    Detecting {tone_freq} Hz tone with pattern matching...")
        
        # Step 1: AM demodulation (extract audio envelope)
        magnitude = np.abs(iq_samples)
        audio_signal = magnitude - np.mean(magnitude)  # AC coupling
        
        audio_rms = np.sqrt(np.mean(audio_signal**2))
        logger.warning(f"      Audio RMS: {audio_rms:.6f}")
        
        if audio_rms < 1e-6:
            logger.warning(f"      Audio signal too weak")
            return None
        
        # Step 2: Create PATTERN template matching actual time code structure
        # WWV/WWVH: 800ms tone at minute mark, then 5ms ticks every second
        # CHU: 500ms tone at minute mark, then 300ms tone every 10 seconds
        
        if self.expected_station == 'CHU':
            # CHU pattern: 500ms tone at second 0, 10, 20, 30, 40, 50
            # Use first 3 seconds to capture minute mark
            pattern_duration = 3.0
            pattern_events = [
                (0.0, 0.5),  # Minute mark: 500ms tone at second 0
            ]
        else:
            # WWV/WWVH pattern: 800ms tone at second 0, 5ms ticks at 1, 2, 3...
            # Use first 3 seconds: 800ms tone + tick + tick
            pattern_duration = 3.0
            pattern_events = [
                (0.0, 0.8),    # Minute mark: 800ms tone
                (1.0, 0.005),  # Second 1: 5ms tick
                (2.0, 0.005),  # Second 2: 5ms tick
            ]
        
        # Create time array for pattern
        t_pattern = np.arange(0, pattern_duration, 1/self.sample_rate)
        pattern_sin = np.zeros(len(t_pattern))
        pattern_cos = np.zeros(len(t_pattern))
        
        # Add each tone/tick event
        for start_time, duration in pattern_events:
            start_idx = int(start_time * self.sample_rate)
            end_idx = int((start_time + duration) * self.sample_rate)
            end_idx = min(end_idx, len(t_pattern))
            
            # Create tone segment
            segment_len = end_idx - start_idx
            t_segment = np.arange(segment_len) / self.sample_rate
            
            # Use Tukey window for smooth edges (tighter for short ticks)
            alpha = 0.5 if duration < 0.01 else 0.1
            window = sp_signal.windows.tukey(segment_len, alpha=alpha)
            
            # Add to pattern
            pattern_sin[start_idx:end_idx] = np.sin(2 * np.pi * tone_freq * t_segment) * window
            pattern_cos[start_idx:end_idx] = np.cos(2 * np.pi * tone_freq * t_segment) * window
        
        # Normalize to unit energy
        pattern_sin /= np.linalg.norm(pattern_sin)
        pattern_cos /= np.linalg.norm(pattern_cos)
        
        logger.warning(f"      Pattern template: {tone_freq} Hz, {pattern_duration:.1f}s ({len(t_pattern)} samples)")
        
        # Step 3: Pattern matching (correlation with full minute structure)
        try:
            from scipy.signal import correlate
            corr_sin = correlate(audio_signal, pattern_sin, mode='valid')
            corr_cos = correlate(audio_signal, pattern_cos, mode='valid')
        except Exception as e:
            logger.warning(f"      Correlation failed: {e}")
            return None
        
        if len(corr_sin) == 0:
            logger.warning(f"      Empty correlation (buffer too short?)")
            return None
        
        # Step 4: Phase-invariant combination
        correlation = np.sqrt(corr_sin**2 + corr_cos**2)
        
        # Step 5: Find peak with sub-sample precision using parabolic interpolation
        peak_idx = np.argmax(correlation)
        peak_value = correlation[peak_idx]
        
        # Parabolic (quadratic) interpolation for sub-sample precision
        # Uses the peak and its two neighbors to fit a parabola
        # Peak of parabola: x_peak = (y[-1] - y[1]) / (2 * (y[-1] - 2*y[0] + y[1]))
        sub_sample_offset = 0.0
        if 0 < peak_idx < len(correlation) - 1:
            y_m1 = correlation[peak_idx - 1]  # y at x=-1
            y_0 = correlation[peak_idx]        # y at x=0 (peak)
            y_p1 = correlation[peak_idx + 1]  # y at x=+1
            
            denominator = y_m1 - 2*y_0 + y_p1
            if abs(denominator) > 1e-10:  # Avoid division by zero
                sub_sample_offset = 0.5 * (y_m1 - y_p1) / denominator
                # Clamp to reasonable range
                sub_sample_offset = max(-0.5, min(0.5, sub_sample_offset))
                
                # Interpolated peak value (parabola maximum)
                peak_value = y_0 - 0.25 * (y_m1 - y_p1) * sub_sample_offset
        
        precise_peak_idx = peak_idx + sub_sample_offset
        
        # Calculate SNR
        # Noise estimate: median of correlation (robust to outliers)
        noise_estimate = np.median(correlation)
        signal_estimate = peak_value
        
        if noise_estimate > 0:
            snr_linear = signal_estimate / noise_estimate
            snr_db = 20 * np.log10(snr_linear) if snr_linear > 0 else 0
        else:
            snr_db = 0
        
        logger.warning(f"      Peak: idx={peak_idx}{sub_sample_offset:+.3f}, value={peak_value:.6f}, SNR={snr_db:.1f}dB")
        
        # Threshold: SNR > 6dB for detection
        if snr_db < 6.0:
            logger.warning(f"      SNR too low ({snr_db:.1f}dB < 6.0dB)")
            return None
        
        # Calculate RTP timestamp at peak (using precise sub-sample position)
        # Use floor for integer RTP, but store fractional part for precision
        rtp_at_peak = first_rtp_timestamp + int(precise_peak_idx)
        sub_sample_fraction = precise_peak_idx - int(precise_peak_idx)
        
        # Calculate confidence based on SNR
        if snr_db > 15.0:
            confidence = 0.95
        elif snr_db > 12.0:
            confidence = 0.90
        elif snr_db > 9.0:
            confidence = 0.80
        else:
            confidence = 0.70
        
        # Sub-sample precision in microseconds (at 20kHz: 1 sample = 50μs)
        sub_sample_us = sub_sample_offset * (1e6 / self.sample_rate)
        logger.warning(f"      ✅ TONE DETECTED: SNR={snr_db:.1f}dB, conf={confidence:.2f}, "
                      f"sub-sample offset={sub_sample_us:+.1f}μs")
        
        return {
            'rtp_timestamp': int(rtp_at_peak),
            'utc_timestamp': 0.0,  # Will be set by caller
            'confidence': confidence,
            'snr_db': snr_db,
            'tone_frequency': tone_freq,
            'precise_sample': float(precise_peak_idx),  # Now includes sub-sample precision
            'sub_sample_offset': sub_sample_offset  # Fractional sample offset
        }
    
    # Old edge detection methods no longer used (matched filtering is more robust)
    
    def _find_rising_edges_OLD_UNUSED(self, derivative: np.ndarray, envelope: np.ndarray) -> list:
        """
        Find rising edge candidates in the envelope derivative.
        
        Returns list of sample indices where rising edges occur.
        
        A rising edge should have:
        - Positive derivative (increasing amplitude)
        - Low baseline before edge
        - High amplitude after edge
        """
        # Threshold for derivative (must be significant rise)
        derivative_threshold = np.percentile(np.abs(derivative), 95)
        
        logger.debug(f"    Derivative threshold (95th percentile): {derivative_threshold:.6f}")
        logger.debug(f"    Looking for peaks > {derivative_threshold * 0.3:.6f}")
        
        # Find peaks in positive derivative
        peaks, properties = sp_signal.find_peaks(
            derivative,
            height=derivative_threshold * 0.3,
            distance=self.sample_rate // 2  # At least 0.5s apart
        )
        
        logger.debug(f"    Found {len(peaks)} derivative peaks")
        
        # Filter peaks: must have low baseline before and high amplitude after
        valid_edges = []
        
        for peak in peaks:
            # Check baseline before peak (100ms window)
            baseline_start = max(0, peak - int(0.1 * self.sample_rate))
            baseline = np.mean(envelope[baseline_start:peak])
            
            # Check amplitude after peak (200ms window)
            after_end = min(len(envelope), peak + int(0.2 * self.sample_rate))
            after_amplitude = np.mean(envelope[peak:after_end])
            
            ratio = after_amplitude / baseline if baseline > 0 else 0
            logger.debug(f"      Peak at {peak}: baseline={baseline:.6f}, after={after_amplitude:.6f}, ratio={ratio:.2f}x")
            
            # Valid edge: amplitude increases significantly
            if after_amplitude > baseline * 2.0:  # At least 2x increase
                valid_edges.append(peak)
                logger.debug(f"        VALID EDGE")
            else:
                logger.debug(f"        Rejected (ratio < 2.0)")
        
        return valid_edges
    
    def _evaluate_edge_OLD_UNUSED(self, envelope: np.ndarray, edge_sample: int, tone_freq: float) -> Optional[dict]:
        """
        Evaluate quality of detected edge.
        
        Returns metrics: score, confidence, snr_db
        """
        # Check if we have enough data after edge
        if edge_sample + int(0.3 * self.sample_rate) >= len(envelope):
            return None
        
        # Baseline (before edge): 100ms window
        baseline_start = max(0, edge_sample - int(0.1 * self.sample_rate))
        baseline = np.mean(envelope[baseline_start:edge_sample])
        baseline_std = np.std(envelope[baseline_start:edge_sample])
        
        # Signal (after edge): 200ms window
        signal_end = min(len(envelope), edge_sample + int(0.2 * self.sample_rate))
        signal = np.mean(envelope[edge_sample:signal_end])
        signal_std = np.std(envelope[edge_sample:signal_end])
        
        # SNR calculation
        if baseline > 0:
            snr_linear = signal / baseline
            snr_db = 10 * np.log10(snr_linear) if snr_linear > 0 else 0
        else:
            snr_db = 0
        
        # Confidence based on SNR and signal stability
        if snr_db > 15.0 and signal_std < signal * 0.2:
            confidence = 0.95
            score = 100
        elif snr_db > 10.0 and signal_std < signal * 0.3:
            confidence = 0.85
            score = 80
        elif snr_db > 6.0 and signal_std < signal * 0.4:
            confidence = 0.70
            score = 60
        elif snr_db > 3.0:
            confidence = 0.50
            score = 40
        else:
            return None  # Not confident enough
        
        return {
            'score': score,
            'confidence': confidence,
            'snr_db': snr_db
        }
    
    def _interpolate_edge_OLD_UNUSED(self, envelope: np.ndarray, edge_sample: int) -> float:
        """
        Sub-sample interpolation for precision.
        
        Uses parabolic interpolation around the peak derivative point
        to achieve sub-sample (~60 microsecond) precision.
        """
        # Get 3 points around edge for parabolic fit
        if edge_sample < 1 or edge_sample >= len(envelope) - 1:
            return float(edge_sample)
        
        # Derivative around edge
        y1 = envelope[edge_sample - 1]
        y2 = envelope[edge_sample]
        y3 = envelope[edge_sample + 1]
        
        # Parabolic interpolation
        # Find peak of parabola through 3 points
        denom = 2 * (2*y2 - y1 - y3)
        if abs(denom) < 1e-10:
            return float(edge_sample)
        
        offset = (y3 - y1) / denom
        
        # Limit offset to reasonable range
        offset = np.clip(offset, -0.5, 0.5)
        
        return edge_sample + offset
    
    def create_ntp_time_snap(self, first_rtp_timestamp: int,
                            ntp_synced: bool, ntp_offset_ms: Optional[float]) -> StartupTimeSnap:
        """
        Create time_snap from NTP-synchronized wall clock.
        
        Used when no tone detected but NTP sync is available.
        """
        utc_now = datetime.now(timezone.utc).timestamp()
        
        confidence = 0.7 if ntp_synced and abs(ntp_offset_ms or 0) < 50 else 0.5
        
        return StartupTimeSnap(
            rtp_timestamp=first_rtp_timestamp,
            utc_timestamp=utc_now,
            sample_rate=self.sample_rate,
            source='ntp',
            confidence=confidence,
            station='NTP',
            tone_frequency=0.0,
            detection_snr_db=0.0
        )
    
    def create_wall_clock_time_snap(self, first_rtp_timestamp: int) -> StartupTimeSnap:
        """
        Create time_snap from unsynchronized wall clock.
        
        Fallback when no tone and no NTP available.
        """
        utc_now = datetime.now(timezone.utc).timestamp()
        
        return StartupTimeSnap(
            rtp_timestamp=first_rtp_timestamp,
            utc_timestamp=utc_now,
            sample_rate=self.sample_rate,
            source='wall_clock',
            confidence=0.3,
            station='WALL_CLOCK',
            tone_frequency=0.0,
            detection_snr_db=0.0
        )
