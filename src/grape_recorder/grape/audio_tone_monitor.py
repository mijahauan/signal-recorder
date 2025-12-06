#!/usr/bin/env python3
"""
Audio Tone Monitor - Continuous 500/600 Hz power and intermodulation analysis

Monitors audio tones every minute to detect:
1. WWV 500 Hz tone power
2. WWVH 600 Hz tone power  
3. Intermodulation products from 100 Hz BCD:
   - 400 Hz (500 - 100): WWV BCD sideband
   - 600 Hz (500 + 100): WWV BCD interfering with WWVH
   - 500 Hz (600 - 100): WWVH BCD interfering with WWV
   - 700 Hz (600 + 100): WWVH BCD sideband

This allows detection of which station's signal is present by looking at
the intermodulation signatures, even when both are transmitting the same tone.
"""

import numpy as np
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Tuple
from scipy.fft import rfft, rfftfreq
from scipy import signal as scipy_signal

logger = logging.getLogger(__name__)


@dataclass
class AudioToneAnalysis:
    """Results from audio tone analysis for one minute."""
    minute_boundary: int
    
    # Primary audio tones (dB)
    power_500_hz_db: float
    power_600_hz_db: float
    
    # BCD intermodulation products (dB)
    power_400_hz_db: float  # 500 - 100: WWV BCD lower sideband
    power_700_hz_db: float  # 600 + 100: WWVH BCD upper sideband
    
    # Timing marker tones (dB)
    power_1000_hz_db: float  # WWV timing marker
    power_1200_hz_db: float  # WWVH timing marker
    
    # Derived metrics
    ratio_500_600_db: float  # WWV vs WWVH audio tone ratio
    ratio_400_700_db: float  # WWV vs WWVH intermod signature
    
    # Intermodulation analysis
    wwv_intermod_500_to_600_db: float   # How much WWV's 500 Hz leaks to 600 Hz via BCD
    wwvh_intermod_600_to_500_db: float  # How much WWVH's 600 Hz leaks to 500 Hz via BCD
    
    # Station dominance from intermod signature
    intermod_dominant_station: Optional[str]  # 'WWV', 'WWVH', or None
    intermod_confidence: float  # 0.0 to 1.0


class AudioToneMonitor:
    """
    Continuous audio tone monitoring with intermodulation analysis.
    
    The key insight: WWV and WWVH both use 100 Hz BCD amplitude modulation.
    This creates sidebands around their audio tones.
    
    CRITICAL: WWV and WWVH SWAP tones according to the schedule!
    
    When WWV=500Hz, WWVH=600Hz (minutes 4, 6, 12, 20, 22...):
      - 400 Hz (500-100) = WWV BCD sideband
      - 700 Hz (600+100) = WWVH BCD sideband
    
    When WWV=600Hz, WWVH=500Hz (minutes 3, 5, 11, 21, 23...):
      - 400 Hz (500-100) = WWVH BCD sideband
      - 700 Hz (600+100) = WWV BCD sideband
    
    The interpretation of 400/700 Hz FLIPS depending on the minute!
    Must consult TONE_SCHEDULE_500_600 to correctly interpret.
    """
    
    def __init__(self, channel_name: str, sample_rate: int = 20000):
        self.channel_name = channel_name
        self.sample_rate = sample_rate
        
        # Tone frequencies to monitor
        self.tone_freqs = {
            '400_hz': 400,   # WWV BCD lower sideband
            '500_hz': 500,   # WWV audio tone / WWVH BCD lower sideband
            '600_hz': 600,   # WWVH audio tone / WWV BCD upper sideband
            '700_hz': 700,   # WWVH BCD upper sideband
            '1000_hz': 1000, # WWV timing marker
            '1200_hz': 1200, # WWVH timing marker
        }
        
        # Bandwidth for tone power measurement (Hz)
        self.tone_bandwidth = 10  # ±5 Hz
        
        logger.info(f"{channel_name}: AudioToneMonitor initialized @ {sample_rate} Hz")
    
    def analyze_minute(
        self,
        iq_samples: np.ndarray,
        minute_boundary: int
    ) -> AudioToneAnalysis:
        """
        Analyze audio tones and intermodulation for one minute of IQ samples.
        
        Args:
            iq_samples: Complex IQ samples for the minute
            minute_boundary: UTC timestamp of minute start
            
        Returns:
            AudioToneAnalysis with all tone powers and intermod metrics
        """
        # Get minute number for schedule lookup
        minute_number = (minute_boundary // 60) % 60
        
        # Get schedule to know which station has which tone
        from .wwv_constants import TONE_SCHEDULE_500_600
        schedule = TONE_SCHEDULE_500_600.get(minute_number, {'WWV': None, 'WWVH': None})
        wwv_tone = schedule.get('WWV')
        wwvh_tone = schedule.get('WWVH')
        
        # AM demodulation to get audio
        magnitude = np.abs(iq_samples)
        audio_signal = magnitude - np.mean(magnitude)
        
        # Use seconds 5-55 to avoid voice announcements
        start_sample = int(5.0 * self.sample_rate)
        end_sample = min(int(55.0 * self.sample_rate), len(audio_signal))
        
        if end_sample <= start_sample:
            return self._empty_result(minute_boundary)
        
        audio_window = audio_signal[start_sample:end_sample]
        
        # Window and FFT
        windowed = audio_window * scipy_signal.windows.hann(len(audio_window))
        fft_result = rfft(windowed)
        fft_power = np.abs(fft_result) ** 2
        freqs = rfftfreq(len(windowed), 1/self.sample_rate)
        
        # Measure power at each frequency
        powers = {}
        for name, freq in self.tone_freqs.items():
            powers[name] = self._measure_tone_power(fft_power, freqs, freq)
        
        # Calculate noise floor (median power in 200-300 Hz band)
        noise_mask = (freqs >= 200) & (freqs <= 300)
        if np.any(noise_mask):
            noise_floor = np.median(fft_power[noise_mask])
        else:
            noise_floor = np.median(fft_power)
        
        noise_floor_db = 10 * np.log10(noise_floor + 1e-12)
        
        # Convert to dB (SNR relative to noise floor)
        power_400_db = 10 * np.log10(powers['400_hz'] + 1e-12) - noise_floor_db
        power_500_db = 10 * np.log10(powers['500_hz'] + 1e-12) - noise_floor_db
        power_600_db = 10 * np.log10(powers['600_hz'] + 1e-12) - noise_floor_db
        power_700_db = 10 * np.log10(powers['700_hz'] + 1e-12) - noise_floor_db
        power_1000_db = 10 * np.log10(powers['1000_hz'] + 1e-12) - noise_floor_db
        power_1200_db = 10 * np.log10(powers['1200_hz'] + 1e-12) - noise_floor_db
        
        # Ratios
        ratio_500_600_db = power_500_db - power_600_db
        ratio_400_700_db = power_400_db - power_700_db
        
        # Intermodulation analysis - SCHEDULE DEPENDENT!
        # The 400/700 Hz interpretation depends on which station has which tone
        #
        # If WWV=500Hz, WWVH=600Hz:
        #   400 Hz = 500-100 = WWV sideband
        #   700 Hz = 600+100 = WWVH sideband
        #   → ratio_400_700 positive = WWV dominant
        #
        # If WWV=600Hz, WWVH=500Hz:
        #   400 Hz = 500-100 = WWVH sideband  
        #   700 Hz = 600+100 = WWV sideband
        #   → ratio_400_700 positive = WWVH dominant (FLIPPED!)
        
        intermod_dominant = None
        intermod_conf = 0.0
        wwv_intermod = 0.0
        wwvh_intermod = 0.0
        
        if wwv_tone is not None and wwvh_tone is not None:
            if wwv_tone == 500 and wwvh_tone == 600:
                # Normal case: 400 Hz = WWV, 700 Hz = WWVH
                wwv_intermod = power_400_db  # WWV's sideband
                wwvh_intermod = power_700_db  # WWVH's sideband
                
                if ratio_400_700_db > 6:
                    intermod_dominant = 'WWV'
                    intermod_conf = min(1.0, ratio_400_700_db / 15.0)
                elif ratio_400_700_db < -6:
                    intermod_dominant = 'WWVH'
                    intermod_conf = min(1.0, -ratio_400_700_db / 15.0)
                    
            elif wwv_tone == 600 and wwvh_tone == 500:
                # Flipped case: 400 Hz = WWVH, 700 Hz = WWV
                wwv_intermod = power_700_db  # WWV's sideband (600+100)
                wwvh_intermod = power_400_db  # WWVH's sideband (500-100)
                
                # Interpretation is REVERSED!
                if ratio_400_700_db > 6:
                    intermod_dominant = 'WWVH'  # Strong 400 Hz = WWVH
                    intermod_conf = min(1.0, ratio_400_700_db / 15.0)
                elif ratio_400_700_db < -6:
                    intermod_dominant = 'WWV'  # Strong 700 Hz = WWV
                    intermod_conf = min(1.0, -ratio_400_700_db / 15.0)
        
        # Log the schedule-aware interpretation
        logger.debug(
            f"{self.channel_name}: Intermod analysis min={minute_number}: "
            f"WWV={wwv_tone}Hz, WWVH={wwvh_tone}Hz, "
            f"400/700_ratio={ratio_400_700_db:.1f}dB → {intermod_dominant}"
        )
        
        return AudioToneAnalysis(
            minute_boundary=minute_boundary,
            power_500_hz_db=power_500_db,
            power_600_hz_db=power_600_db,
            power_400_hz_db=power_400_db,
            power_700_hz_db=power_700_db,
            power_1000_hz_db=power_1000_db,
            power_1200_hz_db=power_1200_db,
            ratio_500_600_db=ratio_500_600_db,
            ratio_400_700_db=ratio_400_700_db,
            wwv_intermod_500_to_600_db=wwv_intermod,
            wwvh_intermod_600_to_500_db=wwvh_intermod,
            intermod_dominant_station=intermod_dominant,
            intermod_confidence=intermod_conf
        )
    
    def _measure_tone_power(
        self,
        fft_power: np.ndarray,
        freqs: np.ndarray,
        target_freq: float
    ) -> float:
        """Measure power in a narrow band around target frequency."""
        half_bw = self.tone_bandwidth / 2
        mask = (freqs >= target_freq - half_bw) & (freqs <= target_freq + half_bw)
        if np.any(mask):
            return np.sum(fft_power[mask])
        return 0.0
    
    def _empty_result(self, minute_boundary: int) -> AudioToneAnalysis:
        """Return empty result when insufficient data."""
        return AudioToneAnalysis(
            minute_boundary=minute_boundary,
            power_500_hz_db=-99.0,
            power_600_hz_db=-99.0,
            power_400_hz_db=-99.0,
            power_700_hz_db=-99.0,
            power_1000_hz_db=-99.0,
            power_1200_hz_db=-99.0,
            ratio_500_600_db=0.0,
            ratio_400_700_db=0.0,
            wwv_intermod_500_to_600_db=0.0,
            wwvh_intermod_600_to_500_db=0.0,
            intermod_dominant_station=None,
            intermod_confidence=0.0
        )


def analyze_bcd_tone_correlation(
    iq_samples: np.ndarray,
    sample_rate: int,
    minute_timestamp: float
) -> Dict[str, float]:
    """
    Analyze correlation between BCD envelope and audio tone power.
    
    Divides the minute into 1-second windows and measures how well
    the 500/600 Hz tone power tracks the BCD bit pattern.
    
    Args:
        iq_samples: Complex IQ samples for the minute
        sample_rate: Sample rate in Hz
        minute_timestamp: UTC timestamp of minute start
        
    Returns:
        Dict with correlation coefficients:
        - bcd_500hz_correlation: How well 500 Hz tracks BCD
        - bcd_600hz_correlation: How well 600 Hz tracks BCD
    """
    # This is a placeholder for more sophisticated analysis
    # Would need to:
    # 1. Extract BCD envelope (100 Hz AM demod)
    # 2. Extract 500/600 Hz power in short windows
    # 3. Compute correlation coefficient
    
    return {
        'bcd_500hz_correlation': 0.0,
        'bcd_600hz_correlation': 0.0
    }
