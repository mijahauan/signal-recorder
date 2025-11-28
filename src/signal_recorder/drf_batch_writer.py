#!/usr/bin/env python3
"""
DRF Batch Writer - Multi-subchannel Digital RF writer for daily uploads

Creates wsprdaemon-compatible Digital RF datasets with all frequency channels
combined into a single ch0 with multiple subchannels.

Structure matches wsprdaemon/wav2grape.py:
- Single ch0 directory
- IQ data horizontally stacked: [freq1_IQ | freq2_IQ | ... | freq9_IQ]
- center_frequencies metadata as array of all frequencies
- Optional extended metadata (time_snap, gap analysis)
"""

import argparse
import json
import logging
import numpy as np
import sys
import uuid
from datetime import datetime, timezone, date
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

try:
    import digital_rf as drf
    DRF_AVAILABLE = True
except ImportError:
    DRF_AVAILABLE = False
    print("WARNING: digital_rf not available", file=sys.stderr)

logger = logging.getLogger(__name__)


@dataclass
class ChannelConfig:
    """Configuration for a single frequency channel"""
    name: str
    frequency_hz: float
    decimated_dir: Path
    analytics_state_file: Path


@dataclass 
class TimeSlice:
    """IQ data for all channels at a specific timestamp"""
    timestamp: float  # UTC timestamp
    rtp_timestamp: int
    samples_per_channel: int
    channel_data: Dict[str, np.ndarray]  # channel_name -> IQ samples
    timing_metadata: Optional[Dict] = None
    quality_metadata: Optional[Dict] = None


def maidenhead_to_lat_long(grid: str) -> Tuple[float, float]:
    """Convert Maidenhead grid square to latitude/longitude"""
    grid = grid.upper()
    lon = (ord(grid[0]) - ord('A')) * 20 + (ord(grid[2]) - ord('0')) * 2 - 180
    lat = (ord(grid[1]) - ord('A')) * 10 + (ord(grid[3]) - ord('0')) - 90
    if len(grid) >= 6:
        lon += (ord(grid[4]) - ord('A')) * 5.0 / 60.0
        lat += (ord(grid[5]) - ord('A')) * 2.5 / 60.0
        if len(grid) >= 8:
            lon += (ord(grid[6]) - ord('0')) * 30.0 / 3600.0
            lat += (ord(grid[7]) - ord('0')) * 15.0 / 3600.0
    return lat, lon


class DRFBatchWriter:
    """
    Multi-subchannel Digital RF batch writer
    
    Combines multiple frequency channels into a single ch0 with subchannels,
    matching the wsprdaemon format expected by PSWS.
    """
    
    def __init__(
        self,
        channels: List[ChannelConfig],
        output_dir: Path,
        station_config: Dict,
        include_extended_metadata: bool = False
    ):
        self.channels = sorted(channels, key=lambda c: c.frequency_hz)  # Sort by frequency
        self.output_dir = Path(output_dir)
        self.station_config = station_config
        self.include_extended_metadata = include_extended_metadata
        
        self.sample_rate = 10  # 10 Hz decimated data
        self.num_subchannels = len(channels)
        self.frequencies = [c.frequency_hz for c in self.channels]
        
        # DRF configuration matching wsprdaemon
        self.subdir_cadence_secs = 86400  # Daily subdirectories
        self.file_cadence_millisecs = 3600000  # Hourly files
        self.compression_level = 0  # No compression for speed
        
        self.dataset_uuid = station_config.get('psws_station_id', uuid.uuid4().hex)
        
        logger.info(f"DRF Batch Writer initialized")
        logger.info(f"  Channels: {self.num_subchannels}")
        logger.info(f"  Frequencies: {self.frequencies}")
        logger.info(f"  Extended metadata: {include_extended_metadata}")
    
    def discover_files_for_date(self, target_date: date) -> Dict[str, List[Path]]:
        """
        Discover all decimated NPZ files for a specific date, grouped by channel
        
        Returns: {channel_name: [file_paths sorted by time]}
        """
        date_prefix = target_date.strftime('%Y%m%d')
        files_by_channel = {}
        
        for channel in self.channels:
            pattern = f"{date_prefix}T*_iq_10hz.npz"
            files = sorted(channel.decimated_dir.glob(pattern))
            files_by_channel[channel.name] = files
            logger.info(f"  {channel.name}: {len(files)} files")
        
        return files_by_channel
    
    def load_aligned_time_slices(
        self, 
        files_by_channel: Dict[str, List[Path]]
    ) -> List[TimeSlice]:
        """
        Load and align IQ data from all channels by timestamp
        
        Returns time slices where ALL channels have data at that timestamp.
        """
        # Build timestamp -> {channel: file_path} mapping
        timestamp_map = {}
        
        for channel_name, files in files_by_channel.items():
            for file_path in files:
                # Extract timestamp from filename: YYYYMMDDTHHMMSSZ_freq_iq_10hz.npz
                filename = file_path.stem
                time_part = filename.split('_')[0]  # YYYYMMDDTHHMMSSZ
                
                if time_part not in timestamp_map:
                    timestamp_map[time_part] = {}
                timestamp_map[time_part][channel_name] = file_path
        
        # Filter to timestamps where ALL channels have data
        all_channel_names = set(c.name for c in self.channels)
        complete_timestamps = sorted([
            ts for ts, channels in timestamp_map.items()
            if set(channels.keys()) == all_channel_names
        ])
        
        logger.info(f"Found {len(complete_timestamps)} complete time slices (all {self.num_subchannels} channels)")
        
        # Load data for complete timestamps
        time_slices = []
        for ts in complete_timestamps:
            try:
                slice_data = self._load_time_slice(ts, timestamp_map[ts])
                if slice_data:
                    time_slices.append(slice_data)
            except Exception as e:
                logger.warning(f"Failed to load time slice {ts}: {e}")
                continue
        
        return time_slices
    
    def _load_time_slice(
        self, 
        timestamp_str: str, 
        channel_files: Dict[str, Path]
    ) -> Optional[TimeSlice]:
        """Load IQ data for all channels at a specific timestamp"""
        channel_data = {}
        utc_timestamp = None
        rtp_timestamp = None
        samples_per_channel = None
        timing_metadata = None
        quality_metadata = None
        
        for channel in self.channels:
            file_path = channel_files[channel.name]
            data = np.load(file_path, allow_pickle=True)
            
            iq = data['iq']
            
            # Validate consistent sample count
            if samples_per_channel is None:
                samples_per_channel = len(iq)
            elif len(iq) != samples_per_channel:
                logger.warning(f"Sample count mismatch in {file_path}: {len(iq)} vs {samples_per_channel}")
                return None
            
            # Get timestamp from first file
            if utc_timestamp is None:
                utc_timestamp = float(data['created_timestamp'])
                rtp_timestamp = int(data['rtp_timestamp'])
                
                # Load extended metadata if enabled
                if self.include_extended_metadata:
                    if 'timing_metadata' in data.files:
                        timing_metadata = data['timing_metadata'].item()
                    if 'quality_metadata' in data.files:
                        quality_metadata = data['quality_metadata'].item()
            
            channel_data[channel.name] = iq.astype(np.complex64)
        
        return TimeSlice(
            timestamp=utc_timestamp,
            rtp_timestamp=rtp_timestamp,
            samples_per_channel=samples_per_channel,
            channel_data=channel_data,
            timing_metadata=timing_metadata,
            quality_metadata=quality_metadata
        )
    
    def write_drf_dataset(
        self,
        target_date: date,
        time_slices: List[TimeSlice]
    ) -> Optional[Path]:
        """
        Write complete DRF dataset for a day
        
        Creates wsprdaemon-compatible structure:
        - OBS{date}T00-00/ch0/
        - All frequencies as subchannels in single ch0
        """
        if not time_slices:
            logger.error("No time slices to write")
            return None
        
        if not DRF_AVAILABLE:
            logger.error("digital_rf not available")
            return None
        
        # Build output directory structure
        # Note: output_dir should already include the date level (e.g., /upload/20251128)
        obs_date = target_date.strftime('%Y-%m-%dT00-00')
        obs_dir_name = f"OBS{obs_date}"
        
        station = self.station_config
        drf_base = self.output_dir / \
                   f"{station['callsign']}_{station['grid_square']}" / \
                   f"{station['receiver_name']}@{station['psws_station_id']}_{station['psws_instrument_id']}" / \
                   obs_dir_name
        
        channel_dir = drf_base / "ch0"
        channel_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Writing DRF dataset to: {channel_dir}")
        
        # Calculate start index from first timestamp
        first_ts = time_slices[0].timestamp
        start_global_index = int(first_ts * self.sample_rate)
        
        # Prepare stacked IQ data for all time slices
        # Shape: (total_samples, 2, num_subchannels) -> flatten to (total_samples, 2 * num_subchannels)
        all_samples = []
        
        for ts in time_slices:
            # Stack channels horizontally: [ch1_I, ch1_Q, ch2_I, ch2_Q, ...]
            slice_samples = []
            for channel in self.channels:
                iq = ts.channel_data[channel.name]
                # Convert complex to float32 [I, Q] pairs
                iq_float = np.zeros((len(iq), 2), dtype=np.float32)
                iq_float[:, 0] = iq.real
                iq_float[:, 1] = iq.imag
                slice_samples.append(iq_float)
            
            # Horizontal stack: (samples, 2 * num_channels)
            stacked = np.hstack(slice_samples)
            all_samples.append(stacked)
        
        # Concatenate all time slices
        all_data = np.vstack(all_samples)
        total_samples = len(all_data)
        
        logger.info(f"  Total samples: {total_samples}")
        logger.info(f"  Data shape: {all_data.shape}")
        logger.info(f"  Start index: {start_global_index}")
        
        # Write DRF dataset
        try:
            writer = drf.DigitalRFWriter(
                str(channel_dir),
                'f4',  # float32
                self.subdir_cadence_secs,
                self.file_cadence_millisecs,
                start_global_index,
                self.sample_rate,  # sample_rate_numerator
                1,                  # sample_rate_denominator
                self.dataset_uuid,
                self.compression_level,
                False,              # checksum
                True,               # is_complex
                self.num_subchannels,
                True,               # is_continuous
                False               # marching_periods
            )
            
            writer.rf_write(all_data)
            writer.close()
            
            logger.info(f"✅ Wrote {total_samples} samples to DRF")
            
        except Exception as e:
            logger.error(f"Failed to write DRF data: {e}", exc_info=True)
            return None
        
        # Write metadata
        self._write_metadata(channel_dir, start_global_index, time_slices)
        
        return drf_base
    
    def _write_metadata(
        self,
        channel_dir: Path,
        start_global_index: int,
        time_slices: List[TimeSlice]
    ):
        """Write metadata to DRF dataset"""
        metadata_dir = channel_dir / "metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)
        
        # Get lat/long from grid square
        lat, lon = maidenhead_to_lat_long(self.station_config['grid_square'])
        
        # Base metadata (wsprdaemon compatible)
        metadata = {
            'callsign': self.station_config['callsign'],
            'grid_square': self.station_config['grid_square'],
            'receiver_name': self.station_config['receiver_name'],
            'lat': np.float32(lat),
            'long': np.float32(lon),
            'center_frequencies': np.ascontiguousarray(self.frequencies, dtype=np.float64),
            'uuid_str': self.dataset_uuid
        }
        
        logger.info(f"📝 Writing metadata:")
        logger.info(f"   callsign: {metadata['callsign']}")
        logger.info(f"   grid_square: {metadata['grid_square']}")
        logger.info(f"   lat/long: {lat:.4f}, {lon:.4f}")
        logger.info(f"   center_frequencies: {self.frequencies}")
        
        # Write base metadata
        try:
            md_writer = drf.DigitalMetadataWriter(
                str(metadata_dir),
                self.subdir_cadence_secs,
                self.subdir_cadence_secs,  # file_cadence_secs
                self.sample_rate,
                1,
                'metadata'
            )
            md_writer.write(start_global_index, metadata)
            logger.info("✅ Base metadata written")
        except Exception as e:
            logger.error(f"Failed to write metadata: {e}")
        
        # Extended metadata (if enabled)
        if self.include_extended_metadata:
            self._write_extended_metadata(channel_dir, time_slices)
    
    def _write_extended_metadata(
        self,
        channel_dir: Path,
        time_slices: List[TimeSlice]
    ):
        """Write extended metadata (timing quality, gap analysis)"""
        extended_dir = channel_dir / "metadata" / "extended"
        extended_dir.mkdir(parents=True, exist_ok=True)
        
        # Collect timing and quality data
        extended_data = {
            'time_slices': len(time_slices),
            'timing_samples': [],
            'quality_samples': [],
            'gaps': []
        }
        
        prev_ts = None
        for ts in time_slices:
            if ts.timing_metadata:
                extended_data['timing_samples'].append({
                    'timestamp': ts.timestamp,
                    'data': ts.timing_metadata
                })
            
            if ts.quality_metadata:
                extended_data['quality_samples'].append({
                    'timestamp': ts.timestamp,
                    'data': ts.quality_metadata
                })
            
            # Detect gaps
            if prev_ts is not None:
                expected_gap = 60.0  # 1 minute between files
                actual_gap = ts.timestamp - prev_ts
                if abs(actual_gap - expected_gap) > 5.0:  # >5 second deviation
                    extended_data['gaps'].append({
                        'start': prev_ts,
                        'end': ts.timestamp,
                        'duration': actual_gap
                    })
            prev_ts = ts.timestamp
        
        # Write as JSON for now (can convert to HDF5 metadata later)
        extended_file = extended_dir / "extended_metadata.json"
        with open(extended_file, 'w') as f:
            json.dump(extended_data, f, indent=2, default=str)
        
        logger.info(f"✅ Extended metadata written: {len(extended_data['gaps'])} gaps detected")


def process_day(
    target_date: date,
    analytics_root: Path,
    output_dir: Path,
    station_config: Dict,
    include_extended_metadata: bool = False
) -> Optional[Path]:
    """
    Process a full day's data from all channels into a single DRF dataset
    
    Returns path to OBS directory if successful, None otherwise
    """
    # Discover channels from analytics directory
    channels = []
    
    for channel_dir in sorted(analytics_root.iterdir()):
        if not channel_dir.is_dir():
            continue
        
        decimated_dir = channel_dir / "decimated"
        if not decimated_dir.exists():
            continue
        
        # Extract frequency from channel name
        channel_name = channel_dir.name
        freq_match = None
        
        # Try to extract frequency (handles both "WWV_10_MHz" and "CHU_14.67_MHz")
        import re
        match = re.search(r'([\d.]+)_MHz', channel_name)
        if match:
            freq_mhz = float(match.group(1))
            freq_hz = freq_mhz * 1_000_000
        else:
            logger.warning(f"Could not extract frequency from {channel_name}, skipping")
            continue
        
        channels.append(ChannelConfig(
            name=channel_name,
            frequency_hz=freq_hz,
            decimated_dir=decimated_dir,
            analytics_state_file=channel_dir / "status" / "analytics-service-status.json"
        ))
    
    if not channels:
        logger.error("No channels found")
        return None
    
    logger.info(f"Found {len(channels)} channels")
    
    # Create batch writer
    writer = DRFBatchWriter(
        channels=channels,
        output_dir=output_dir,
        station_config=station_config,
        include_extended_metadata=include_extended_metadata
    )
    
    # Discover files for target date
    files_by_channel = writer.discover_files_for_date(target_date)
    
    # Check we have data
    total_files = sum(len(f) for f in files_by_channel.values())
    if total_files == 0:
        logger.error(f"No files found for {target_date}")
        return None
    
    # Load aligned time slices
    time_slices = writer.load_aligned_time_slices(files_by_channel)
    
    if not time_slices:
        logger.error("No complete time slices (missing channels)")
        return None
    
    # Write DRF dataset
    obs_dir = writer.write_drf_dataset(target_date, time_slices)
    
    return obs_dir


def main():
    parser = argparse.ArgumentParser(
        description='DRF Batch Writer - Create multi-subchannel Digital RF datasets'
    )
    
    parser.add_argument('--analytics-root', required=True, type=Path,
                       help='Root directory containing channel analytics directories')
    parser.add_argument('--output-dir', required=True, type=Path,
                       help='Output directory for DRF dataset')
    parser.add_argument('--date', required=True,
                       help='Target date (YYYY-MM-DD)')
    
    # Station metadata
    parser.add_argument('--callsign', required=True)
    parser.add_argument('--grid-square', required=True)
    parser.add_argument('--receiver-name', default='GRAPE')
    parser.add_argument('--psws-station-id', required=True)
    parser.add_argument('--psws-instrument-id', required=True)
    
    parser.add_argument('--include-extended-metadata', action='store_true',
                       help='Include timing quality and gap analysis metadata')
    parser.add_argument('--log-level', default='INFO',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(levelname)s:%(name)s:%(message)s'
    )
    
    # Parse date
    target_date = datetime.strptime(args.date, '%Y-%m-%d').date()
    
    # Build station config
    station_config = {
        'callsign': args.callsign,
        'grid_square': args.grid_square,
        'receiver_name': args.receiver_name,
        'psws_station_id': args.psws_station_id,
        'psws_instrument_id': args.psws_instrument_id
    }
    
    logger.info(f"Processing {target_date} for station {args.callsign}")
    
    # Process
    obs_dir = process_day(
        target_date=target_date,
        analytics_root=args.analytics_root,
        output_dir=args.output_dir,
        station_config=station_config,
        include_extended_metadata=args.include_extended_metadata
    )
    
    if obs_dir:
        print(f"SUCCESS: {obs_dir}")
        return 0
    else:
        print("FAILED")
        return 1


if __name__ == '__main__':
    sys.exit(main())
