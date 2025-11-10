#!/usr/bin/env python3
"""
Analytics Service - Process NPZ Archives to Derived Products

Watches for new NPZ files from core recorder and generates:
1. Quality metrics (completeness, gaps, packet loss)
2. WWV/CHU/WWVH tone detection → time_snap establishment
3. Discontinuity logs (scientific provenance)
4. Decimated Digital RF (10 Hz)
5. Upload queue management

Design Philosophy:
- Independent from core recorder (can restart without data loss)
- Reprocessable (can rerun with improved algorithms)
- Crash-tolerant (systemd restarts, aggressive retry)
"""

import numpy as np
import logging
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field
from collections import deque
from scipy import signal as scipy_signal
import json

from .tone_detector import MultiStationToneDetector
from .digital_rf_writer import DigitalRFWriter
from .interfaces.data_models import (
    TimeSnapReference, 
    QualityInfo, 
    Discontinuity, 
    DiscontinuityType,
    ToneDetectionResult,
    StationType
)

logger = logging.getLogger(__name__)


@dataclass
class NPZArchive:
    """
    Parsed NPZ archive from core recorder
    """
    file_path: Path
    
    # Primary data
    iq_samples: np.ndarray
    
    # Timing reference (critical)
    rtp_timestamp: int
    rtp_ssrc: int
    sample_rate: int
    
    # Metadata
    frequency_hz: float
    channel_name: str
    unix_timestamp: float
    
    # Quality indicators
    gaps_filled: int
    gaps_count: int
    packets_received: int
    packets_expected: int
    
    # Gap details
    gap_rtp_timestamps: np.ndarray
    gap_sample_indices: np.ndarray
    gap_samples_filled: np.ndarray
    gap_packets_lost: np.ndarray
    
    # Provenance
    recorder_version: str
    created_timestamp: float
    
    @classmethod
    def load(cls, file_path: Path) -> 'NPZArchive':
        """Load NPZ archive from file"""
        data = np.load(file_path)
        
        return cls(
            file_path=file_path,
            iq_samples=data['iq'],
            rtp_timestamp=int(data['rtp_timestamp']),
            rtp_ssrc=int(data['rtp_ssrc']),
            sample_rate=int(data['sample_rate']),
            frequency_hz=float(data['frequency_hz']),
            channel_name=str(data['channel_name']),
            unix_timestamp=float(data['unix_timestamp']),
            gaps_filled=int(data['gaps_filled']),
            gaps_count=int(data['gaps_count']),
            packets_received=int(data['packets_received']),
            packets_expected=int(data['packets_expected']),
            gap_rtp_timestamps=data['gap_rtp_timestamps'],
            gap_sample_indices=data['gap_sample_indices'],
            gap_samples_filled=data['gap_samples_filled'],
            gap_packets_lost=data['gap_packets_lost'],
            recorder_version=str(data['recorder_version']),
            created_timestamp=float(data['created_timestamp'])
        )
    
    def calculate_utc_timestamp(self, time_snap: Optional[TimeSnapReference]) -> float:
        """
        Calculate UTC timestamp for first sample using time_snap reference
        
        Args:
            time_snap: Current time_snap reference, or None to use wall clock
            
        Returns:
            UTC timestamp (seconds since epoch)
        """
        if time_snap:
            return time_snap.calculate_sample_time(self.rtp_timestamp)
        else:
            # Fall back to wall clock (approximate)
            return self.unix_timestamp


@dataclass
class ProcessingState:
    """
    State tracking for analytics processing
    """
    last_processed_file: Optional[Path] = None
    last_processed_time: Optional[float] = None
    files_processed: int = 0
    time_snap: Optional[TimeSnapReference] = None
    time_snap_history: List[TimeSnapReference] = field(default_factory=list)
    detection_history: List[ToneDetectionResult] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """Serialize state for persistence"""
        return {
            'last_processed_file': str(self.last_processed_file) if self.last_processed_file else None,
            'last_processed_time': self.last_processed_time,
            'files_processed': self.files_processed,
            'time_snap': self.time_snap.to_dict() if self.time_snap else None,
            'time_snap_history': [ts.to_dict() for ts in self.time_snap_history],
            'detection_count': len(self.detection_history)
        }


class AnalyticsService:
    """
    Main analytics service - processes NPZ archives to derived products
    """
    
    def __init__(
        self,
        archive_dir: Path,
        output_dir: Path,
        channel_name: str,
        frequency_hz: float,
        state_file: Optional[Path] = None,
        station_config: Optional[Dict] = None
    ):
        """
        Initialize analytics service
        
        Args:
            archive_dir: Directory containing NPZ archives from core recorder
            output_dir: Base directory for derived products
            channel_name: Channel identifier (for tone detector configuration)
            frequency_hz: Center frequency in Hz
            state_file: Path to state persistence file (optional)
            station_config: Station metadata (callsign, grid, etc.) for Digital RF
        """
        self.archive_dir = Path(archive_dir)
        self.output_dir = Path(output_dir)
        self.channel_name = channel_name
        self.frequency_hz = frequency_hz
        self.state_file = state_file
        self.station_config = station_config or {}
        
        # Create output directories
        self.quality_dir = self.output_dir / 'quality'
        self.drf_dir = self.output_dir / 'digital_rf'
        self.logs_dir = self.output_dir / 'logs'
        
        for d in [self.quality_dir, self.drf_dir, self.logs_dir]:
            d.mkdir(parents=True, exist_ok=True)
        
        # Processing state
        self.state = ProcessingState()
        self._load_state()
        
        # Tone detector (resamples 16k → 3k internally)
        self.tone_detector = MultiStationToneDetector(
            channel_name=channel_name,
            sample_rate=3000  # Internal processing rate
        )
        
        # Digital RF writer (16 kHz → 10 Hz decimation + HDF5 output)
        self.drf_writer: Optional[DigitalRFWriter] = None
        try:
            self.drf_writer = DigitalRFWriter(
                output_dir=self.drf_dir,
                channel_name=channel_name,
                frequency_hz=frequency_hz,
                input_sample_rate=16000,
                output_sample_rate=10,
                station_config=self.station_config
            )
            logger.info("✅ DigitalRFWriter initialized")
        except ImportError as e:
            logger.warning(f"Digital RF not available: {e}")
            logger.warning("Continuing without Digital RF output")
        
        # Running flag
        self.running = False
        
        logger.info(f"AnalyticsService initialized for {channel_name}")
        logger.info(f"Archive dir: {self.archive_dir}")
        logger.info(f"Output dir: {self.output_dir}")
        logger.info(f"Files processed: {self.state.files_processed}")
        logger.info(f"Time snap established: {self.state.time_snap is not None}")
    
    def _load_state(self):
        """Load persistent state from file"""
        if self.state_file and self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    state_data = json.load(f)
                
                # Restore basic state
                self.state.files_processed = state_data.get('files_processed', 0)
                self.state.last_processed_time = state_data.get('last_processed_time')
                
                if state_data.get('last_processed_file'):
                    self.state.last_processed_file = Path(state_data['last_processed_file'])
                
                # Restore time_snap if available
                if state_data.get('time_snap'):
                    ts = state_data['time_snap']
                    self.state.time_snap = TimeSnapReference(
                        rtp_timestamp=ts['rtp_timestamp'],
                        utc_timestamp=ts['utc_timestamp'],
                        sample_rate=ts['sample_rate'],
                        source=ts['source'],
                        confidence=ts['confidence'],
                        station=ts['station'],
                        established_at=ts['established_at']
                    )
                
                logger.info(f"Loaded state from {self.state_file}")
            except Exception as e:
                logger.warning(f"Failed to load state: {e}")
    
    def _save_state(self):
        """Save persistent state to file"""
        if self.state_file:
            try:
                with open(self.state_file, 'w') as f:
                    json.dump(self.state.to_dict(), f, indent=2)
            except Exception as e:
                logger.warning(f"Failed to save state: {e}")
    
    def discover_new_files(self) -> List[Path]:
        """
        Discover new NPZ files to process
        
        Returns:
            List of NPZ file paths, sorted by creation time
        """
        # Find all NPZ files recursively
        all_files = sorted(self.archive_dir.rglob('*.npz'))
        
        # Filter to new files (after last processed)
        if self.state.last_processed_time:
            new_files = [
                f for f in all_files 
                if f.stat().st_mtime > self.state.last_processed_time
            ]
        else:
            # First run - process all files
            new_files = all_files
        
        logger.info(f"Discovered {len(new_files)} new NPZ files")
        return new_files
    
    def process_archive(self, archive: NPZArchive) -> Dict:
        """
        Process a single NPZ archive through full analytics pipeline
        
        Args:
            archive: Loaded NPZ archive
            
        Returns:
            Dict with processing results
        """
        results = {
            'file': str(archive.file_path),
            'quality_metrics': None,
            'tone_detections': [],
            'time_snap_updated': False,
            'decimated_samples': 0,
            'errors': []
        }
        
        try:
            # Step 1: Calculate quality metrics
            quality = self._calculate_quality_metrics(archive)
            results['quality_metrics'] = quality.to_dict()
            self._write_quality_metrics(archive, quality)
            
            # Step 2: Tone detection (if applicable)
            if self._is_tone_detection_channel(archive.channel_name):
                detections = self._detect_tones(archive)
                results['tone_detections'] = [
                    {
                        'station': det.station.value,
                        'frequency_hz': det.frequency_hz,
                        'timing_error_ms': det.timing_error_ms,
                        'snr_db': det.snr_db,
                        'use_for_time_snap': det.use_for_time_snap
                    }
                    for det in detections
                ]
                
                # Update time_snap if we got a good detection
                if detections:
                    updated = self._update_time_snap(detections, archive)
                    results['time_snap_updated'] = updated
            
            # Step 3: Decimation and Digital RF output (if time_snap available)
            if self.state.time_snap:
                decimated_count = self._decimate_and_write_drf(archive, quality)
                results['decimated_samples'] = decimated_count
            else:
                logger.debug("Skipping Digital RF - time_snap not yet established")
            
            # Step 4: Write discontinuity log
            self._write_discontinuity_log(archive, quality)
            
        except Exception as e:
            logger.error(f"Error processing {archive.file_path}: {e}", exc_info=True)
            results['errors'].append(str(e))
        
        return results
    
    def _calculate_quality_metrics(self, archive: NPZArchive) -> QualityInfo:
        """
        Calculate quality metrics from archive data
        
        Args:
            archive: Loaded NPZ archive
            
        Returns:
            QualityInfo with calculated metrics
        """
        total_samples = len(archive.iq_samples)
        
        # Completeness
        completeness_pct = 100.0 * (total_samples - archive.gaps_filled) / total_samples if total_samples > 0 else 0.0
        
        # Packet loss
        packet_loss_pct = 100.0 * (archive.packets_expected - archive.packets_received) / archive.packets_expected if archive.packets_expected > 0 else 0.0
        
        # Gap duration in ms
        gap_duration_ms = (archive.gaps_filled / archive.sample_rate) * 1000.0
        
        # Build discontinuity list
        discontinuities = []
        for i in range(len(archive.gap_rtp_timestamps)):
            disc = Discontinuity(
                timestamp=archive.unix_timestamp,  # Approximate
                sample_index=int(archive.gap_sample_indices[i]),
                discontinuity_type=DiscontinuityType.GAP,
                magnitude_samples=int(archive.gap_samples_filled[i]),
                magnitude_ms=(archive.gap_samples_filled[i] / archive.sample_rate) * 1000.0,
                rtp_sequence_before=None,
                rtp_sequence_after=None,
                rtp_timestamp_before=int(archive.gap_rtp_timestamps[i]),
                rtp_timestamp_after=int(archive.gap_rtp_timestamps[i] + archive.gap_samples_filled[i]),
                wwv_related=False,
                explanation=f"RTP packet loss: {archive.gap_packets_lost[i]} packets"
            )
            discontinuities.append(disc)
        
        quality = QualityInfo(
            completeness_pct=completeness_pct,
            gap_count=archive.gaps_count,
            gap_duration_ms=gap_duration_ms,
            packet_loss_pct=packet_loss_pct,
            resequenced_count=0,  # Not tracked in NPZ
            time_snap_established=self.state.time_snap is not None,
            time_snap_confidence=self.state.time_snap.confidence if self.state.time_snap else 0.0,
            discontinuities=discontinuities,
            network_gap_ms=gap_duration_ms,
            source_failure_ms=0.0,
            recorder_offline_ms=0.0
        )
        
        return quality
    
    def _detect_tones(self, archive: NPZArchive) -> List[ToneDetectionResult]:
        """
        Run WWV/CHU/WWVH tone detection on archive
        
        Args:
            archive: Loaded NPZ archive
            
        Returns:
            List of detected tones
        """
        # Resample 16 kHz → 3 kHz for tone detection
        try:
            resampled = scipy_signal.resample_poly(
                archive.iq_samples,
                up=3,
                down=16,
                axis=0
            )
        except Exception as e:
            logger.error(f"Resampling failed: {e}")
            return []
        
        # Calculate UTC timestamp for first sample
        utc_timestamp = archive.calculate_utc_timestamp(self.state.time_snap)
        
        # Run tone detection
        detections = self.tone_detector.process_samples(
            timestamp=utc_timestamp,
            samples=resampled,
            rtp_timestamp=archive.rtp_timestamp
        )
        
        if detections:
            logger.info(f"Detected {len(detections)} tones in {archive.file_path.name}")
            for det in detections:
                logger.info(f"  {det.station.value}: {det.timing_error_ms:+.1f}ms, "
                           f"SNR={det.snr_db:.1f}dB, use_for_time_snap={det.use_for_time_snap}")
        
        return detections or []
    
    def _update_time_snap(
        self,
        detections: List[ToneDetectionResult],
        archive: NPZArchive
    ) -> bool:
        """
        Update time_snap reference from tone detections
        
        Args:
            detections: List of detected tones
            archive: Source archive
            
        Returns:
            True if time_snap was updated
        """
        # Find best time_snap-eligible detection (WWV or CHU, not WWVH)
        eligible = [d for d in detections if d.use_for_time_snap]
        
        if not eligible:
            return False
        
        # Use strongest SNR detection
        best = max(eligible, key=lambda d: d.snr_db)
        
        # Calculate RTP timestamp at tone rising edge
        # Timing error tells us how far off the minute boundary we are
        timing_offset_sec = best.timing_error_ms / 1000.0
        
        # Find minute boundary closest to detection
        minute_boundary = int(best.timestamp_utc / 60) * 60
        actual_tone_time = minute_boundary + timing_offset_sec
        
        # Calculate RTP timestamp at minute boundary
        samples_since_minute = (best.timestamp_utc - minute_boundary) * archive.sample_rate
        rtp_at_minute = int(archive.rtp_timestamp + samples_since_minute)
        
        # Create new time_snap reference
        new_time_snap = TimeSnapReference(
            rtp_timestamp=rtp_at_minute,
            utc_timestamp=float(minute_boundary),
            sample_rate=archive.sample_rate,
            source=f"{best.station.value.lower()}_verified",
            confidence=best.confidence,
            station=best.station.value,
            established_at=time.time()
        )
        
        # Check if this is a significant update
        if self.state.time_snap:
            time_diff_ms = abs((new_time_snap.utc_timestamp - self.state.time_snap.utc_timestamp) * 1000)
            if time_diff_ms > 5.0:  # More than 5ms difference
                logger.warning(f"Time snap adjustment: {time_diff_ms:.1f}ms difference")
        
        # Update state
        old_time_snap = self.state.time_snap
        self.state.time_snap = new_time_snap
        self.state.time_snap_history.append(new_time_snap)
        
        # Keep last 100 time_snap updates
        if len(self.state.time_snap_history) > 100:
            self.state.time_snap_history = self.state.time_snap_history[-100:]
        
        logger.info(f"Time snap {'updated' if old_time_snap else 'established'}: "
                   f"{best.station.value}, confidence={best.confidence:.2f}, "
                   f"timing_error={best.timing_error_ms:+.1f}ms")
        
        return True
    
    def _decimate_and_write_drf(self, archive: NPZArchive, quality: QualityInfo) -> int:
        """
        Decimate samples and write to Digital RF format
        
        Args:
            archive: Source archive
            quality: Quality metrics
            
        Returns:
            Number of decimated samples written
        """
        if not self.drf_writer:
            logger.debug("Digital RF writer not available - skipping decimation")
            return 0
        
        try:
            # Calculate UTC timestamp using time_snap reference
            utc_timestamp = archive.calculate_utc_timestamp(self.state.time_snap)
            
            # Add samples to writer (handles decimation internally)
            # Writer will buffer and decimate in 1-second chunks
            self.drf_writer.add_samples(utc_timestamp, archive.iq_samples)
            
            # Write quality metadata to parallel channel
            self._write_quality_metadata_to_drf(utc_timestamp, quality)
            
            # Calculate expected decimated count
            decimated_samples = len(archive.iq_samples) // 1600
            
            logger.debug(f"Added {len(archive.iq_samples)} samples to Digital RF "
                        f"(will produce ~{decimated_samples} decimated samples)")
            
            return decimated_samples
            
        except Exception as e:
            logger.error(f"Digital RF write error: {e}", exc_info=True)
            return 0
    
    def _write_quality_metadata_to_drf(self, timestamp: float, quality: QualityInfo):
        """
        Write quality metrics as Digital RF metadata
        
        Args:
            timestamp: UTC timestamp
            quality: Quality metrics to embed
        """
        if not self.drf_writer or not self.drf_writer.metadata_writer:
            return
        
        try:
            # Calculate global index at output rate (10 Hz)
            global_index = int(timestamp * 10)
            
            # Build metadata dict
            metadata = {
                'completeness_pct': quality.completeness_pct,
                'gap_count': quality.gap_count,
                'gap_duration_ms': quality.gap_duration_ms,
                'packet_loss_pct': quality.packet_loss_pct,
                'network_gap_ms': quality.network_gap_ms,
                'source_failure_ms': quality.source_failure_ms,
                'recorder_offline_ms': quality.recorder_offline_ms,
                'time_snap_established': quality.time_snap_established,
                'time_snap_confidence': quality.time_snap_confidence,
                'discontinuity_count': len(quality.discontinuities)
            }
            
            # Write to metadata channel
            self.drf_writer.metadata_writer.write(global_index, metadata)
            
            logger.debug(f"Wrote quality metadata at index {global_index}")
            
        except Exception as e:
            logger.warning(f"Failed to write quality metadata: {e}")
    
    def _write_quality_metrics(self, archive: NPZArchive, quality: QualityInfo):
        """Write quality metrics to CSV file"""
        csv_file = self.quality_dir / f"{self.channel_name.replace(' ', '_')}_quality.csv"
        
        # Create CSV if it doesn't exist
        if not csv_file.exists():
            with open(csv_file, 'w') as f:
                f.write("timestamp,file,completeness_pct,gap_count,gap_duration_ms,"
                       "packet_loss_pct,time_snap_established,time_snap_confidence\n")
        
        # Append metrics
        with open(csv_file, 'a') as f:
            f.write(f"{archive.unix_timestamp},{archive.file_path.name},"
                   f"{quality.completeness_pct:.2f},{quality.gap_count},"
                   f"{quality.gap_duration_ms:.2f},{quality.packet_loss_pct:.2f},"
                   f"{quality.time_snap_established},{quality.time_snap_confidence:.3f}\n")
    
    def _write_discontinuity_log(self, archive: NPZArchive, quality: QualityInfo):
        """Write discontinuity log for scientific provenance"""
        if quality.gap_count == 0:
            return
        
        log_file = self.logs_dir / f"{self.channel_name.replace(' ', '_')}_discontinuities.log"
        
        with open(log_file, 'a') as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"File: {archive.file_path.name}\n")
            f.write(f"Timestamp: {datetime.fromtimestamp(archive.unix_timestamp, tz=timezone.utc).isoformat()}\n")
            f.write(f"Total gaps: {quality.gap_count}, Total duration: {quality.gap_duration_ms:.2f}ms\n")
            f.write(f"{'='*80}\n\n")
            
            for disc in quality.discontinuities:
                f.write(f"  Gap at sample {disc.sample_index}: "
                       f"{disc.magnitude_samples} samples ({disc.magnitude_ms:.2f}ms)\n")
                f.write(f"    RTP timestamp: {disc.rtp_timestamp_before} → {disc.rtp_timestamp_after}\n")
                f.write(f"    Explanation: {disc.explanation}\n\n")
    
    def _is_tone_detection_channel(self, channel_name: str) -> bool:
        """Check if channel should have tone detection"""
        tone_keywords = ['WWV', 'CHU', 'WWVH']
        return any(kw in channel_name.upper() for kw in tone_keywords)
    
    def run(self, poll_interval: float = 10.0):
        """
        Main processing loop - polls for new files and processes them
        
        Args:
            poll_interval: Seconds between directory scans
        """
        self.running = True
        logger.info(f"Analytics service starting (poll interval: {poll_interval}s)")
        
        while self.running:
            try:
                # Discover new files
                new_files = self.discover_new_files()
                
                # Process each file
                for file_path in new_files:
                    try:
                        logger.info(f"Processing: {file_path.name}")
                        
                        # Load archive
                        archive = NPZArchive.load(file_path)
                        
                        # Process through analytics pipeline
                        results = self.process_archive(archive)
                        
                        # Update state
                        self.state.last_processed_file = file_path
                        self.state.last_processed_time = file_path.stat().st_mtime
                        self.state.files_processed += 1
                        
                        # Save state periodically
                        if self.state.files_processed % 10 == 0:
                            self._save_state()
                        
                        logger.info(f"Processed: {file_path.name} "
                                   f"(completeness={results['quality_metrics']['completeness_pct']:.1f}%, "
                                   f"detections={len(results['tone_detections'])})")
                        
                    except Exception as e:
                        logger.error(f"Failed to process {file_path}: {e}", exc_info=True)
                        # Continue to next file
                
                # Save state after batch
                if new_files:
                    self._save_state()
                
                # Sleep until next poll
                time.sleep(poll_interval)
                
            except KeyboardInterrupt:
                logger.info("Shutting down on keyboard interrupt")
                self.running = False
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                time.sleep(poll_interval)
        
        # Final state save
        self._save_state()
        
        # Flush Digital RF buffers
        if self.drf_writer:
            logger.info("Flushing Digital RF buffers...")
            self.drf_writer.flush()
        
        logger.info("Analytics service stopped")
    
    def stop(self):
        """Stop the analytics service"""
        self.running = False
        
        # Flush Digital RF writer on stop
        if self.drf_writer:
            logger.info("Flushing Digital RF writer...")
            try:
                self.drf_writer.flush()
            except Exception as e:
                logger.error(f"Error flushing Digital RF: {e}")


def main():
    """CLI entry point for testing"""
    import argparse
    
    parser = argparse.ArgumentParser(description='GRAPE Analytics Service')
    parser.add_argument('--archive-dir', required=True, help='NPZ archive directory')
    parser.add_argument('--output-dir', required=True, help='Output directory for derived products')
    parser.add_argument('--channel-name', required=True, help='Channel name')
    parser.add_argument('--frequency-hz', type=float, required=True, help='Center frequency in Hz')
    parser.add_argument('--state-file', help='State persistence file')
    parser.add_argument('--poll-interval', type=float, default=10.0, help='Poll interval (seconds)')
    parser.add_argument('--log-level', default='INFO', help='Log level')
    parser.add_argument('--callsign', help='Station callsign for Digital RF metadata')
    parser.add_argument('--grid-square', help='Grid square for Digital RF metadata')
    parser.add_argument('--receiver-name', default='GRAPE', help='Receiver name for Digital RF metadata')
    parser.add_argument('--psws-station-id', help='PSWS station ID (for upload compatibility)')
    parser.add_argument('--psws-instrument-id', default='1', help='PSWS instrument number (for upload compatibility)')
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Build station config (PSWS-compatible)
    station_config = {}
    if args.callsign:
        station_config['callsign'] = args.callsign
    if args.grid_square:
        station_config['grid_square'] = args.grid_square
    if args.receiver_name:
        station_config['receiver_name'] = args.receiver_name
    if args.psws_station_id:
        station_config['psws_station_id'] = args.psws_station_id
    if args.psws_instrument_id:
        station_config['psws_instrument_id'] = args.psws_instrument_id
    
    # Create and run service
    service = AnalyticsService(
        archive_dir=Path(args.archive_dir),
        output_dir=Path(args.output_dir),
        channel_name=args.channel_name,
        frequency_hz=args.frequency_hz,
        state_file=Path(args.state_file) if args.state_file else None,
        station_config=station_config if station_config else None
    )
    
    service.run(poll_interval=args.poll_interval)


if __name__ == '__main__':
    main()
