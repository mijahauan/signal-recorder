#!/usr/bin/env python3
"""
Phase 2 Analytics Service - Process Digital RF Archives

Watches for new Digital RF data from Phase 1 and processes through
Phase 2 Temporal Analysis Engine to produce:
1. D_clock (timing correction for UTC alignment)
2. Station discrimination (WWV vs WWVH)
3. Quality metrics and tone detections
4. Status files for web-ui monitoring

Input:  raw_archive/{CHANNEL}/ (20 kHz Digital RF from Phase 1)
Output: phase2/{CHANNEL}/      (timing analysis, status JSON)
"""

import argparse
import csv
import json
import logging
import signal
import sys
import time
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger(__name__)


class Phase2AnalyticsService:
    """
    Phase 2 Analytics Service - reads DRF, produces timing analysis.
    
    Monitors raw_archive/{CHANNEL}/ for new Digital RF data and
    processes each minute through Phase2TemporalEngine.
    """
    
    def __init__(
        self,
        archive_dir: Path,
        output_dir: Path,
        channel_name: str,
        frequency_hz: float,
        sample_rate: int = 20000,
        receiver_grid: str = '',
        station_config: Optional[Dict] = None,
        poll_interval: float = 10.0
    ):
        """
        Initialize Phase 2 analytics service.
        
        Args:
            archive_dir: Directory containing Digital RF from Phase 1
            output_dir: Output directory for Phase 2 products
            channel_name: Channel identifier
            frequency_hz: Center frequency in Hz
            sample_rate: Sample rate (default 20000)
            receiver_grid: Receiver grid square for propagation calculations
            station_config: Station metadata
            poll_interval: Seconds between polling for new data
        """
        self.archive_dir = Path(archive_dir)
        self.output_dir = Path(output_dir)
        self.channel_name = channel_name
        self.frequency_hz = frequency_hz
        self.sample_rate = sample_rate
        self.receiver_grid = receiver_grid
        self.station_config = station_config or {}
        self.poll_interval = poll_interval
        
        # Create output directories using coordinated path structure
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.status_dir = self.output_dir / 'status'
        self.status_dir.mkdir(parents=True, exist_ok=True)
        
        # Clock offset series directory: {data_root}/phase2/{CHANNEL}/clock_offset/
        self.clock_offset_dir = self.output_dir / 'clock_offset'
        self.clock_offset_dir.mkdir(parents=True, exist_ok=True)
        
        # Status file for web-ui
        self.status_file = self.status_dir / 'analytics-service-status.json'
        
        # CSV time series for D_clock (coordinated path)
        self.clock_offset_csv = self.clock_offset_dir / 'clock_offset_series.csv'
        self._init_clock_offset_csv()
        
        # CSV time series for carrier power (for power graphs)
        self.carrier_power_dir = self.output_dir / 'carrier_power'
        self.carrier_power_dir.mkdir(parents=True, exist_ok=True)
        self._init_carrier_power_csv()
        
        # ====================================================================
        # Discrimination Method CSV Directories
        # ====================================================================
        
        # Tone detections (1000/1200 Hz timing tones)
        self.tone_detections_dir = self.output_dir / 'tone_detections'
        self.tone_detections_dir.mkdir(parents=True, exist_ok=True)
        self._init_tone_detections_csv()
        
        # BCD discrimination (BCD correlation analysis)
        self.bcd_discrimination_dir = self.output_dir / 'bcd_discrimination'
        self.bcd_discrimination_dir.mkdir(parents=True, exist_ok=True)
        self._init_bcd_discrimination_csv()
        
        # Doppler analysis
        self.doppler_dir = self.output_dir / 'doppler'
        self.doppler_dir.mkdir(parents=True, exist_ok=True)
        self._init_doppler_csv()
        
        # Station ID (440 Hz voice ID + 500/600 Hz ground truth)
        self.station_id_dir = self.output_dir / 'station_id_440hz'
        self.station_id_dir.mkdir(parents=True, exist_ok=True)
        self._init_station_id_csv()
        
        # Test signal (minutes 8 and 44)
        self.test_signal_dir = self.output_dir / 'test_signal'
        self.test_signal_dir.mkdir(parents=True, exist_ok=True)
        self._init_test_signal_csv()
        
        # Discrimination summary (weighted voting result)
        self.discrimination_dir = self.output_dir / 'discrimination'
        self.discrimination_dir.mkdir(parents=True, exist_ok=True)
        self._init_discrimination_csv()
        
        # Decimated 10 Hz output directory (Phase 3 products)
        self.decimated_dir = self.output_dir / 'decimated'
        self.decimated_dir.mkdir(parents=True, exist_ok=True)
        
        # Spectrogram output directory
        self.spectrogram_dir = self.output_dir / 'spectrograms'
        self.spectrogram_dir.mkdir(parents=True, exist_ok=True)
        
        # Decimation parameters: 20 kHz → 10 Hz
        self.decimation_factor = int(sample_rate / 10)  # 2000 for 20kHz
        self.output_rate = 10  # 10 Hz output
        
        # Accumulator for 10Hz power data (for spectrograms)
        self.power_accumulator = []  # (timestamp, power_db) tuples
        self.spectrogram_interval = 60  # Generate spectrogram every N minutes
        
        # Initialize Phase 2 engine
        from .phase2_temporal_engine import Phase2TemporalEngine
        
        # Extract precise coordinates from station_config if available
        # Precise coordinates improve timing accuracy by ~16μs over grid square center
        precise_lat = self.station_config.get('latitude')
        precise_lon = self.station_config.get('longitude')
        
        if precise_lat is not None and precise_lon is not None:
            logger.info(f"Using precise coordinates: {precise_lat:.6f}°N, {precise_lon:.6f}°W")
        
        self.engine = Phase2TemporalEngine(
            raw_archive_dir=self.archive_dir.parent,  # parent contains all channels
            output_dir=self.output_dir,
            channel_name=channel_name,
            frequency_hz=frequency_hz,
            receiver_grid=receiver_grid,
            sample_rate=sample_rate,
            precise_lat=precise_lat,
            precise_lon=precise_lon
        )
        
        # Initialize Clock Convergence Model
        # "Set, Monitor, Intervention" architecture for GPSDO-disciplined timing
        from .clock_convergence import ClockConvergenceModel
        
        convergence_state_file = self.status_dir / 'convergence_state.json'
        self.convergence_model = ClockConvergenceModel(
            lock_uncertainty_ms=1.0,      # Lock when uncertainty < 1ms
            min_samples_for_lock=30,      # Need 30 minutes of data
            anomaly_sigma=3.0,            # 3σ for anomaly detection
            max_consecutive_anomalies=5,  # Force reacquire after 5 anomalies
            state_file=convergence_state_file
        )
        logger.info(f"Initialized clock convergence model (state file: {convergence_state_file})")
        
        # State tracking
        self.running = False
        self.start_time = time.time()
        self.minutes_processed = 0
        self.last_processed_minute = 0
        self.last_result = None
        self.last_carrier_snr_db = None  # Carrier SNR from IQ data
        self.last_carrier_power_db = None  # Carrier power from IQ data
        
        # Track which minutes we've processed
        self.processed_minutes = set()
        
        logger.info(f"Phase2AnalyticsService initialized for {channel_name}")
        logger.info(f"  Archive: {archive_dir}")
        logger.info(f"  Output: {output_dir}")
        logger.info(f"  Frequency: {frequency_hz/1e6:.3f} MHz")
        logger.info(f"  Grid: {receiver_grid}")
    
    def _init_clock_offset_csv(self):
        """Initialize clock offset CSV file with headers if needed."""
        if not self.clock_offset_csv.exists():
            with open(self.clock_offset_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'system_time', 'utc_time', 'minute_boundary_utc',
                    'clock_offset_ms', 'station', 'frequency_mhz',
                    'propagation_delay_ms', 'propagation_mode', 'n_hops',
                    'confidence', 'uncertainty_ms', 'quality_grade',
                    'snr_db', 'delay_spread_ms', 'doppler_std_hz', 'fss_db',
                    'wwv_power_db', 'wwvh_power_db', 'discrimination_confidence',
                    'utc_verified', 'multi_station_verified',
                    'rtp_timestamp', 'processed_at'
                ])
            logger.info(f"Created clock offset CSV: {self.clock_offset_csv}")
    
    def _write_clock_offset(self, result, minute_boundary: int, rtp_timestamp: int):
        """Append D_clock measurement to CSV time series with convergence tracking."""
        try:
            # Extract values from Phase2Result
            solution = result.solution if hasattr(result, 'solution') else None
            station = solution.station if solution else 'UNKNOWN'
            frequency_mhz = self.frequency_hz / 1e6
            
            # ================================================================
            # Process through Clock Convergence Model
            # "Set, Monitor, Intervention" - converge to lock, then monitor
            # ================================================================
            convergence_result = self.convergence_model.process_measurement(
                station=station,
                frequency_mhz=frequency_mhz,
                d_clock_ms=result.d_clock_ms,
                timestamp=float(minute_boundary),
                snr_db=self.last_carrier_snr_db,
                quality_grade=result.quality_grade
            )
            
            # Use converged values when locked, raw values otherwise
            if convergence_result.is_locked:
                effective_d_clock = convergence_result.d_clock_ms
                effective_uncertainty = convergence_result.uncertainty_ms
                quality_grade = 'A' if convergence_result.uncertainty_ms < 0.5 else 'B'
            else:
                effective_d_clock = convergence_result.d_clock_ms  # Running mean
                effective_uncertainty = convergence_result.uncertainty_ms
                # Grade based on convergence progress
                progress = convergence_result.convergence_progress
                if progress >= 0.9:
                    quality_grade = 'B'
                elif progress >= 0.5:
                    quality_grade = 'C'
                else:
                    quality_grade = 'D'
            
            # Log convergence state changes
            if convergence_result.is_locked and convergence_result.sample_count == 30:
                logger.info(
                    f"🔒 LOCKED: {self.channel_name} D_clock = "
                    f"{effective_d_clock:.3f} ± {effective_uncertainty:.3f} ms"
                )
            
            # Log anomalies (propagation events!)
            if convergence_result.is_anomaly:
                logger.info(
                    f"📡 PROPAGATION EVENT: {self.channel_name} residual = "
                    f"{convergence_result.residual_ms:.2f} ms "
                    f"({convergence_result.anomaly_sigma:.1f}σ)"
                )
            
            with open(self.clock_offset_csv, 'a', newline='') as f:
                writer = csv.writer(f)
                
                writer.writerow([
                    minute_boundary,                                    # system_time
                    minute_boundary + (effective_d_clock / 1000.0),     # utc_time
                    minute_boundary,                                    # minute_boundary_utc
                    effective_d_clock,                                  # clock_offset_ms (converged)
                    station,                                            # station
                    frequency_mhz,                                      # frequency_mhz
                    solution.t_propagation_ms if solution else 0,       # propagation_delay_ms
                    solution.propagation_mode if solution else '',      # propagation_mode
                    solution.n_hops if solution else 0,                 # n_hops
                    solution.confidence if solution else 0,             # confidence
                    effective_uncertainty,                              # uncertainty_ms (from convergence)
                    quality_grade,                                      # quality_grade (from convergence)
                    self.last_carrier_snr_db or 0,                      # snr_db
                    '',                                                 # delay_spread_ms
                    '',                                                 # doppler_std_hz
                    '',                                                 # fss_db
                    '',                                                 # wwv_power_db
                    '',                                                 # wwvh_power_db
                    '',                                                 # discrimination_confidence
                    convergence_result.is_locked,                       # utc_verified (locked = verified)
                    False,                                              # multi_station_verified
                    rtp_timestamp,                                      # rtp_timestamp
                    datetime.now(timezone.utc).timestamp()              # processed_at
                ])
                
            # Store convergence result for status reporting
            self.last_convergence_result = convergence_result
            
        except Exception as e:
            logger.error(f"Failed to write clock offset: {e}")
    
    def _init_carrier_power_csv(self):
        """Initialize carrier power CSV file for today."""
        today = datetime.now(timezone.utc).strftime('%Y%m%d')
        self.carrier_power_csv = self.carrier_power_dir / f'carrier_power_{today}.csv'
        
        if not self.carrier_power_csv.exists():
            with open(self.carrier_power_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'utc_time', 'power_db', 'snr_db',
                    'wwv_tone_db', 'wwvh_tone_db', 'station', 'quality_grade'
                ])
            logger.info(f"Created carrier power CSV: {self.carrier_power_csv}")
    
    def _write_carrier_power(self, minute_boundary: int, power_db: float, snr_db: float,
                              wwv_tone_db: float = None, wwvh_tone_db: float = None,
                              station: str = None, quality_grade: str = None):
        """Append carrier power measurement to daily CSV."""
        try:
            # Ensure we're writing to today's file
            today = datetime.now(timezone.utc).strftime('%Y%m%d')
            expected_csv = self.carrier_power_dir / f'carrier_power_{today}.csv'
            if self.carrier_power_csv != expected_csv:
                self.carrier_power_csv = expected_csv
                self._init_carrier_power_csv()
            
            with open(self.carrier_power_csv, 'a', newline='') as f:
                writer = csv.writer(f)
                utc_time = datetime.fromtimestamp(minute_boundary, timezone.utc).isoformat()
                writer.writerow([
                    minute_boundary,
                    utc_time,
                    round(power_db, 2) if power_db else '',
                    round(snr_db, 2) if snr_db else '',
                    round(wwv_tone_db, 2) if wwv_tone_db else '',
                    round(wwvh_tone_db, 2) if wwvh_tone_db else '',
                    station or '',
                    quality_grade or ''
                ])
        except Exception as e:
            logger.error(f"Failed to write carrier power: {e}")
    
    # ========================================================================
    # Discrimination Method CSV Writers
    # ========================================================================
    
    def _get_file_channel_name(self) -> str:
        """Get filename-safe channel name (spaces and dots to underscores)."""
        return self.channel_name.replace(' ', '_').replace('.', '_')
    
    def _init_tone_detections_csv(self):
        """Initialize tone detections CSV for today."""
        today = datetime.now(timezone.utc).strftime('%Y%m%d')
        file_channel = self._get_file_channel_name()
        self.tone_detections_csv = self.tone_detections_dir / f'{file_channel}_tones_{today}.csv'
        
        if not self.tone_detections_csv.exists():
            with open(self.tone_detections_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp_utc', 'minute_boundary', 'wwv_detected', 'wwvh_detected',
                    'wwv_snr_db', 'wwvh_snr_db', 'wwv_timing_ms', 'wwvh_timing_ms',
                    'anchor_station', 'anchor_confidence'
                ])
            logger.info(f"Created tone detections CSV: {self.tone_detections_csv}")
    
    def _write_tone_detections(self, minute_boundary: int, time_snap):
        """Write tone detection results from TimeSnapResult."""
        try:
            today = datetime.now(timezone.utc).strftime('%Y%m%d')
            file_channel = self._get_file_channel_name()
            expected_csv = self.tone_detections_dir / f'{file_channel}_tones_{today}.csv'
            if self.tone_detections_csv != expected_csv:
                self.tone_detections_csv = expected_csv
                self._init_tone_detections_csv()
            
            with open(self.tone_detections_csv, 'a', newline='') as f:
                writer = csv.writer(f)
                utc_time = datetime.fromtimestamp(minute_boundary, timezone.utc).isoformat()
                writer.writerow([
                    utc_time,
                    minute_boundary,
                    1 if time_snap.wwv_detected else 0,
                    1 if time_snap.wwvh_detected else 0,
                    round(time_snap.wwv_snr_db, 2) if time_snap.wwv_snr_db else '',
                    round(time_snap.wwvh_snr_db, 2) if time_snap.wwvh_snr_db else '',
                    round(time_snap.wwv_timing_ms, 3) if time_snap.wwv_timing_ms else '',
                    round(time_snap.wwvh_timing_ms, 3) if time_snap.wwvh_timing_ms else '',
                    time_snap.anchor_station or '',
                    round(time_snap.anchor_confidence, 3) if time_snap.anchor_confidence else ''
                ])
        except Exception as e:
            logger.error(f"Failed to write tone detections: {e}")
    
    def _init_bcd_discrimination_csv(self):
        """Initialize BCD discrimination CSV for today."""
        today = datetime.now(timezone.utc).strftime('%Y%m%d')
        file_channel = self._get_file_channel_name()
        self.bcd_discrimination_csv = self.bcd_discrimination_dir / f'{file_channel}_bcd_{today}.csv'
        
        if not self.bcd_discrimination_csv.exists():
            with open(self.bcd_discrimination_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp_utc', 'minute_boundary', 'wwv_amplitude', 'wwvh_amplitude',
                    'differential_delay_ms', 'correlation_quality', 'wwv_toa_ms', 'wwvh_toa_ms',
                    'amplitude_ratio_db'
                ])
            logger.info(f"Created BCD discrimination CSV: {self.bcd_discrimination_csv}")
    
    def _write_bcd_discrimination(self, minute_boundary: int, channel_char):
        """Write BCD discrimination results from ChannelCharacterization."""
        try:
            today = datetime.now(timezone.utc).strftime('%Y%m%d')
            file_channel = self._get_file_channel_name()
            expected_csv = self.bcd_discrimination_dir / f'{file_channel}_bcd_{today}.csv'
            if self.bcd_discrimination_csv != expected_csv:
                self.bcd_discrimination_csv = expected_csv
                self._init_bcd_discrimination_csv()
            
            # Calculate amplitude ratio in dB
            ratio_db = None
            if channel_char.bcd_wwv_amplitude and channel_char.bcd_wwvh_amplitude:
                if channel_char.bcd_wwvh_amplitude > 0:
                    ratio_db = 20 * np.log10(channel_char.bcd_wwv_amplitude / channel_char.bcd_wwvh_amplitude)
            
            with open(self.bcd_discrimination_csv, 'a', newline='') as f:
                writer = csv.writer(f)
                utc_time = datetime.fromtimestamp(minute_boundary, timezone.utc).isoformat()
                writer.writerow([
                    utc_time,
                    minute_boundary,
                    round(channel_char.bcd_wwv_amplitude, 4) if channel_char.bcd_wwv_amplitude else '',
                    round(channel_char.bcd_wwvh_amplitude, 4) if channel_char.bcd_wwvh_amplitude else '',
                    round(channel_char.bcd_differential_delay_ms, 3) if channel_char.bcd_differential_delay_ms else '',
                    round(channel_char.bcd_correlation_quality, 3) if channel_char.bcd_correlation_quality else '',
                    round(channel_char.bcd_wwv_toa_ms, 3) if channel_char.bcd_wwv_toa_ms else '',
                    round(channel_char.bcd_wwvh_toa_ms, 3) if channel_char.bcd_wwvh_toa_ms else '',
                    round(ratio_db, 2) if ratio_db else ''
                ])
        except Exception as e:
            logger.error(f"Failed to write BCD discrimination: {e}")
    
    def _init_doppler_csv(self):
        """Initialize Doppler analysis CSV for today."""
        today = datetime.now(timezone.utc).strftime('%Y%m%d')
        file_channel = self._get_file_channel_name()
        self.doppler_csv = self.doppler_dir / f'{file_channel}_doppler_{today}.csv'
        
        if not self.doppler_csv.exists():
            with open(self.doppler_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp_utc', 'minute_boundary', 'wwv_doppler_hz', 'wwvh_doppler_hz',
                    'wwv_doppler_std_hz', 'wwvh_doppler_std_hz', 'doppler_quality',
                    'max_coherent_window_sec', 'phase_variance_rad'
                ])
            logger.info(f"Created Doppler CSV: {self.doppler_csv}")
    
    def _write_doppler(self, minute_boundary: int, channel_char):
        """Write Doppler analysis results from ChannelCharacterization."""
        try:
            today = datetime.now(timezone.utc).strftime('%Y%m%d')
            file_channel = self._get_file_channel_name()
            expected_csv = self.doppler_dir / f'{file_channel}_doppler_{today}.csv'
            if self.doppler_csv != expected_csv:
                self.doppler_csv = expected_csv
                self._init_doppler_csv()
            
            with open(self.doppler_csv, 'a', newline='') as f:
                writer = csv.writer(f)
                utc_time = datetime.fromtimestamp(minute_boundary, timezone.utc).isoformat()
                writer.writerow([
                    utc_time,
                    minute_boundary,
                    round(channel_char.doppler_wwv_hz, 4) if channel_char.doppler_wwv_hz else '',
                    round(channel_char.doppler_wwvh_hz, 4) if channel_char.doppler_wwvh_hz else '',
                    round(channel_char.doppler_wwv_std_hz, 4) if channel_char.doppler_wwv_std_hz else '',
                    round(channel_char.doppler_wwvh_std_hz, 4) if channel_char.doppler_wwvh_std_hz else '',
                    round(channel_char.doppler_quality, 3) if channel_char.doppler_quality else '',
                    round(channel_char.max_coherent_window_sec, 3) if channel_char.max_coherent_window_sec else '',
                    round(channel_char.phase_variance_rad, 6) if channel_char.phase_variance_rad else ''
                ])
        except Exception as e:
            logger.error(f"Failed to write Doppler: {e}")
    
    def _init_station_id_csv(self):
        """Initialize station ID (440Hz/500Hz/600Hz) CSV for today."""
        today = datetime.now(timezone.utc).strftime('%Y%m%d')
        file_channel = self._get_file_channel_name()
        self.station_id_csv = self.station_id_dir / f'{file_channel}_440hz_{today}.csv'
        
        if not self.station_id_csv.exists():
            with open(self.station_id_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp_utc', 'minute_boundary', 'minute_number',
                    'ground_truth_station', 'ground_truth_source', 'ground_truth_power_db',
                    'station_confidence', 'dominant_station',
                    'harmonic_ratio_500_1000', 'harmonic_ratio_600_1200'
                ])
            logger.info(f"Created station ID CSV: {self.station_id_csv}")
    
    def _write_station_id(self, minute_boundary: int, channel_char):
        """Write station ID results from ChannelCharacterization."""
        try:
            today = datetime.now(timezone.utc).strftime('%Y%m%d')
            file_channel = self._get_file_channel_name()
            expected_csv = self.station_id_dir / f'{file_channel}_440hz_{today}.csv'
            if self.station_id_csv != expected_csv:
                self.station_id_csv = expected_csv
                self._init_station_id_csv()
            
            # Calculate minute number within hour (0-59)
            minute_number = (minute_boundary // 60) % 60
            
            with open(self.station_id_csv, 'a', newline='') as f:
                writer = csv.writer(f)
                utc_time = datetime.fromtimestamp(minute_boundary, timezone.utc).isoformat()
                writer.writerow([
                    utc_time,
                    minute_boundary,
                    minute_number,
                    channel_char.ground_truth_station or '',
                    channel_char.ground_truth_source or '',
                    round(channel_char.ground_truth_power_db, 2) if channel_char.ground_truth_power_db else '',
                    channel_char.station_confidence or '',
                    channel_char.dominant_station or '',
                    round(channel_char.harmonic_ratio_500_1000, 2) if channel_char.harmonic_ratio_500_1000 else '',
                    round(channel_char.harmonic_ratio_600_1200, 2) if channel_char.harmonic_ratio_600_1200 else ''
                ])
        except Exception as e:
            logger.error(f"Failed to write station ID: {e}")
    
    def _init_test_signal_csv(self):
        """Initialize test signal CSV for today."""
        today = datetime.now(timezone.utc).strftime('%Y%m%d')
        file_channel = self._get_file_channel_name()
        self.test_signal_csv = self.test_signal_dir / f'{file_channel}_test_signal_{today}.csv'
        
        if not self.test_signal_csv.exists():
            with open(self.test_signal_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp_utc', 'minute_boundary', 'minute_number', 'detected', 'station',
                    'confidence', 'multitone_score', 'chirp_score', 'snr_db',
                    'fss_db', 'delay_spread_ms', 'toa_offset_ms', 'coherence_time_sec'
                ])
            logger.info(f"Created test signal CSV: {self.test_signal_csv}")
    
    def _write_test_signal(self, minute_boundary: int, iq_samples, minute_number: int):
        """Detect and write test signal for minutes 8 and 44."""
        try:
            today = datetime.now(timezone.utc).strftime('%Y%m%d')
            file_channel = self._get_file_channel_name()
            expected_csv = self.test_signal_dir / f'{file_channel}_test_signal_{today}.csv'
            if self.test_signal_csv != expected_csv:
                self.test_signal_csv = expected_csv
                self._init_test_signal_csv()
            
            # Detect test signal using the engine's discriminator
            detection = self.engine.discriminator.test_signal_detector.detect(
                iq_samples=iq_samples,
                minute_number=minute_number,
                sample_rate=self.sample_rate
            )
            
            # Determine station from schedule: minute 8 = WWV, minute 44 = WWVH
            station = 'WWV' if minute_number == 8 else 'WWVH'
            
            with open(self.test_signal_csv, 'a', newline='') as f:
                writer = csv.writer(f)
                utc_time = datetime.fromtimestamp(minute_boundary, timezone.utc).isoformat()
                writer.writerow([
                    utc_time,
                    minute_boundary,
                    minute_number,
                    1 if detection.detected else 0,
                    station if detection.detected else '',
                    round(detection.confidence, 4) if detection.confidence else '',
                    round(detection.multitone_score, 4) if detection.multitone_score else '',
                    round(detection.chirp_score, 4) if detection.chirp_score else '',
                    round(detection.snr_db, 2) if detection.snr_db else '',
                    round(detection.frequency_selectivity_db, 2) if detection.frequency_selectivity_db else '',
                    round(detection.delay_spread_ms, 3) if detection.delay_spread_ms else '',
                    round(detection.toa_offset_ms, 3) if detection.toa_offset_ms else '',
                    round(detection.coherence_time_sec, 3) if detection.coherence_time_sec else ''
                ])
            
            if detection.detected:
                logger.info(
                    f"Test signal detected minute {minute_number}: {station}, "
                    f"confidence={detection.confidence:.2f}, SNR={detection.snr_db:.1f}dB"
                )
        except Exception as e:
            logger.error(f"Failed to write test signal: {e}")
    
    def _init_discrimination_csv(self):
        """Initialize discrimination summary CSV for today."""
        today = datetime.now(timezone.utc).strftime('%Y%m%d')
        file_channel = self._get_file_channel_name()
        self.discrimination_csv = self.discrimination_dir / f'{file_channel}_discrimination_{today}.csv'
        
        if not self.discrimination_csv.exists():
            with open(self.discrimination_csv, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp_utc', 'minute_boundary', 'dominant_station', 'station_confidence',
                    'wwv_snr_db', 'wwvh_snr_db', 'power_ratio_db', 'ground_truth_station',
                    'quality_grade', 'method_agreements', 'method_disagreements'
                ])
            logger.info(f"Created discrimination CSV: {self.discrimination_csv}")
    
    def _write_discrimination(self, minute_boundary: int, result, time_snap, channel_char):
        """Write discrimination summary combining all methods."""
        try:
            today = datetime.now(timezone.utc).strftime('%Y%m%d')
            file_channel = self._get_file_channel_name()
            expected_csv = self.discrimination_dir / f'{file_channel}_discrimination_{today}.csv'
            if self.discrimination_csv != expected_csv:
                self.discrimination_csv = expected_csv
                self._init_discrimination_csv()
            
            # Calculate power ratio from tone SNRs
            power_ratio_db = None
            if time_snap.wwv_snr_db is not None and time_snap.wwvh_snr_db is not None:
                power_ratio_db = time_snap.wwv_snr_db - time_snap.wwvh_snr_db
            
            with open(self.discrimination_csv, 'a', newline='') as f:
                writer = csv.writer(f)
                utc_time = datetime.fromtimestamp(minute_boundary, timezone.utc).isoformat()
                writer.writerow([
                    utc_time,
                    minute_boundary,
                    channel_char.dominant_station or '',
                    channel_char.station_confidence or '',
                    round(time_snap.wwv_snr_db, 2) if time_snap.wwv_snr_db else '',
                    round(time_snap.wwvh_snr_db, 2) if time_snap.wwvh_snr_db else '',
                    round(power_ratio_db, 2) if power_ratio_db else '',
                    channel_char.ground_truth_station or '',
                    result.quality_grade if result else '',
                    ';'.join(channel_char.cross_validation_agreements) if channel_char.cross_validation_agreements else '',
                    ';'.join(channel_char.cross_validation_disagreements) if channel_char.cross_validation_disagreements else ''
                ])
        except Exception as e:
            logger.error(f"Failed to write discrimination: {e}")
    
    def _read_drf_minute(self, target_minute: int) -> Optional[Tuple[np.ndarray, float, int]]:
        """
        Read one minute of DRF data centered on target_minute.
        
        Args:
            target_minute: Unix timestamp of minute boundary
            
        Returns:
            (iq_samples, system_time, rtp_timestamp) or None
        """
        try:
            import digital_rf as drf
        except ImportError:
            logger.error("digital_rf not available")
            return None
        
        if not self.archive_dir.exists():
            return None
        
        try:
            # Initialize DRF reader on the channel directory
            reader = drf.DigitalRFReader(str(self.archive_dir))
            channels = reader.get_channels()
            
            if not channels:
                logger.debug(f"No DRF channels found in {self.archive_dir}")
                return None
            
            # Use first channel (typically the date directory)
            channel = channels[0]
            bounds = reader.get_bounds(channel)
            
            if bounds[0] is None or bounds[1] is None:
                logger.debug(f"No valid data bounds in channel {channel}")
                return None
            
            # Calculate sample indices for target minute
            # DRF uses global sample index = sample_rate * unix_time
            target_start_index = int(target_minute * self.sample_rate)
            samples_per_minute = self.sample_rate * 60
            target_end_index = target_start_index + samples_per_minute
            
            # Check if target minute is within available bounds
            if target_start_index < bounds[0] or target_start_index >= bounds[1]:
                # Try to read whatever is available
                available_samples = bounds[1] - bounds[0]
                if available_samples < samples_per_minute:
                    logger.debug(f"Only {available_samples} samples available, need {samples_per_minute}")
                    return None
                # Use latest complete minute
                target_start_index = bounds[1] - samples_per_minute
            
            # Read the data
            iq_samples = reader.read_vector(target_start_index, samples_per_minute, channel)
            
            if iq_samples is None or len(iq_samples) < samples_per_minute:
                logger.debug(f"Could not read full minute of data")
                return None
            
            # Convert to proper format
            iq_samples = iq_samples.squeeze().astype(np.complex64)
            
            # Calculate system time and RTP timestamp
            system_time = target_start_index / self.sample_rate
            rtp_timestamp = target_start_index
            
            logger.debug(f"Read {len(iq_samples)} samples for minute {target_minute}")
            return iq_samples, system_time, rtp_timestamp
            
        except Exception as e:
            logger.debug(f"Error reading DRF: {e}")
            return None
    
    def _get_latest_minute(self) -> int:
        """Get the latest complete minute boundary."""
        now = time.time()
        # Go back 2 minutes to ensure data is complete
        return ((int(now) // 60) - 2) * 60
    
    def _calculate_carrier_snr(self, iq_samples: np.ndarray) -> float:
        """
        Calculate carrier SNR from IQ samples.
        
        This measures the signal-to-noise ratio of the carrier (DC component)
        which is independent of tone detection. Works for all channels.
        
        Method: Compare mean power (signal) to variance (noise fluctuations)
        
        Args:
            iq_samples: Complex IQ samples
            
        Returns:
            SNR in dB
        """
        # Calculate carrier power (mean of |IQ|^2)
        power = np.abs(iq_samples) ** 2
        carrier_power = np.mean(power)
        
        # Estimate noise power from variance of power (fluctuations around mean)
        noise_power = np.var(power)
        
        # Avoid division by zero
        if noise_power < 1e-20:
            noise_power = 1e-20
        
        # SNR in dB
        snr_db = 10 * np.log10(carrier_power / noise_power)
        
        return float(snr_db)
    
    def _decimate_to_10hz(self, iq_samples: np.ndarray, minute_boundary: int):
        """
        Decimate 20kHz IQ to 10Hz power time series and accumulate for spectrogram.
        
        Args:
            iq_samples: 20kHz complex IQ samples (1 minute = 1.2M samples)
            minute_boundary: Unix timestamp of minute start
        """
        try:
            # Reshape into 2000-sample blocks (each block = 0.1 sec = 10Hz)
            n_samples = len(iq_samples)
            n_blocks = n_samples // self.decimation_factor
            
            if n_blocks == 0:
                return
            
            # Truncate to exact multiple
            trimmed = iq_samples[:n_blocks * self.decimation_factor]
            blocks = trimmed.reshape(n_blocks, self.decimation_factor)
            
            # Calculate power for each 0.1 second block
            block_power = np.mean(np.abs(blocks) ** 2, axis=1)
            power_db = 10 * np.log10(block_power + 1e-12)
            
            # Create timestamps for each 10Hz sample
            for i, p in enumerate(power_db):
                ts = minute_boundary + (i / self.output_rate)
                self.power_accumulator.append((ts, float(p)))
            
            # Generate spectrogram if we have enough data
            if len(self.power_accumulator) >= self.spectrogram_interval * self.output_rate * 60:
                self._generate_spectrogram()
                
        except Exception as e:
            logger.error(f"Decimation error: {e}")
    
    def _generate_spectrogram(self):
        """Generate spectrogram PNG from accumulated 10Hz power data."""
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            
            if len(self.power_accumulator) < 600:  # Need at least 1 minute
                return
            
            # Extract data
            times = [t for t, p in self.power_accumulator]
            powers = [p for t, p in self.power_accumulator]
            
            # Create figure
            fig, ax = plt.subplots(figsize=(12, 4))
            
            # Convert to datetime for x-axis
            from matplotlib.dates import DateFormatter
            time_labels = [datetime.fromtimestamp(t, timezone.utc) for t in times]
            
            ax.plot(time_labels, powers, 'b-', linewidth=0.5, alpha=0.8)
            ax.fill_between(time_labels, powers, alpha=0.3)
            
            ax.set_xlabel('Time (UTC)')
            ax.set_ylabel('Carrier Power (dB)')
            ax.set_title(f'{self.channel_name} - 10Hz Carrier Power')
            ax.grid(True, alpha=0.3)
            ax.xaxis.set_major_formatter(DateFormatter('%H:%M'))
            
            plt.tight_layout()
            
            # Save with date in filename
            date_str = datetime.fromtimestamp(times[0], timezone.utc).strftime('%Y%m%d')
            output_file = self.spectrogram_dir / f'{date_str}_spectrogram.png'
            plt.savefig(output_file, dpi=100)
            plt.close()
            
            logger.info(f"Generated spectrogram: {output_file}")
            
            # Keep only last 30 minutes for rolling display
            cutoff = time.time() - 1800
            self.power_accumulator = [(t, p) for t, p in self.power_accumulator if t > cutoff]
            
        except Exception as e:
            logger.error(f"Spectrogram generation error: {e}")
    
    def _write_status(self):
        """Write status file for web-ui monitoring."""
        try:
            # Build time_snap info from last result
            time_snap_dict = None
            if self.last_result and self.last_result.time_snap:
                ts = self.last_result.time_snap
                time_snap_dict = {
                    'established': True,
                    'utc_timestamp': time.time(),
                    'source': ts.anchor_station or 'unknown',
                    'confidence': ts.anchor_confidence
                }
            
            status = {
                'service': 'phase2_analytics_service',
                'version': '2.0',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'uptime_seconds': int(time.time() - self.start_time),
                'pid': None,
                'channels': {
                    self.channel_name: {
                        'channel_name': self.channel_name,
                        'frequency_hz': self.frequency_hz,
                        'minutes_processed': self.minutes_processed,
                        'last_processed_time': datetime.fromtimestamp(
                            self.last_processed_minute, timezone.utc
                        ).isoformat() if self.last_processed_minute else None,
                        'time_snap': time_snap_dict,
                        'quality_metrics': {
                            'last_completeness_pct': 100.0 if self.last_result else 0.0,
                            'last_packet_loss_pct': 0.0,
                            'last_snr_db': self.last_carrier_snr_db  # Carrier SNR from IQ data
                        }
                    }
                },
                'overall': {
                    'channels_processing': 1,
                    'total_minutes_processed': self.minutes_processed
                }
            }
            
            # Add D_clock result if available
            if self.last_result:
                status['channels'][self.channel_name]['d_clock_ms'] = self.last_result.d_clock_ms
                status['channels'][self.channel_name]['quality_grade'] = self.last_result.quality_grade
                if self.last_result.solution:
                    sol = self.last_result.solution
                    status['channels'][self.channel_name]['station'] = sol.station
                    status['channels'][self.channel_name]['propagation_mode'] = sol.propagation_mode
                    status['channels'][self.channel_name]['propagation_delay_ms'] = getattr(sol, 't_propagation_ms', 0)
                    status['channels'][self.channel_name]['n_hops'] = sol.n_hops
                    # Mode candidates for Mode Ridge visualization
                    status['channels'][self.channel_name]['mode_candidates'] = getattr(sol, 'mode_candidates', [])
            
            # Add convergence model state - shows convergence progress and lock status
            if hasattr(self, 'last_convergence_result') and self.last_convergence_result:
                conv = self.last_convergence_result
                status['channels'][self.channel_name]['convergence'] = {
                    'state': conv.state.value,
                    'is_locked': conv.is_locked,
                    'sample_count': conv.sample_count,
                    'uncertainty_ms': conv.uncertainty_ms if conv.uncertainty_ms != float('inf') else None,
                    'convergence_progress': conv.convergence_progress,
                    'residual_ms': conv.residual_ms,
                    'is_anomaly': conv.is_anomaly
                }
                # Also expose uncertainty at channel level for consensus weighting
                status['channels'][self.channel_name]['uncertainty_ms'] = (
                    conv.uncertainty_ms if conv.uncertainty_ms != float('inf') else 100.0
                )
            
            # Write atomically
            temp_file = self.status_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(status, f, indent=2)
            temp_file.replace(self.status_file)
            
        except Exception as e:
            logger.error(f"Failed to write status: {e}")
    
    def process_minute(self, minute_boundary: int) -> bool:
        """
        Process one minute of data.
        
        Args:
            minute_boundary: Unix timestamp of minute start
            
        Returns:
            True if processed successfully
        """
        if minute_boundary in self.processed_minutes:
            return False
        
        # Read DRF data for this minute
        data = self._read_drf_minute(minute_boundary)
        if data is None:
            logger.debug(f"No data available for minute {minute_boundary}")
            return False
        
        iq_samples, system_time, rtp_timestamp = data
        
        # Always calculate carrier SNR and power from the raw IQ samples
        # This works for all channels regardless of tone detection
        self.last_carrier_snr_db = self._calculate_carrier_snr(iq_samples)
        
        # Calculate carrier power in dB (for power graphs)
        power_linear = np.mean(np.abs(iq_samples) ** 2)
        self.last_carrier_power_db = 10 * np.log10(power_linear + 1e-12)
        
        # Decimate to 10Hz and accumulate for spectrograms
        self._decimate_to_10hz(iq_samples, minute_boundary)
        
        try:
            # Process through Phase 2 engine
            result = self.engine.process_minute(
                iq_samples=iq_samples,
                system_time=system_time,
                rtp_timestamp=rtp_timestamp
            )
            
            self.minutes_processed += 1
            self.last_processed_minute = minute_boundary
            self.processed_minutes.add(minute_boundary)
            
            if result:
                self.last_result = result
                
                # Write to CSV time series (coordinated path)
                self._write_clock_offset(result, minute_boundary, rtp_timestamp)
                
                # Write carrier power for power graphs
                solution = result.solution if hasattr(result, 'solution') else None
                time_snap = result.time_snap if hasattr(result, 'time_snap') else None
                channel_char = result.channel if hasattr(result, 'channel') else None
                
                self._write_carrier_power(
                    minute_boundary=minute_boundary,
                    power_db=self.last_carrier_power_db,
                    snr_db=self.last_carrier_snr_db,
                    wwv_tone_db=time_snap.wwv_snr_db if time_snap else None,
                    wwvh_tone_db=time_snap.wwvh_snr_db if time_snap else None,
                    station=solution.station if solution else None,
                    quality_grade=result.quality_grade
                )
                
                # Write discrimination method CSVs
                if time_snap:
                    self._write_tone_detections(minute_boundary, time_snap)
                
                if channel_char:
                    self._write_bcd_discrimination(minute_boundary, channel_char)
                    self._write_doppler(minute_boundary, channel_char)
                    self._write_station_id(minute_boundary, channel_char)
                    self._write_discrimination(minute_boundary, result, time_snap, channel_char)
                
                logger.info(
                    f"Processed minute {minute_boundary}: "
                    f"D_clock={result.d_clock_ms:+.2f}ms, "
                    f"quality={result.quality_grade}, "
                    f"carrier_snr={self.last_carrier_snr_db:.1f}dB"
                )
            else:
                logger.debug(
                    f"Processed minute {minute_boundary}: no timing result, "
                    f"carrier_snr={self.last_carrier_snr_db:.1f}dB"
                )
            
            # Write test signal for minutes 8 and 44 (channel sounding minutes)
            # Run OUTSIDE of if result: block since test signal detection doesn't need timing lock
            minute_number = (minute_boundary // 60) % 60
            if minute_number in [8, 44]:
                self._write_test_signal(minute_boundary, iq_samples, minute_number)
            
            return True
                
        except Exception as e:
            logger.error(f"Error processing minute {minute_boundary}: {e}")
            return False
    
    def run(self):
        """Main service loop."""
        self.running = True
        logger.info(f"Starting Phase 2 analytics service for {self.channel_name}")
        
        while self.running:
            try:
                # Get latest complete minute
                latest_minute = self._get_latest_minute()
                
                # Process any unprocessed minutes
                if latest_minute not in self.processed_minutes:
                    self.process_minute(latest_minute)
                
                # Write status
                self._write_status()
                
                # Sleep until next poll
                time.sleep(self.poll_interval)
                
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(self.poll_interval)
        
        logger.info("Phase 2 analytics service stopped")
    
    def stop(self):
        """Stop the service."""
        self.running = False


def main():
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description='Phase 2 Analytics Service - Process Digital RF to timing products'
    )
    parser.add_argument('--archive-dir', required=True, help='Digital RF archive directory')
    parser.add_argument('--output-dir', required=True, help='Output directory')
    parser.add_argument('--channel-name', required=True, help='Channel name')
    parser.add_argument('--frequency-hz', type=float, required=True, help='Center frequency')
    parser.add_argument('--sample-rate', type=int, default=20000, help='Sample rate')
    parser.add_argument('--grid-square', default='', help='Receiver grid square')
    parser.add_argument('--poll-interval', type=float, default=10.0, help='Poll interval')
    parser.add_argument('--log-level', default='INFO', help='Log level')
    
    # Additional args for compatibility with grape-analytics.sh
    parser.add_argument('--state-file', help='State file (not used)')
    parser.add_argument('--backfill-gaps', action='store_true', help='Backfill gaps (not used)')
    parser.add_argument('--max-backfill', type=int, help='Max backfill (not used)')
    parser.add_argument('--callsign', help='Callsign')
    parser.add_argument('--receiver-name', help='Receiver name')
    parser.add_argument('--psws-station-id', help='PSWS station ID')
    parser.add_argument('--psws-instrument-id', help='PSWS instrument ID')
    parser.add_argument('--latitude', type=float, help='Precise latitude (improves timing ~16μs)')
    parser.add_argument('--longitude', type=float, help='Precise longitude (improves timing ~16μs)')
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format='%(asctime)s %(levelname)s:%(name)s:%(message)s'
    )
    
    # Build station config
    station_config = {
        'callsign': args.callsign,
        'grid_square': args.grid_square,
        'receiver_name': args.receiver_name,
        'station_id': args.psws_station_id,
        'instrument_id': args.psws_instrument_id,
        'latitude': args.latitude,
        'longitude': args.longitude
    }
    
    # Create service
    service = Phase2AnalyticsService(
        archive_dir=Path(args.archive_dir),
        output_dir=Path(args.output_dir),
        channel_name=args.channel_name,
        frequency_hz=args.frequency_hz,
        sample_rate=args.sample_rate,
        receiver_grid=args.grid_square,
        station_config=station_config,
        poll_interval=args.poll_interval
    )
    
    # Handle signals
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, stopping...")
        service.stop()
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Run
    service.run()


if __name__ == '__main__':
    main()
