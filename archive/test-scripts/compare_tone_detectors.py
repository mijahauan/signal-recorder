#!/usr/bin/env python3
"""
Compare tone detection algorithms on archived NPZ data

Tests multiple detection methods against existing 16 kHz NPZ archives to 
determine which approach provides best sensitivity and accuracy for WWV/CHU
tone detection.

Usage:
    python3 scripts/compare_tone_detectors.py --date 20251116 --channel "WWV 5 MHz"
"""

import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple
import numpy as np
from dataclasses import dataclass
import pandas as pd

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.signal_recorder.paths import get_paths

from scipy import signal
from scipy.fft import fft, fftfreq

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class DetectionResult:
    """Result from a tone detector"""
    detected: bool
    timing_error_ms: Optional[float]  # None if not detected
    snr_db: Optional[float]
    confidence: float  # 0-1 scale
    peak_value: float
    method: str


class CurrentMatchedFilterDetector:
    """Current LIVE detector: quadrature matched filter + 2-sigma threshold"""
    
    def __init__(self, tone_freq=1000, tone_duration=0.8, sample_rate=3000):
        self.tone_freq = tone_freq
        self.tone_duration = tone_duration
        self.sample_rate = sample_rate
        self.method = "current_live"
        
        # Create quadrature templates (same as live detector)
        t = np.arange(0, tone_duration, 1/sample_rate)
        window = signal.windows.tukey(len(t), alpha=0.1)
        
        self.template_sin = np.sin(2 * np.pi * tone_freq * t) * window
        self.template_cos = np.cos(2 * np.pi * tone_freq * t) * window
        
        # Normalize
        self.template_sin /= np.linalg.norm(self.template_sin)
        self.template_cos /= np.linalg.norm(self.template_cos)
    
    def detect(self, iq_16k: np.ndarray, expected_time: float) -> DetectionResult:
        """Detect tone using CURRENT LIVE method (quadrature matched filter + 2-sigma)"""
        # Resample to 3 kHz
        iq_3k = signal.resample(iq_16k, len(iq_16k) * 3000 // 16000)
        
        # AM demodulate (extract envelope)
        magnitude = np.abs(iq_3k)
        audio_signal = magnitude - np.mean(magnitude)  # AC coupling
        
        # Quadrature correlation (phase-invariant)
        corr_sin = np.correlate(audio_signal, self.template_sin, mode='valid')
        corr_cos = np.correlate(audio_signal, self.template_cos, mode='valid')
        
        if len(corr_sin) == 0:
            return DetectionResult(False, None, None, 0, 0, self.method)
        
        # Combine: sqrt(sin^2 + cos^2)
        correlation = np.sqrt(corr_sin**2 + corr_cos**2)
        
        # Find peak
        peak_idx = np.argmax(correlation)
        peak_val = correlation[peak_idx]
        
        # Noise-adaptive threshold (2-sigma, same as live detector)
        noise_mean = np.mean(correlation)
        noise_std = np.std(correlation)
        threshold = noise_mean + 2.0 * noise_std
        
        detected = peak_val > threshold
        
        if detected:
            # Timing calculation
            edge_time = peak_idx / self.sample_rate
            timing_error = edge_time * 1000  # ms from start
            
            # SNR
            if noise_mean > 0:
                snr_db = 20 * np.log10(peak_val / noise_mean)
            else:
                snr_db = None
            
            confidence = min(1.0, peak_val / (threshold * 2.0))
            
            return DetectionResult(
                detected=True,
                timing_error_ms=timing_error,
                snr_db=snr_db,
                confidence=confidence,
                peak_value=peak_val,
                method=self.method
            )
        
        return DetectionResult(
            detected=False,
            timing_error_ms=None,
            snr_db=None,
            confidence=peak_val / (threshold + 1e-10),
            peak_value=peak_val,
            method=self.method
        )


class MatchedFilterDetector:
    """Matched filter: correlate with known tone template"""
    
    def __init__(self, tone_freq=1000, tone_duration=0.8, sample_rate=3000):
        self.tone_freq = tone_freq
        self.tone_duration = tone_duration
        self.sample_rate = sample_rate
        self.method = "matched_filter"
        
        # Generate reference tone template
        n_samples = int(tone_duration * sample_rate)
        t = np.arange(n_samples) / sample_rate
        
        # Windowed tone (Hann window for smooth edges)
        window = np.hanning(n_samples)
        self.template = np.sin(2 * np.pi * tone_freq * t) * window
        
        # Normalize template
        self.template = self.template / np.linalg.norm(self.template)
    
    def detect(self, iq_16k: np.ndarray, expected_time: float) -> DetectionResult:
        """
        Detect tone using matched filter (correlation with template)
        """
        # Resample to 3 kHz
        iq_3k = signal.resample(iq_16k, len(iq_16k) * 3000 // 16000)
        
        # AM demodulate
        envelope = np.abs(iq_3k)
        
        # Remove DC
        envelope = envelope - np.mean(envelope)
        
        # Bandpass filter 950-1050 Hz
        sos = signal.butter(4, [950, 1050], btype='band', fs=3000, output='sos')
        filtered = signal.sosfilt(sos, envelope)
        
        # Matched filter: correlate with template
        correlation = np.correlate(filtered, self.template, mode='valid')
        
        # Normalize correlation by input energy
        n_template = len(self.template)
        input_energy = np.array([
            np.sum(filtered[i:i+n_template]**2) 
            for i in range(len(correlation))
        ])
        input_energy = np.sqrt(input_energy + 1e-10)  # Avoid division by zero
        normalized_corr = correlation / input_energy
        
        # Peak detection
        peak_idx = np.argmax(normalized_corr)
        peak_value = normalized_corr[peak_idx]
        
        # Adaptive threshold based on noise floor
        noise_estimate = np.median(np.abs(normalized_corr))
        threshold = noise_estimate + 5 * np.std(normalized_corr)  # 5-sigma
        
        detected = peak_value > threshold
        
        if detected:
            # Timing: peak position in correlation
            edge_time = peak_idx / self.sample_rate
            timing_error = edge_time * 1000  # ms from start
            
            # SNR estimate
            snr_db = 20 * np.log10(peak_value / (noise_estimate + 1e-10))
            
            # Confidence based on how much peak exceeds threshold
            confidence = min(1.0, peak_value / (threshold * 2))
            
            return DetectionResult(
                detected=True,
                timing_error_ms=timing_error,
                snr_db=snr_db,
                confidence=confidence,
                peak_value=peak_value,
                method=self.method
            )
        
        return DetectionResult(
            detected=False,
            timing_error_ms=None,
            snr_db=None,
            confidence=peak_value / (threshold + 1e-10),
            peak_value=peak_value,
            method=self.method
        )


class AdaptiveThresholdDetector:
    """Envelope detection with adaptive noise-based threshold"""
    
    def __init__(self, tone_freq=1000, sigma_multiplier=5.0):
        self.tone_freq = tone_freq
        self.sigma_multiplier = sigma_multiplier
        self.method = "adaptive_threshold"
    
    def detect(self, iq_16k: np.ndarray, expected_time: float) -> DetectionResult:
        """Detect tone using adaptive threshold based on noise floor"""
        # Same preprocessing as baseline
        iq_3k = signal.resample(iq_16k, len(iq_16k) * 3000 // 16000)
        envelope = np.abs(iq_3k) - np.mean(np.abs(iq_3k))
        
        sos = signal.butter(4, [950, 1050], btype='band', fs=3000, output='sos')
        filtered = signal.sosfilt(sos, envelope)
        
        analytic = signal.hilbert(filtered)
        tone_envelope = np.abs(analytic)
        
        # Adaptive threshold
        noise_floor = np.percentile(tone_envelope, 10)  # 10th percentile
        noise_std = np.std(tone_envelope[tone_envelope < np.median(tone_envelope)])
        threshold = noise_floor + self.sigma_multiplier * noise_std
        
        peak = np.max(tone_envelope)
        detected = peak > threshold
        
        if detected:
            above_threshold = np.where(tone_envelope > threshold)[0]
            if len(above_threshold) > 0:
                edge_sample = above_threshold[0]
                edge_time = edge_sample / 3000.0
                timing_error = edge_time * 1000
                
                snr_db = 20 * np.log10(peak / (noise_floor + 1e-10))
                confidence = min(1.0, peak / (threshold * 1.5))
                
                return DetectionResult(
                    detected=True,
                    timing_error_ms=timing_error,
                    snr_db=snr_db,
                    confidence=confidence,
                    peak_value=peak,
                    method=self.method
                )
        
        return DetectionResult(
            detected=False,
            timing_error_ms=None,
            snr_db=None,
            confidence=peak / (threshold + 1e-10),
            peak_value=peak,
            method=self.method
        )


def load_minute_npz(npz_path: Path) -> Tuple[np.ndarray, float]:
    """
    Load IQ data from NPZ archive
    
    Returns:
        (iq_samples, unix_timestamp)
    """
    data = np.load(npz_path)
    iq = data['iq']
    
    # Parse timestamp from filename
    timestamp_str = npz_path.stem.split('_')[0]
    dt = datetime.strptime(timestamp_str, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
    unix_ts = dt.timestamp()
    
    return iq, unix_ts


def compare_detectors_on_day(archive_dir: Path, date_str: str, channel_name: str, limit: Optional[int] = None) -> pd.DataFrame:
    """
    Run all detectors on a day's worth of NPZ files
    
    Args:
        limit: Optional limit on number of files to process (for testing)
    
    Returns:
        DataFrame with comparison results
    """
    # Initialize detectors
    detectors = [
        CurrentMatchedFilterDetector(tone_duration=0.8),  # Current live (2-sigma)
        AdaptiveThresholdDetector(sigma_multiplier=5.0),  # 5-sigma variant
        AdaptiveThresholdDetector(sigma_multiplier=3.0)   # 3-sigma variant
    ]
    detectors[2].method = "adaptive_3sigma"  # Rename for clarity
    
    # Find NPZ files for this date
    npz_files = sorted(archive_dir.glob(f"{date_str}*_iq.npz"))
    
    if limit:
        npz_files = npz_files[:limit]
    
    logger.info(f"Found {len(npz_files)} NPZ files for {date_str}")
    sys.stdout.flush()
    
    if not npz_files:
        logger.warning(f"No NPZ files found in {archive_dir}")
        return pd.DataFrame()
    
    results = []
    
    for i, npz_path in enumerate(npz_files):
        if (i + 1) % 10 == 0:
            logger.info(f"Processed {i + 1}/{len(npz_files)} files...")
            sys.stdout.flush()
        
        try:
            iq_data, unix_ts = load_minute_npz(npz_path)
            
            # Only analyze minutes at :00 seconds (when tone should appear)
            dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc)
            if dt.second != 0:
                continue
            
            minute_result = {
                'timestamp': dt.isoformat(),
                'unix_ts': unix_ts,
                'minute': dt.minute,
                'hour': dt.hour
            }
            
            # Run all detectors
            for detector in detectors:
                result = detector.detect(iq_data, unix_ts)
                prefix = detector.method
                
                minute_result[f'{prefix}_detected'] = result.detected
                minute_result[f'{prefix}_timing_ms'] = result.timing_error_ms
                minute_result[f'{prefix}_snr_db'] = result.snr_db
                minute_result[f'{prefix}_confidence'] = result.confidence
                minute_result[f'{prefix}_peak'] = result.peak_value
            
            results.append(minute_result)
            
        except Exception as e:
            logger.warning(f"Failed to process {npz_path.name}: {e}")
            continue
    
    df = pd.DataFrame(results)
    logger.info(f"\n{'='*60}")
    logger.info(f"Processed {len(df)} minutes at :00 seconds")
    return df


def print_comparison_summary(df: pd.DataFrame, channel_name: str, date_str: str):
    """Print comparison summary statistics"""
    
    print(f"\n{'='*80}")
    print(f"Tone Detection Comparison: {channel_name} on {date_str}")
    print(f"{'='*80}\n")
    
    methods = ['current_live', 'adaptive_threshold', 'adaptive_3sigma']
    
    print(f"{'Method':<20} {'Detections':<15} {'Avg SNR':<12} {'Avg Timing':<15} {'Min SNR':<10}")
    print(f"{'-'*80}")
    
    for method in methods:
        detected_col = f'{method}_detected'
        snr_col = f'{method}_snr_db'
        timing_col = f'{method}_timing_ms'
        
        if detected_col not in df.columns:
            continue
        
        detections = df[detected_col].sum()
        total = len(df)
        
        detected_df = df[df[detected_col] == True]
        
        if len(detected_df) > 0:
            avg_snr = detected_df[snr_col].mean()
            avg_timing = detected_df[timing_col].mean()
            min_snr = detected_df[snr_col].min()
        else:
            avg_snr = avg_timing = min_snr = 0
        
        print(f"{method:<20} {detections}/{total:<10} {avg_snr:>8.1f} dB  {avg_timing:>10.1f} ms  {min_snr:>7.1f} dB")
    
    # Agreement analysis
    print(f"\n{'Agreement Analysis:':<20}")
    all_detected = df['current_live_detected'] & df['adaptive_threshold_detected'] & df['adaptive_3sigma_detected']
    print(f"  All methods agree: {all_detected.sum()}/{len(df)} ({100*all_detected.sum()/len(df):.1f}%)")
    
    # Unique detections
    for method in methods:
        detected_col = f'{method}_detected'
        other_methods = [m for m in methods if m != method]
        
        unique = df[detected_col].copy()
        for other in other_methods:
            unique = unique & ~df[f'{other}_detected']
        
        if unique.sum() > 0:
            print(f"  Only {method}: {unique.sum()} detections")


def main():
    parser = argparse.ArgumentParser(description='Compare tone detection algorithms')
    parser.add_argument('--date', required=True, help='Date in YYYYMMDD format')
    parser.add_argument('--channel', required=True, help='Channel name (e.g., "WWV 5 MHz")')
    parser.add_argument('--data-root', default='/tmp/grape-test', help='Data root path')
    parser.add_argument('--output', help='Output CSV file (optional)')
    parser.add_argument('--limit', type=int, help='Limit number of files to process (for testing)')
    
    args = parser.parse_args()
    
    # Immediate output to show script started
    print(f"\n{'='*80}")
    print(f"Tone Detector Comparison Script")
    print(f"{'='*80}")
    print(f"Date: {args.date}")
    print(f"Channel: {args.channel}")
    print(f"Data root: {args.data_root}")
    if args.limit:
        print(f"Limit: {args.limit} files (test mode)")
    print(f"{'='*80}\n")
    sys.stdout.flush()
    
    # Get archive directory
    channel_dir = args.channel.replace(' ', '_')
    archive_dir = Path(args.data_root) / 'archives' / channel_dir
    
    if not archive_dir.exists():
        logger.error(f"Archive directory not found: {archive_dir}")
        return 1
    
    logger.info(f"Analyzing {args.channel} on {args.date}")
    logger.info(f"Archive directory: {archive_dir}")
    sys.stdout.flush()
    
    # Run comparison
    df = compare_detectors_on_day(archive_dir, args.date, args.channel, limit=args.limit)
    
    if df.empty:
        logger.error("No data processed")
        return 1
    
    # Print summary
    print_comparison_summary(df, args.channel, args.date)
    
    # Save results if requested
    if args.output:
        df.to_csv(args.output, index=False)
        logger.info(f"\nResults saved to: {args.output}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
