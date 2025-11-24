#!/usr/bin/env python3
"""
WWV/WWVH Scientific Test Signal Generator and Detector

Generates and detects the scientific modulation test signal transmitted at:
- Minute 8 (WWV at Fort Collins, CO)
- Minute 44 (WWVH at Kauai, HI)

Signal designed by WWV/H Scientific Modulation Working Group.
Reference: hamsci.org/wwv

Signal structure (45 seconds total):
1. Voice announcement (10s) - "What follows is a scientific modulation test..."
2. Gaussian white noise (2s) - synchronization
3. Blank time (1s)
4. Phase-coherent multi-tone (10s) - 2, 3, 4, 5 kHz with 3dB attenuation steps
5. Blank time (1s)
6. Chirp sequences (8s) - linear up/down chirps, short and long
7. Blank time (2s)
8. Single-cycle bursts (2s) - 2.5 kHz and 5 kHz timing marks
9. Blank time (1s)
10. Gaussian white noise (2s) - repeated for synchronization
11. Blank time (3s)

This implementation focuses on the most distinctive features for discrimination:
- Multi-tone with attenuation pattern (strongest discriminator)
- Chirp sequences (confirmatory)
- White noise bookends (for alignment)
"""

import numpy as np
import logging
from typing import Tuple, Optional, Dict
from scipy import signal
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TestSignalDetection:
    """Results from test signal detection"""
    detected: bool
    confidence: float  # 0.0 to 1.0
    station: Optional[str]  # 'WWV' or 'WWVH'
    minute_number: int
    
    # Feature-specific scores
    multitone_score: float = 0.0
    chirp_score: float = 0.0
    noise_correlation: float = 0.0
    
    # Timing information
    signal_start_time: Optional[float] = None
    snr_db: Optional[float] = None


class WWVTestSignalGenerator:
    """
    Generate WWV/WWVH scientific test signal
    
    This is a deterministic signal that can be generated at any sample rate
    for template matching and discrimination purposes.
    """
    
    def __init__(self, sample_rate: int = 16000):
        """
        Initialize test signal generator
        
        Args:
            sample_rate: Sample rate in Hz (typically 16000 for WWV/WWVH analysis)
        """
        self.sample_rate = sample_rate
        self.dt = 1.0 / sample_rate
        
    def generate_white_noise(self, duration_sec: float, seed: Optional[int] = None) -> np.ndarray:
        """
        Generate Gaussian white noise segment
        
        Args:
            duration_sec: Duration in seconds
            seed: Random seed for reproducibility (optional)
            
        Returns:
            Normalized white noise array
        """
        if seed is not None:
            np.random.seed(seed)
        
        num_samples = int(duration_sec * self.sample_rate)
        noise = np.random.randn(num_samples)
        
        # Normalize to prevent clipping
        noise = noise / np.max(np.abs(noise))
        
        return noise
    
    def generate_multitone(self, duration_sec: float = 10.0) -> np.ndarray:
        """
        Generate phase-coherent multi-tone sequence with 3dB attenuation steps
        
        This is the most distinctive feature of the test signal:
        - Four tones: 2, 3, 4, 5 kHz
        - All phase-locked (coherent)
        - 1 second at each attenuation level
        - Starts at -12 dB (0.25 amplitude), attenuates by 3 dB 9 times
        
        Args:
            duration_sec: Total duration (default 10s for 10 attenuation steps)
            
        Returns:
            Multi-tone signal array
        """
        t = np.arange(0, 1.0, self.dt)  # 1 second segments
        
        # Generate four phase-locked tones
        tone_2k = np.cos(2 * np.pi * 2000 * t)
        tone_3k = np.cos(2 * np.pi * 3000 * t)
        tone_4k = np.cos(2 * np.pi * 4000 * t)
        tone_5k = np.cos(2 * np.pi * 5000 * t)
        
        # Sum and scale to prevent clipping
        tone_sum = tone_2k + tone_3k + tone_4k + tone_5k
        tone_1sec = 0.25 * tone_sum  # Start at -12 dB
        
        # Create attenuation sequence: 10 steps of 3 dB
        multitone = tone_1sec.copy()
        current_level = tone_1sec
        
        for i in range(9):  # 9 more attenuation steps
            current_level = current_level / np.sqrt(2)  # -3 dB
            multitone = np.concatenate([multitone, current_level])
        
        return multitone
    
    def generate_chirp_sequence(self) -> np.ndarray:
        """
        Generate chirp sequence: short and long up/down chirps
        
        Sequence:
        - 3 short up-chirps (0.05s each, 0-5 kHz, TBW=250)
        - 3 short down-chirps
        - 0.5s blank
        - 3 long up-chirps (1.0s each, 0-5 kHz, TBW=5000)
        - 3 long down-chirps
        - 0.1s gaps between chirps
        
        Total: ~8 seconds
        
        Returns:
            Chirp sequence array
        """
        short_duration = 0.05
        long_duration = 1.0
        gap_duration = 0.1
        
        # Short chirps
        t_short = np.arange(0, short_duration, self.dt)
        short_up = signal.chirp(t_short, 0, short_duration, 5000, method='linear')
        short_down = signal.chirp(t_short, 5000, short_duration, 0, method='linear')
        
        # Long chirps
        t_long = np.arange(0, long_duration, self.dt)
        long_up = signal.chirp(t_long, 0, long_duration, 5000, method='linear')
        long_down = signal.chirp(t_long, 5000, long_duration, 0, method='linear')
        
        # Gaps
        gap = np.zeros(int(gap_duration * self.sample_rate))
        long_gap = np.zeros(int(0.5 * self.sample_rate))
        
        # Assemble sequence
        chirp_seq = np.concatenate([
            # 3 short up
            short_up, gap, short_up, gap, short_up, gap,
            # 3 short down
            short_down, gap, short_down, gap, short_down,
            # 0.5s gap
            long_gap,
            # 3 long up
            long_up, gap, long_up, gap, long_up, gap,
            # 3 long down
            long_down, gap, long_down, gap, long_down, gap
        ])
        
        return chirp_seq
    
    def generate_burst_sequence(self) -> np.ndarray:
        """
        Generate single-cycle burst sequence for timing measurement
        
        - 5 bursts of 2.5 kHz (one cycle each)
        - 5 bursts of 5 kHz (one cycle each)
        - Evenly spaced over 1 second each
        
        Total: 2 seconds
        
        Returns:
            Burst sequence array
        """
        # 2.5 kHz bursts
        t_2k5 = np.arange(0, 1.0/2500, self.dt)
        burst_2k5 = np.sin(2 * np.pi * 2500 * t_2k5)
        
        # 5 kHz bursts
        t_5k = np.arange(0, 1.0/5000, self.dt)
        burst_5k = np.sin(2 * np.pi * 5000 * t_5k)
        
        # Create 1-second sequences with 5 bursts each
        burst_interval = int(self.sample_rate / 6)  # ~6 bursts per second
        
        seq_2k5 = np.zeros(self.sample_rate)
        seq_5k = np.zeros(self.sample_rate)
        
        for i in range(5):
            start_idx = i * burst_interval
            seq_2k5[start_idx:start_idx + len(burst_2k5)] = burst_2k5
            seq_5k[start_idx:start_idx + len(burst_5k)] = burst_5k
        
        return np.concatenate([seq_2k5, seq_5k])
    
    def generate_full_signal(self, include_voice: bool = False) -> np.ndarray:
        """
        Generate complete test signal
        
        Args:
            include_voice: If True, prepend 10s silence placeholder for voice
                          (actual voice is pre-recorded, not synthesized)
            
        Returns:
            Complete test signal array
        """
        components = []
        
        # Voice announcement (10s) - placeholder
        if include_voice:
            components.append(np.zeros(int(10 * self.sample_rate)))
        
        # 1. White noise (2s) - fixed seed for template matching
        components.append(self.generate_white_noise(2.0, seed=42))
        
        # 2. Blank (1s)
        components.append(np.zeros(int(1 * self.sample_rate)))
        
        # 3. Multi-tone with attenuation (10s) - STRONGEST DISCRIMINATOR
        components.append(self.generate_multitone(10.0))
        
        # 4. Blank (1s)
        components.append(np.zeros(int(1 * self.sample_rate)))
        
        # 5. Chirp sequences (8s)
        components.append(self.generate_chirp_sequence())
        
        # 6. Blank (2s)
        components.append(np.zeros(int(2 * self.sample_rate)))
        
        # 7. Single-cycle bursts (2s)
        components.append(self.generate_burst_sequence())
        
        # 8. Blank (1s)
        components.append(np.zeros(int(1 * self.sample_rate)))
        
        # 9. White noise (2s) - same seed for synchronization
        components.append(self.generate_white_noise(2.0, seed=42))
        
        # 10. Blank (3s)
        components.append(np.zeros(int(3 * self.sample_rate)))
        
        full_signal = np.concatenate(components)
        
        logger.info(f"Generated test signal: {len(full_signal)/self.sample_rate:.1f} seconds")
        
        return full_signal
    
    def get_multitone_template(self) -> np.ndarray:
        """
        Get just the multi-tone segment for template matching
        
        This is the most distinctive feature for discrimination.
        
        Returns:
            10-second multi-tone template
        """
        return self.generate_multitone(10.0)
    
    def get_chirp_template(self) -> np.ndarray:
        """
        Get just the chirp sequence for template matching
        
        Returns:
            ~8-second chirp template
        """
        return self.generate_chirp_sequence()


class WWVTestSignalDetector:
    """
    Detect WWV/WWVH scientific test signal in received audio
    
    Detection strategy:
    1. Check minute number (must be 8 for WWV or 44 for WWVH)
    2. Cross-correlate against multi-tone template (strongest feature)
    3. Verify with chirp detection (confirmatory)
    4. Classify as WWV or WWVH based on minute number
    """
    
    def __init__(self, sample_rate: int = 16000):
        """
        Initialize detector
        
        Args:
            sample_rate: Sample rate in Hz
        """
        self.sample_rate = sample_rate
        self.generator = WWVTestSignalGenerator(sample_rate)
        
        # Pre-generate templates for matching
        self.multitone_template = self.generator.get_multitone_template()
        self.chirp_template = self.generator.get_chirp_template()
        
        # Detection thresholds
        self.multitone_threshold = 0.15  # Correlation coefficient threshold (lowered for testing)
        self.chirp_threshold = 0.2
        self.combined_threshold = 0.20  # Overall confidence threshold (lowered for testing)
        
        logger.info(f"Test signal detector initialized (sample_rate={sample_rate})")
    
    def detect(
        self,
        iq_samples: np.ndarray,
        minute_number: int,
        sample_rate: int
    ) -> TestSignalDetection:
        """
        Detect test signal in received IQ samples
        
        Args:
            iq_samples: Complex IQ samples (full minute, ~960000 samples @ 16kHz)
            minute_number: Minute of hour (0-59)
            sample_rate: Sample rate in Hz
            
        Returns:
            TestSignalDetection object with results
        """
        # Quick exit if not test signal minute
        if minute_number not in [8, 44]:
            return TestSignalDetection(
                detected=False,
                confidence=0.0,
                station=None,
                minute_number=minute_number
            )
        
        # Determine expected station
        expected_station = 'WWV' if minute_number == 8 else 'WWVH'
        
        # Convert IQ to real (magnitude)
        audio_signal = np.abs(iq_samples)
        
        # Resample if necessary
        if sample_rate != self.sample_rate:
            num_samples = int(len(audio_signal) * self.sample_rate / sample_rate)
            audio_signal = signal.resample(audio_signal, num_samples)
        
        # Normalize
        audio_signal = audio_signal / np.max(np.abs(audio_signal))
        
        # Step 1: Multi-tone detection (primary discriminator)
        multitone_score, multitone_start = self._detect_multitone(audio_signal)
        
        # Step 2: Chirp detection (confirmatory)
        chirp_score, chirp_start = self._detect_chirp(audio_signal)
        
        # Step 3: Compute combined confidence
        # Weight multi-tone more heavily (it's more distinctive)
        confidence = 0.7 * multitone_score + 0.3 * chirp_score
        
        detected = confidence >= self.combined_threshold
        
        # Estimate SNR if detected
        snr_db = None
        if detected and multitone_start is not None:
            snr_db = self._estimate_snr(audio_signal, multitone_start, len(self.multitone_template))
        
        logger.info(f"Test signal detection: minute={minute_number}, "
                   f"multitone={multitone_score:.3f}, chirp={chirp_score:.3f}, "
                   f"confidence={confidence:.3f}, detected={detected}")
        
        return TestSignalDetection(
            detected=detected,
            confidence=confidence,
            station=expected_station if detected else None,
            minute_number=minute_number,
            multitone_score=multitone_score,
            chirp_score=chirp_score,
            signal_start_time=multitone_start,
            snr_db=snr_db
        )
    
    def _detect_multitone(self, audio_signal: np.ndarray) -> Tuple[float, Optional[float]]:
        """
        Detect multi-tone sequence using normalized cross-correlation
        
        Uses a sliding window approach with proper normalization to compute
        correlation coefficient at each position.
        
        Returns:
            (correlation_score, start_time_sec)
        """
        template = self.multitone_template
        template_len = len(template)
        
        # Pre-compute template statistics
        template_mean = np.mean(template)
        template_std = np.std(template)
        template_energy = np.sum((template - template_mean)**2)
        
        if template_std < 1e-10 or template_energy < 1e-10:
            return 0.0, None
        
        # Compute local means and stds using convolution (efficient)
        ones = np.ones(template_len)
        signal_len = len(audio_signal)
        
        # Local sums
        local_sum = signal.correlate(audio_signal, ones, mode='valid')
        local_mean = local_sum / template_len
        
        # Local squared sums for std calculation
        local_sum_sq = signal.correlate(audio_signal**2, ones, mode='valid')
        local_var = (local_sum_sq / template_len) - local_mean**2
        local_var = np.maximum(local_var, 0.0)  # Avoid negative variance from numerical errors
        local_std = np.sqrt(local_var)
        
        # Cross-correlation
        template_centered = template - template_mean
        correlation = signal.correlate(audio_signal, template_centered, mode='valid')
        
        # Normalize: corr_coef = correlation / (template_std * local_std * template_len)
        # But template is already centered, so we use template_energy instead
        normalized_corr = np.zeros(len(correlation))
        for i in range(len(correlation)):
            if local_std[i] > 1e-10:
                # Pearson correlation coefficient
                local_energy = local_std[i]**2 * template_len
                normalized_corr[i] = correlation[i] / np.sqrt(template_energy * local_energy)
        
        # Find peak correlation
        peak_idx = np.argmax(np.abs(normalized_corr))
        score = np.clip(abs(normalized_corr[peak_idx]), 0.0, 1.0)
        
        start_time = peak_idx / self.sample_rate if score > self.multitone_threshold else None
        
        return score, start_time
    
    def _detect_chirp(self, audio_signal: np.ndarray) -> Tuple[float, Optional[float]]:
        """
        Detect chirp sequence using spectrogram analysis
        
        Returns:
            (detection_score, start_time_sec)
        """
        # For chirps, use spectrogram rather than simple correlation
        # Look for characteristic time-frequency signature
        
        # Compute spectrogram
        f, t, Sxx = signal.spectrogram(
            audio_signal,
            fs=self.sample_rate,
            nperseg=512,
            noverlap=256
        )
        
        # Look for energy in 0-5 kHz band (chirp range)
        chirp_band = (f >= 0) & (f <= 5000)
        chirp_energy = np.sum(Sxx[chirp_band, :], axis=0)
        
        # Chirps create distinctive peaks in energy
        # Simple heuristic: look for variance in chirp band
        if len(chirp_energy) > 0:
            chirp_variance = np.std(chirp_energy) / (np.mean(chirp_energy) + 1e-10)
            score = np.clip(chirp_variance / 10.0, 0.0, 1.0)  # Empirical scaling
        else:
            score = 0.0
        
        # Rough start time from energy peak
        if score > self.chirp_threshold:
            peak_time_idx = np.argmax(chirp_energy)
            start_time = t[peak_time_idx]
        else:
            start_time = None
        
        return score, start_time
    
    def _estimate_snr(
        self,
        audio_signal: np.ndarray,
        signal_start: float,
        signal_length: int
    ) -> float:
        """
        Estimate SNR of detected signal
        
        Args:
            audio_signal: Full audio signal
            signal_start: Start time of signal (seconds)
            signal_length: Length of signal (samples)
            
        Returns:
            SNR in dB
        """
        start_idx = int(signal_start * self.sample_rate)
        end_idx = start_idx + signal_length
        
        if end_idx > len(audio_signal):
            return 0.0
        
        # Signal power
        signal_segment = audio_signal[start_idx:end_idx]
        signal_power = np.mean(signal_segment**2)
        
        # Noise power (from before signal)
        noise_start = max(0, start_idx - signal_length)
        noise_segment = audio_signal[noise_start:start_idx]
        noise_power = np.mean(noise_segment**2) if len(noise_segment) > 0 else 1e-10
        
        snr_db = 10 * np.log10(signal_power / noise_power)
        
        return float(snr_db)


# Convenience function for integration
def detect_test_signal(
    iq_samples: np.ndarray,
    sample_rate: int,
    minute_number: int
) -> TestSignalDetection:
    """
    Convenience function to detect test signal
    
    Args:
        iq_samples: Complex IQ samples
        sample_rate: Sample rate in Hz
        minute_number: Minute of hour (0-59)
        
    Returns:
        TestSignalDetection object
    """
    detector = WWVTestSignalDetector(sample_rate)
    return detector.detect(iq_samples, minute_number, sample_rate)
