#!/usr/bin/env python3
"""
DEPRECATED: Use carrier_spectrogram.py instead
==============================================

This module is deprecated and will be removed in a future version.
Use CarrierSpectrogramGenerator from carrier_spectrogram.py for:
- Solar zenith overlay support (path midpoint calculation)
- Quality grade visualization
- Gap highlighting
- Rolling spectrograms
- Correct Phase 3 path structure

Migration:
----------
    # OLD (deprecated):
    from hf_timestd.core.spectrogram_generator import SpectrogramGenerator
    gen = SpectrogramGenerator(data_root, channel_name)
    gen.generate_day('20251204')
    
    # NEW (recommended):
    from hf_timestd.core.carrier_spectrogram import CarrierSpectrogramGenerator
    gen = CarrierSpectrogramGenerator(data_root, channel_name, receiver_grid='EM38ww')
    gen.generate_daily('20251204')

Command Line:
    # NEW (recommended):
    python -m hf_timestd.core.carrier_spectrogram \\
        --data-root /tmp/grape-test \\
        --channel "WWV 10 MHz" \\
        --date 20251204 \\
        --grid EM38ww

Deprecated: 2025-12-08 (Phase 3 consolidation)
"""
import warnings
warnings.warn(
    "spectrogram_generator.py is deprecated. Use carrier_spectrogram.py instead.",
    DeprecationWarning,
    stacklevel=2
)

import numpy as np
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple, Dict, Any
from dataclasses import dataclass
import json

logger = logging.getLogger(__name__)

# Check for matplotlib
try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend for server use
    import matplotlib.pyplot as plt
    from matplotlib.dates import DateFormatter, HourLocator
    from matplotlib.colors import LogNorm
    MPL_AVAILABLE = True
except ImportError:
    MPL_AVAILABLE = False
    logger.warning("matplotlib not available - spectrogram generation disabled")

# Check for scipy
try:
    from scipy import signal
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    logger.warning("scipy not available - spectrogram generation disabled")

# Check for Digital RF
try:
    import digital_rf as drf
    DRF_AVAILABLE = True
except ImportError:
    DRF_AVAILABLE = False
    logger.warning("digital_rf not available - cannot read Phase 3 DRF data")


# Constants
SAMPLE_RATE_10HZ = 10  # 10 Hz decimated data
SAMPLES_PER_MINUTE = 600  # 10 Hz * 60 seconds
SAMPLES_PER_HOUR = 36000  # 10 Hz * 3600 seconds
SAMPLES_PER_DAY = 864000  # 10 Hz * 86400 seconds

# Spectrogram parameters
NFFT = 256  # FFT size
NOVERLAP = 128  # 50% overlap
CMAP = 'viridis'  # Colormap


@dataclass
class SpectrogramConfig:
    """Configuration for spectrogram generation."""
    nfft: int = 256
    noverlap: int = 128
    cmap: str = 'viridis'
    vmin_db: float = -80  # Minimum dB for colormap
    vmax_db: float = -20  # Maximum dB for colormap
    dpi: int = 150
    daily_width: int = 16  # Figure width for daily spectrogram
    daily_height: int = 6  # Figure height for daily spectrogram
    hourly_width: int = 12
    hourly_height: int = 4
    generate_daily: bool = True
    generate_hourly: bool = True
    generate_power_chart: bool = True


class SpectrogramGenerator:
    """
    Generate spectrograms from Phase 3 decimated DRF data.
    
    Reads 10 Hz Digital RF from products/{CHANNEL}/decimated/
    and generates PNG spectrograms to products/{CHANNEL}/spectrograms/
    """
    
    def __init__(
        self,
        data_root: Path,
        channel_name: str,
        config: Optional[SpectrogramConfig] = None
    ):
        """
        Initialize spectrogram generator.
        
        Args:
            data_root: Root data directory
            channel_name: Channel name (e.g., "WWV 10 MHz")
            config: Spectrogram configuration
        """
        if not MPL_AVAILABLE:
            raise ImportError("matplotlib required for spectrogram generation")
        if not SCIPY_AVAILABLE:
            raise ImportError("scipy required for spectrogram generation")
        
        self.data_root = Path(data_root)
        self.channel_name = channel_name
        self.config = config or SpectrogramConfig()
        
        # Channel directory name
        self.channel_dir = channel_name.replace(' ', '_')
        
        # Input: Phase 3 decimated DRF
        self.decimated_dir = self.data_root / 'products' / self.channel_dir / 'decimated'
        
        # Output: spectrograms
        self.output_dir = self.data_root / 'products' / self.channel_dir / 'spectrograms'
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"SpectrogramGenerator initialized for {channel_name}")
        logger.info(f"  Input: {self.decimated_dir}")
        logger.info(f"  Output: {self.output_dir}")
    
    def generate_day(self, date_str: str) -> Dict[str, Any]:
        """
        Generate all spectrograms for a day.
        
        Args:
            date_str: Date string (YYYY-MM-DD or YYYYMMDD)
            
        Returns:
            Dict with generation results
        """
        # Normalize date format
        if '-' in date_str:
            date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        else:
            date_obj = datetime.strptime(date_str, '%Y%m%d')
        
        date_yyyymmdd = date_obj.strftime('%Y%m%d')
        
        results = {
            'date': date_str,
            'channel': self.channel_name,
            'spectrograms_generated': [],
            'errors': []
        }
        
        logger.info(f"Generating spectrograms for {self.channel_name} on {date_str}")
        
        # Read day's data
        day_data = self._read_day_data(date_yyyymmdd)
        if day_data is None:
            results['errors'].append("No data found for date")
            return results
        
        # Create output directory for this date
        date_output_dir = self.output_dir / date_yyyymmdd
        date_output_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate daily overview spectrogram
        if self.config.generate_daily:
            try:
                daily_path = self._generate_daily_spectrogram(
                    day_data, date_obj, date_output_dir
                )
                if daily_path:
                    results['spectrograms_generated'].append(str(daily_path))
            except Exception as e:
                logger.error(f"Daily spectrogram error: {e}")
                results['errors'].append(f"Daily: {e}")
        
        # Generate power chart
        if self.config.generate_power_chart:
            try:
                power_path = self._generate_power_chart(
                    day_data, date_obj, date_output_dir
                )
                if power_path:
                    results['spectrograms_generated'].append(str(power_path))
            except Exception as e:
                logger.error(f"Power chart error: {e}")
                results['errors'].append(f"Power chart: {e}")
        
        # Generate hourly spectrograms
        if self.config.generate_hourly:
            for hour in range(24):
                try:
                    hourly_path = self._generate_hourly_spectrogram(
                        day_data, date_obj, hour, date_output_dir
                    )
                    if hourly_path:
                        results['spectrograms_generated'].append(str(hourly_path))
                except Exception as e:
                    logger.error(f"Hourly spectrogram error (hour {hour}): {e}")
                    results['errors'].append(f"Hour {hour}: {e}")
        
        logger.info(f"Generated {len(results['spectrograms_generated'])} spectrograms")
        return results
    
    def _read_day_data(self, date_yyyymmdd: str) -> Optional[np.ndarray]:
        """
        Read a day's worth of 10 Hz data from Phase 3 DRF.
        
        Returns:
            Complex64 array of shape (864000,) or None if no data
        """
        # Look for DRF data in the date directory
        date_dir = self.decimated_dir / date_yyyymmdd
        
        if not date_dir.exists():
            logger.warning(f"No decimated data directory: {date_dir}")
            return None
        
        # Try to read with Digital RF
        if DRF_AVAILABLE:
            return self._read_drf_day(date_dir, date_yyyymmdd)
        else:
            # Fallback to NPZ files if present
            return self._read_npz_day(date_dir, date_yyyymmdd)
    
    def _read_drf_day(self, date_dir: Path, date_yyyymmdd: str) -> Optional[np.ndarray]:
        """Read day data from Digital RF format."""
        try:
            # Find the channel directory (ch0)
            # Structure: {date}/{callsign}_{grid}/{receiver}@{id}/OBS*/ch0/
            ch0_dirs = list(date_dir.glob('**/ch0'))
            
            if not ch0_dirs:
                logger.warning(f"No ch0 directory found under {date_dir}")
                return None
            
            # Use the first ch0 found
            ch0_dir = ch0_dirs[0]
            
            # Open DRF reader
            reader = drf.DigitalRFReader(str(ch0_dir.parent))
            channels = reader.get_channels()
            
            if not channels:
                logger.warning("No channels in DRF reader")
                return None
            
            channel = channels[0]
            bounds = reader.get_bounds(channel)
            
            if bounds[0] is None:
                logger.warning("No data bounds in DRF")
                return None
            
            # Read all samples
            start_idx, end_idx = bounds
            samples = reader.read_vector(start_idx, end_idx - start_idx, channel)
            
            # Convert from float32 (N, 2) to complex64
            if samples.dtype != np.complex64:
                if len(samples.shape) == 2 and samples.shape[1] == 2:
                    samples = samples[:, 0] + 1j * samples[:, 1]
                samples = samples.astype(np.complex64)
            
            logger.info(f"Read {len(samples)} samples from DRF")
            
            # Pad/trim to exactly one day
            day_array = np.zeros(SAMPLES_PER_DAY, dtype=np.complex64)
            n_samples = min(len(samples), SAMPLES_PER_DAY)
            day_array[:n_samples] = samples[:n_samples]
            
            return day_array
            
        except Exception as e:
            logger.error(f"DRF read error: {e}")
            return None
    
    def _read_npz_day(self, date_dir: Path, date_yyyymmdd: str) -> Optional[np.ndarray]:
        """Fallback: Read day data from NPZ files."""
        # Look for NPZ files
        npz_files = sorted(date_dir.glob(f"*_iq_10hz.npz"))
        
        if not npz_files:
            logger.warning(f"No NPZ files found in {date_dir}")
            return None
        
        # Create day array
        day_array = np.zeros(SAMPLES_PER_DAY, dtype=np.complex64)
        samples_placed = 0
        
        for npz_file in npz_files:
            try:
                data = np.load(npz_file)
                iq = data['iq']
                
                # Parse timestamp from filename
                # Format: YYYYMMDDTHHMMSSZ_freq_iq_10hz.npz
                name = npz_file.stem
                time_str = name.split('_')[0]  # YYYYMMDDTHHMMSSZ
                file_time = datetime.strptime(time_str, '%Y%m%dT%H%M%SZ')
                file_time = file_time.replace(tzinfo=timezone.utc)
                
                # Calculate sample index
                day_start = datetime.strptime(date_yyyymmdd, '%Y%m%d').replace(tzinfo=timezone.utc)
                seconds_into_day = (file_time - day_start).total_seconds()
                sample_idx = int(seconds_into_day * SAMPLE_RATE_10HZ)
                
                if 0 <= sample_idx < SAMPLES_PER_DAY:
                    n_samples = min(len(iq), SAMPLES_PER_DAY - sample_idx)
                    day_array[sample_idx:sample_idx + n_samples] = iq[:n_samples]
                    samples_placed += n_samples
                    
            except Exception as e:
                logger.warning(f"Error reading {npz_file}: {e}")
        
        if samples_placed == 0:
            return None
        
        logger.info(f"Read {samples_placed} samples from {len(npz_files)} NPZ files")
        return day_array
    
    def _generate_daily_spectrogram(
        self,
        data: np.ndarray,
        date_obj: datetime,
        output_dir: Path
    ) -> Optional[Path]:
        """Generate 24-hour daily overview spectrogram."""
        if np.all(data == 0):
            logger.warning("No data for daily spectrogram")
            return None
        
        fig, ax = plt.subplots(
            figsize=(self.config.daily_width, self.config.daily_height)
        )
        
        # Compute spectrogram
        f, t, Sxx = signal.spectrogram(
            data,
            fs=SAMPLE_RATE_10HZ,
            nperseg=self.config.nfft,
            noverlap=self.config.noverlap,
            mode='magnitude'
        )
        
        # Convert to dB
        Sxx_db = 20 * np.log10(np.abs(Sxx) + 1e-10)
        
        # Plot
        im = ax.pcolormesh(
            t / 3600,  # Convert to hours
            f,
            Sxx_db,
            shading='auto',
            cmap=self.config.cmap,
            vmin=self.config.vmin_db,
            vmax=self.config.vmax_db
        )
        
        ax.set_xlabel('Time (UTC hours)')
        ax.set_ylabel('Frequency (Hz)')
        ax.set_title(f'{self.channel_name} - {date_obj.strftime("%Y-%m-%d")}')
        ax.set_xlim(0, 24)
        ax.set_ylim(0, SAMPLE_RATE_10HZ / 2)
        
        plt.colorbar(im, ax=ax, label='Power (dB)')
        plt.tight_layout()
        
        # Save
        output_path = output_dir / f'{date_obj.strftime("%Y%m%d")}_daily.png'
        plt.savefig(output_path, dpi=self.config.dpi)
        plt.close(fig)
        
        logger.info(f"Generated daily spectrogram: {output_path}")
        return output_path
    
    def _generate_hourly_spectrogram(
        self,
        data: np.ndarray,
        date_obj: datetime,
        hour: int,
        output_dir: Path
    ) -> Optional[Path]:
        """Generate spectrogram for a single hour."""
        # Extract hour's data
        start_idx = hour * SAMPLES_PER_HOUR
        end_idx = start_idx + SAMPLES_PER_HOUR
        hour_data = data[start_idx:end_idx]
        
        # Check if hour has data
        if np.all(hour_data == 0):
            return None
        
        fig, ax = plt.subplots(
            figsize=(self.config.hourly_width, self.config.hourly_height)
        )
        
        # Compute spectrogram
        f, t, Sxx = signal.spectrogram(
            hour_data,
            fs=SAMPLE_RATE_10HZ,
            nperseg=min(self.config.nfft, len(hour_data) // 4),
            noverlap=self.config.noverlap // 2,
            mode='magnitude'
        )
        
        Sxx_db = 20 * np.log10(np.abs(Sxx) + 1e-10)
        
        im = ax.pcolormesh(
            t / 60,  # Convert to minutes
            f,
            Sxx_db,
            shading='auto',
            cmap=self.config.cmap,
            vmin=self.config.vmin_db,
            vmax=self.config.vmax_db
        )
        
        ax.set_xlabel('Time (minutes)')
        ax.set_ylabel('Frequency (Hz)')
        ax.set_title(f'{self.channel_name} - {date_obj.strftime("%Y-%m-%d")} {hour:02d}:00 UTC')
        ax.set_xlim(0, 60)
        ax.set_ylim(0, SAMPLE_RATE_10HZ / 2)
        
        plt.colorbar(im, ax=ax, label='Power (dB)')
        plt.tight_layout()
        
        output_path = output_dir / f'{date_obj.strftime("%Y%m%d")}_{hour:02d}00.png'
        plt.savefig(output_path, dpi=self.config.dpi)
        plt.close(fig)
        
        return output_path
    
    def _generate_power_chart(
        self,
        data: np.ndarray,
        date_obj: datetime,
        output_dir: Path
    ) -> Optional[Path]:
        """Generate combined power profile and spectrogram chart."""
        if np.all(data == 0):
            return None
        
        fig, (ax1, ax2) = plt.subplots(
            2, 1,
            figsize=(self.config.daily_width, self.config.daily_height * 1.5),
            height_ratios=[1, 2],
            sharex=True
        )
        
        # Power profile (per-minute)
        n_minutes = SAMPLES_PER_DAY // SAMPLES_PER_MINUTE
        power_db = np.zeros(n_minutes)
        
        for i in range(n_minutes):
            start = i * SAMPLES_PER_MINUTE
            end = start + SAMPLES_PER_MINUTE
            minute_data = data[start:end]
            if not np.all(minute_data == 0):
                power_db[i] = 20 * np.log10(np.mean(np.abs(minute_data)) + 1e-10)
            else:
                power_db[i] = np.nan
        
        minutes = np.arange(n_minutes) / 60  # Hours
        ax1.plot(minutes, power_db, 'b-', linewidth=0.5)
        ax1.set_ylabel('Power (dB)')
        ax1.set_title(f'{self.channel_name} - {date_obj.strftime("%Y-%m-%d")} Power & Spectrogram')
        ax1.set_xlim(0, 24)
        ax1.grid(True, alpha=0.3)
        
        # Spectrogram
        f, t, Sxx = signal.spectrogram(
            data,
            fs=SAMPLE_RATE_10HZ,
            nperseg=self.config.nfft,
            noverlap=self.config.noverlap,
            mode='magnitude'
        )
        
        Sxx_db = 20 * np.log10(np.abs(Sxx) + 1e-10)
        
        im = ax2.pcolormesh(
            t / 3600,
            f,
            Sxx_db,
            shading='auto',
            cmap=self.config.cmap,
            vmin=self.config.vmin_db,
            vmax=self.config.vmax_db
        )
        
        ax2.set_xlabel('Time (UTC hours)')
        ax2.set_ylabel('Frequency (Hz)')
        ax2.set_ylim(0, SAMPLE_RATE_10HZ / 2)
        
        plt.colorbar(im, ax=ax2, label='Power (dB)')
        plt.tight_layout()
        
        output_path = output_dir / f'{date_obj.strftime("%Y%m%d")}_power.png'
        plt.savefig(output_path, dpi=self.config.dpi)
        plt.close(fig)
        
        logger.info(f"Generated power chart: {output_path}")
        return output_path
    
    def get_stats(self) -> Dict[str, Any]:
        """Get generator statistics."""
        # Count existing spectrograms
        spectrograms = list(self.output_dir.glob('**/*.png'))
        
        return {
            'channel_name': self.channel_name,
            'output_dir': str(self.output_dir),
            'total_spectrograms': len(spectrograms),
            'dates_processed': len(set(p.parent.name for p in spectrograms))
        }


def generate_spectrograms_for_day(
    data_root: Path,
    channel_name: str,
    date_str: str,
    config: Optional[SpectrogramConfig] = None
) -> Dict[str, Any]:
    """
    Convenience function to generate spectrograms for a single day.
    
    Args:
        data_root: Root data directory
        channel_name: Channel name
        date_str: Date string (YYYY-MM-DD or YYYYMMDD)
        config: Optional spectrogram configuration
        
    Returns:
        Dict with results
    """
    gen = SpectrogramGenerator(data_root, channel_name, config)
    return gen.generate_day(date_str)


# CLI interface
if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Generate spectrograms from Phase 3 decimated DRF data'
    )
    parser.add_argument('--data-root', type=Path, required=True,
                       help='Root data directory')
    parser.add_argument('--channel', type=str, required=True,
                       help='Channel name (e.g., "WWV 10 MHz")')
    parser.add_argument('--date', type=str, required=True,
                       help='Date to process (YYYY-MM-DD or YYYYMMDD)')
    parser.add_argument('--no-hourly', action='store_true',
                       help='Skip hourly spectrograms')
    parser.add_argument('--no-power', action='store_true',
                       help='Skip power chart')
    
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    config = SpectrogramConfig(
        generate_hourly=not args.no_hourly,
        generate_power_chart=not args.no_power
    )
    
    results = generate_spectrograms_for_day(
        args.data_root,
        args.channel,
        args.date,
        config
    )
    
    print(f"Generated {len(results['spectrograms_generated'])} spectrograms")
    if results['errors']:
        print(f"Errors: {results['errors']}")
