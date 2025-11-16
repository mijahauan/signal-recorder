#!/usr/bin/env python3
"""
Digital RF Writer Service

Simple, isolated service that converts pre-decimated 10 Hz NPZ files to Digital RF format.

Input: *_iq_10hz.npz files (output from analytics/decimation service)
Output: Digital RF HDF5 files for upload

This service ONLY does format conversion - no decimation, no tone detection.
All upstream processing (tone detection, decimation, quality metrics) happens
in the analytics service before creating the 10Hz NPZ files.
"""

import argparse
import logging
import time
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
import numpy as np

try:
    import digital_rf as drf
    DRF_AVAILABLE = True
except ImportError:
    DRF_AVAILABLE = False
    logging.error("digital_rf not available - this service requires it")

logger = logging.getLogger(__name__)


@dataclass
class TimeSnapReference:
    """Time anchor from WWV/CHU tone detection (loaded from analytics state)"""
    rtp_timestamp: int
    utc_timestamp: float
    sample_rate: int
    source: str
    confidence: float
    station: str
    
    def calculate_sample_time(self, rtp_timestamp: int) -> float:
        """Calculate UTC timestamp for a given RTP timestamp"""
        # Handle RTP timestamp wrap-around (32-bit unsigned)
        rtp_elapsed = (rtp_timestamp - self.rtp_timestamp) & 0xFFFFFFFF
        # Handle large negative offsets (wrap-around detection)
        if rtp_elapsed > 0x80000000:
            rtp_elapsed -= 0x100000000
        
        elapsed_seconds = rtp_elapsed / self.sample_rate
        return self.utc_timestamp + elapsed_seconds


@dataclass
class DecimatedArchive:
    """
    Parsed 10 Hz decimated NPZ file with optional metadata
    
    Core fields (always present):
        - iq_samples, rtp_timestamp, sample rates, timestamps
    
    Optional metadata fields (for future expansion):
        - timing_metadata: timing quality, time_snap age, ntp offset
        - quality_metadata: completeness, packet loss, gaps
        - discrimination_metadata: WWV/WWVH analysis results
    """
    file_path: Path
    iq_samples: np.ndarray
    rtp_timestamp: int
    sample_rate_original: int
    sample_rate_decimated: int
    decimation_factor: int
    created_timestamp: float
    source_file: str
    
    # Optional metadata (future expansion)
    timing_metadata: Optional[Dict[str, Any]] = None
    quality_metadata: Optional[Dict[str, Any]] = None
    discrimination_metadata: Optional[Dict[str, Any]] = None
    
    @classmethod
    def load(cls, file_path: Path) -> 'DecimatedArchive':
        """
        Load a 10Hz decimated NPZ archive
        
        Supports both current format (just IQ data) and future enhanced format
        with embedded timing/quality/discrimination metadata
        """
        data = np.load(file_path, allow_pickle=True)
        
        # Load optional metadata if present
        timing_metadata = data.get('timing_metadata', None)
        if timing_metadata is not None and hasattr(timing_metadata, 'item'):
            timing_metadata = timing_metadata.item()  # Convert numpy object to dict
        
        quality_metadata = data.get('quality_metadata', None)
        if quality_metadata is not None and hasattr(quality_metadata, 'item'):
            quality_metadata = quality_metadata.item()
        
        discrimination_metadata = data.get('discrimination_metadata', None)
        if discrimination_metadata is not None and hasattr(discrimination_metadata, 'item'):
            discrimination_metadata = discrimination_metadata.item()
        
        return cls(
            file_path=file_path,
            iq_samples=data['iq_decimated'],
            rtp_timestamp=int(data['rtp_timestamp']),
            sample_rate_original=int(data['sample_rate_original']),
            sample_rate_decimated=int(data['sample_rate_decimated']),
            decimation_factor=int(data['decimation_factor']),
            created_timestamp=float(data['created_timestamp']),
            source_file=str(data['source_file']),
            timing_metadata=timing_metadata,
            quality_metadata=quality_metadata,
            discrimination_metadata=discrimination_metadata
        )
    
    def calculate_utc_timestamp(self, time_snap: Optional[TimeSnapReference]) -> float:
        """Calculate UTC timestamp using time_snap or fall back to creation time"""
        if time_snap:
            # Use precise RTP-to-UTC conversion
            return time_snap.calculate_sample_time(self.rtp_timestamp)
        else:
            # Fall back to file creation timestamp
            logger.warning(f"No time_snap available, using creation timestamp")
            return self.created_timestamp


class DRFWriterService:
    """
    Service that converts 10 Hz decimated NPZ files to Digital RF format
    
    Architecture:
    - Watches input directory for *_iq_10hz.npz files
    - Loads time_snap from analytics state file
    - Writes data in strict chronological order
    - Maintains monotonic sample indices
    """
    
    def __init__(self, input_dir: Path, output_dir: Path, channel_name: str,
                 frequency_hz: float, analytics_state_file: Path,
                 station_config: dict):
        
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.channel_name = channel_name
        self.frequency_hz = frequency_hz
        self.analytics_state_file = analytics_state_file
        self.station_config = station_config
        
        self.sample_rate = 10  # 10 Hz decimated data
        self.running = False
        
        # DRF writer state
        self.drf_writer: Optional[drf.DigitalRFWriter] = None
        self.metadata_writers: Dict[str, drf.DigitalMetadataWriter] = {}
        self.current_day: Optional[datetime] = None
        self.next_index: Optional[int] = None
        self.dataset_uuid = station_config.get('psws_station_id', 'UNKNOWN')
        
        # Service state
        self.state_file = output_dir / 'drf_writer_state.json'
        self.last_processed_file: Optional[Path] = None
        self.files_processed = 0
        
        # Load state if exists
        self._load_state()
        
        logger.info(f"DRF Writer Service initialized")
        logger.info(f"  Input: {input_dir}")
        logger.info(f"  Output: {output_dir}")
        logger.info(f"  Channel: {channel_name} @ {frequency_hz/1e6:.2f} MHz")
    
    def _load_state(self):
        """Load service state from disk"""
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    state = json.load(f)
                self.last_processed_file = Path(state.get('last_processed_file')) if state.get('last_processed_file') else None
                self.files_processed = state.get('files_processed', 0)
                self.next_index = state.get('next_index')
                logger.info(f"Loaded state: {self.files_processed} files processed")
            except Exception as e:
                logger.warning(f"Could not load state: {e}")
    
    def _save_state(self):
        """Save service state to disk"""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            state = {
                'last_processed_file': str(self.last_processed_file) if self.last_processed_file else None,
                'files_processed': self.files_processed,
                'next_index': self.next_index,
                'last_save_time': time.time()
            }
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
    
    def _load_time_snap(self) -> Optional[TimeSnapReference]:
        """Load current time_snap from analytics state file"""
        if not self.analytics_state_file.exists():
            logger.debug("Analytics state file not found - no time_snap available")
            return None
        
        try:
            with open(self.analytics_state_file) as f:
                state = json.load(f)
            
            ts_data = state.get('time_snap')
            if not ts_data:
                return None
            
            return TimeSnapReference(
                rtp_timestamp=ts_data['rtp_timestamp'],
                utc_timestamp=ts_data['utc_timestamp'],
                sample_rate=ts_data['sample_rate'],
                source=ts_data['source'],
                confidence=ts_data['confidence'],
                station=ts_data['station']
            )
        except Exception as e:
            logger.warning(f"Could not load time_snap: {e}")
            return None
    
    def discover_new_files(self) -> List[Path]:
        """
        Discover new 10Hz NPZ files to process
        
        Returns files in strict chronological order to ensure monotonic DRF writes
        """
        # Find all 10Hz decimated NPZ files
        all_files = list(self.input_dir.glob('*_iq_10hz.npz'))
        
        # Filter to new files (after last processed)
        if self.last_processed_file:
            # Use filename comparison for strict chronological order
            last_name = self.last_processed_file.name
            new_files = [f for f in all_files if f.name > last_name]
        else:
            # First run - process all files
            new_files = all_files
        
        # CRITICAL: Sort by filename (ISO timestamp) to ensure chronological order
        new_files = sorted(new_files, key=lambda f: f.name)
        
        logger.debug(f"Discovered {len(new_files)} new 10Hz files")
        return new_files
    
    def _create_drf_writer(self, timestamp: float):
        """Create Digital RF writer for current day"""
        day_date = datetime.fromtimestamp(timestamp, tz=timezone.utc).date()
        
        # Check if we need a new writer
        if self.current_day == day_date and self.drf_writer:
            return
        
        # Close old writer if exists
        if self.drf_writer:
            self.drf_writer = None
            logger.info(f"Closed Digital RF writer for {self.current_day}")
        
        # Create directory structure
        safe_channel_name = self.channel_name.replace(' ', '_')
        drf_dir = self.output_dir / 'digital_rf' / day_date.strftime('%Y%m%d') / \
                  f"{self.station_config['callsign']}_{self.station_config['grid_square']}" / \
                  f"{self.station_config['receiver_name']}@{self.station_config['psws_station_id']}_{self.station_config['psws_instrument_id']}" / \
                  f"OBS{day_date.isoformat()}T00-00" / safe_channel_name
        
        drf_dir.mkdir(parents=True, exist_ok=True)
        
        # Calculate start_global_index
        start_global_index = int(timestamp * self.sample_rate)
        
        logger.info(f"Creating Digital RF writer for {day_date}")
        logger.info(f"  Directory: {drf_dir}")
        logger.info(f"  Start index: {start_global_index}")
        
        # Create main data channel (IQ samples at 10 Hz)
        self.drf_writer = drf.DigitalRFWriter(
            str(drf_dir),
            dtype=np.complex64,
            subdir_cadence_secs=86400,
            file_cadence_millisecs=3600000,
            start_global_index=start_global_index,
            sample_rate_numerator=self.sample_rate,
            sample_rate_denominator=1,
            uuid_str=self.dataset_uuid,
            compression_level=9,
            checksum=False,
            is_complex=True,
            num_subchannels=1,
            is_continuous=True,
            marching_periods=False
        )
        
        # Create metadata writers for parallel channels
        metadata_base = drf_dir / "metadata"
        metadata_base.mkdir(parents=True, exist_ok=True)
        
        # Timing metadata channel
        timing_metadata_dir = metadata_base / "timing_quality"
        timing_metadata_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_writers['timing'] = drf.DigitalMetadataWriter(
            metadata_dir=str(timing_metadata_dir),
            subdir_cadence_secs=3600,  # 1 hour subdirectories
            file_cadence_secs=60,       # 1 minute files
            sample_rate_numerator=self.sample_rate,
            sample_rate_denominator=1,
            file_name="timing_quality"
        )
        
        # Quality metadata channel
        quality_metadata_dir = metadata_base / "data_quality"
        quality_metadata_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_writers['quality'] = drf.DigitalMetadataWriter(
            metadata_dir=str(quality_metadata_dir),
            subdir_cadence_secs=3600,
            file_cadence_secs=60,
            sample_rate_numerator=self.sample_rate,
            sample_rate_denominator=1,
            file_name="data_quality"
        )
        
        # WWV-H discrimination metadata channel (future expansion)
        # Will contain: wwv_detected, wwvh_detected, power_ratio_db, 
        #               differential_delay_ms, dominant_station, confidence
        self.metadata_writers['discrimination'] = drf.DigitalMetadataWriter(
            str(metadata_base),
            subdir_cadence_secs=86400,
            file_cadence_secs=3600,
            sample_rate_numerator=self.sample_rate,
            sample_rate_denominator=1,
            file_name='wwvh_discrimination'
        )
        
        # Station/receiver metadata (static info)
        self.metadata_writers['station'] = drf.DigitalMetadataWriter(
            str(metadata_dir),
            subdir_cadence_secs=86400,
            file_cadence_secs=86400,  # Daily file
            sample_rate_numerator=self.sample_rate,
            sample_rate_denominator=1,
            file_name='station_info'
        )
        
        # Write initial station metadata (once per day)
        station_metadata = {
            'callsign': self.station_config['callsign'],
            'grid_square': self.station_config['grid_square'],
            'receiver_name': self.station_config['receiver_name'],
            'psws_station_id': self.station_config['psws_station_id'],
            'psws_instrument_id': self.station_config['psws_instrument_id'],
            'center_frequency_hz': self.frequency_hz,
            'channel_name': self.channel_name,
            'sample_rate_hz': self.sample_rate,
            'data_type': 'complex64',
            'processing_chain': 'GRAPE_V2 -> Analytics -> DRF_Writer',
            'date': day_date.isoformat()
        }
        self.metadata_writers['station'].write(start_global_index, station_metadata)
        
        self.current_day = day_date
        
        # Initialize monotonic index if not set
        if self.next_index is None:
            self.next_index = start_global_index
        
        logger.info(f"✅ Digital RF writer ready (next_index={self.next_index})")
        logger.info(f"   Metadata channels: {list(self.metadata_writers.keys())}")
    
    def write_to_drf(self, archive: DecimatedArchive, time_snap: Optional[TimeSnapReference]):
        """Write decimated samples to Digital RF"""
        try:
            # Calculate UTC timestamp
            utc_timestamp = archive.calculate_utc_timestamp(time_snap)
            
            # Create writer for this day if needed
            self._create_drf_writer(utc_timestamp)
            
            if not self.drf_writer:
                logger.error("Failed to create DRF writer")
                return
            
            # Calculate sample index
            calculated_index = int(utc_timestamp * self.sample_rate)
            
            # CRITICAL: Check for backwards time jump (out-of-order archive)
            if calculated_index < self.next_index:
                logger.warning(f"⚠️  Archive out of order! "
                             f"Calculated index {calculated_index} < next_index {self.next_index}. "
                             f"Skipping {archive.file_path.name} to maintain monotonic sequence.")
                return
            
            # Write samples to main data channel
            self.drf_writer.rf_write(archive.iq_samples, int(self.next_index))
            
            # Write metadata to parallel channels (if present in archive)
            self._write_metadata_channels(archive, self.next_index)
            
            # Advance index monotonically
            self.next_index += len(archive.iq_samples)
            
            logger.debug(f"Wrote {len(archive.iq_samples)} samples (index now {self.next_index})")
            
        except Exception as e:
            logger.error(f"DRF write error: {e}", exc_info=True)
    
    def _write_metadata_channels(self, archive: DecimatedArchive, sample_index: int):
        """
        Write metadata to parallel Digital RF metadata channels
        
        This follows Digital RF spec for multi-channel data with metadata.
        Currently, metadata is optional in 10Hz files. When analytics service
        starts embedding it, this will automatically write it to DRF.
        """
        try:
            # Timing quality metadata
            if archive.timing_metadata and 'timing' in self.metadata_writers:
                self.metadata_writers['timing'].write(sample_index, archive.timing_metadata)
            
            # Data quality metadata
            if archive.quality_metadata and 'quality' in self.metadata_writers:
                self.metadata_writers['quality'].write(sample_index, archive.quality_metadata)
            
            # WWV-H discrimination metadata
            if archive.discrimination_metadata and 'discrimination' in self.metadata_writers:
                self.metadata_writers['discrimination'].write(sample_index, archive.discrimination_metadata)
                
        except Exception as e:
            # Non-fatal - log but continue
            logger.warning(f"Failed to write metadata: {e}")
    
    def run(self, poll_interval: float = 10.0):
        """Main processing loop"""
        logger.info("DRF Writer Service started")
        self.running = True
        
        try:
            while self.running:
                try:
                    # Load current time_snap from analytics
                    time_snap = self._load_time_snap()
                    if time_snap:
                        logger.debug(f"Time snap: {time_snap.source} @ {time_snap.utc_timestamp}")
                    
                    # Discover new files
                    new_files = self.discover_new_files()
                    
                    if not new_files:
                        logger.debug("No new files to process")
                    
                    # Process each file
                    for file_path in new_files:
                        if not self.running:
                            break
                        
                        try:
                            # Load decimated archive
                            archive = DecimatedArchive.load(file_path)
                            
                            # Write to DRF
                            self.write_to_drf(archive, time_snap)
                            
                            # Update state
                            self.last_processed_file = file_path
                            self.files_processed += 1
                            
                            # Save state periodically
                            if self.files_processed % 10 == 0:
                                self._save_state()
                            
                            logger.info(f"✅ Processed: {file_path.name}")
                            
                        except Exception as e:
                            logger.error(f"Failed to process {file_path}: {e}", exc_info=True)
                            continue
                    
                    # Save state after batch
                    if new_files:
                        self._save_state()
                    
                    # Sleep until next poll
                    time.sleep(poll_interval)
                    
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    logger.error(f"Error in main loop: {e}", exc_info=True)
                    time.sleep(poll_interval)
        
        except KeyboardInterrupt:
            logger.info("Shutdown requested")
        finally:
            self.running = False
            self._save_state()
            logger.info(f"DRF Writer Service stopped ({self.files_processed} files processed)")


def main():
    parser = argparse.ArgumentParser(
        description='Digital RF Writer Service - Convert 10Hz NPZ to Digital RF'
    )
    
    parser.add_argument('--input-dir', required=True, type=Path,
                       help='Input directory with *_iq_10hz.npz files')
    parser.add_argument('--output-dir', required=True, type=Path,
                       help='Output directory for Digital RF files')
    parser.add_argument('--channel-name', required=True,
                       help='Channel name (e.g., "WWV 5 MHz")')
    parser.add_argument('--frequency-hz', required=True, type=float,
                       help='Center frequency in Hz')
    parser.add_argument('--analytics-state-file', required=True, type=Path,
                       help='Path to analytics state file (for time_snap)')
    parser.add_argument('--poll-interval', type=float, default=10.0,
                       help='Polling interval in seconds')
    parser.add_argument('--log-level', default='INFO',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'])
    
    # Station metadata
    parser.add_argument('--callsign', required=True, help='Station callsign')
    parser.add_argument('--grid-square', required=True, help='Grid square')
    parser.add_argument('--receiver-name', default='GRAPE', help='Receiver name')
    parser.add_argument('--psws-station-id', required=True, help='PSWS station ID')
    parser.add_argument('--psws-instrument-id', required=True, help='PSWS instrument ID')
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    if not DRF_AVAILABLE:
        logger.error("digital_rf module not available - cannot run")
        return 1
    
    # Build station config
    station_config = {
        'callsign': args.callsign,
        'grid_square': args.grid_square,
        'receiver_name': args.receiver_name,
        'psws_station_id': args.psws_station_id,
        'psws_instrument_id': args.psws_instrument_id
    }
    
    # Create service
    service = DRFWriterService(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        channel_name=args.channel_name,
        frequency_hz=args.frequency_hz,
        analytics_state_file=args.analytics_state_file,
        station_config=station_config
    )
    
    # Run
    return service.run(poll_interval=args.poll_interval) or 0


if __name__ == '__main__':
    exit(main())
