#!/usr/bin/env python3
"""
GRAPE Core Recorder - Battle-Tested Data Acquisition

Minimal, rock-solid recorder that ONLY writes NPZ archives.
NO analytics, NO tone detection, NO decimation, NO quality metrics.

Responsibilities:
1. Receive RTP packets from ka9q-radio multicast
2. Resequence packets (handle out-of-order delivery)
3. Detect gaps via RTP timestamp discontinuities
4. Fill gaps with zeros (maintain sample count integrity)
5. Write complete NPZ archives with RTP timestamps

That's it. Everything else is analytics (separate process).
"""

import logging
import signal
import sys
import os
import time
import json
import threading
from pathlib import Path
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timezone
import subprocess

from ..core.rtp_receiver import RTPReceiver
from ..channel_manager import ChannelManager
from ..radiod_health import RadiodHealthChecker
from ..quota_manager import QuotaManager
from .grape_recorder import GrapeRecorder, GrapeConfig

logger = logging.getLogger(__name__)


@dataclass
class ChannelConfig:
    """Configuration for a single channel"""
    ssrc: int
    frequency_hz: float
    sample_rate: int
    description: str


class CoreRecorder:
    """
    Core recorder: RTP → NPZ archives
    
    Design principles:
    - Minimal code (~200 lines)
    - Conservative error handling (never crash)
    - No dependencies on analytics code
    - Optimized for reliability over features
    """
    
    def __init__(self, config: dict):
        """
        Initialize core recorder
        
        Args:
            config: Configuration dict with:
                - multicast_address: RTP multicast group
                - port: RTP port (default 5004)
                - output_dir: Base directory for archives
                - station: Station metadata (callsign, grid, instrument_id)
                - channels: List of channel configs
                - status_address: Radiod status address for channel management
        """
        self.config = config
        self.output_dir = Path(config['output_dir'])
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Channel management for auto-recovery
        self.status_address = config.get('status_address', '239.192.152.141')
        self.channel_manager = ChannelManager(self.status_address)
        self.health_checker = RadiodHealthChecker(self.status_address)
        self.channel_configs = {}  # Store for recreation
        
        # RTP receiver (shared across channels)
        self.rtp_receiver = RTPReceiver(
            multicast_address=config['multicast_address'],
            port=config.get('port', 5004)
        )
        
        # Per-channel recorders (using new GrapeRecorder)
        self.channels: Dict[int, GrapeRecorder] = {}
        
        # Initialize channels with GrapeRecorder
        station_config = config.get('station', {})
        for ch_cfg in config.get('channels', []):
            # Store config for recovery
            self.channel_configs[ch_cfg['ssrc']] = ch_cfg
            
            grape_config = GrapeConfig(
                ssrc=ch_cfg['ssrc'],
                frequency_hz=ch_cfg['frequency_hz'],
                sample_rate=ch_cfg['sample_rate'],
                description=ch_cfg['description'],
                output_dir=self.output_dir,
                station_config=station_config,
                startup_buffer_duration=ch_cfg.get('startup_buffer_duration', 120.0),
                tone_check_interval=ch_cfg.get('tone_check_interval', 300.0),
            )
            
            recorder = GrapeRecorder(
                config=grape_config,
                rtp_receiver=self.rtp_receiver,
                get_ntp_status=self.get_ntp_status,
            )
            self.channels[ch_cfg['ssrc']] = recorder
            
            # Note: GrapeRecorder registers its own callbacks when start() is called
        
        logger.info(f"CoreRecorder initialized: {len(self.channels)} channels")
        
        # Centralized NTP status cache (shared by all channels)
        # Updated periodically in main loop to avoid subprocess calls in critical path
        self.ntp_status = {'offset_ms': None, 'synced': False, 'last_update': 0}
        self.ntp_status_lock = threading.Lock()
        
        # Status tracking
        self.start_time = time.time()
        self.status_file = self.output_dir / 'status' / 'core-recorder-status.json'
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Graceful shutdown
        self.running = False
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def run(self):
        """Main run loop"""
        logger.info("Starting GRAPE Core Recorder")
        logger.info("Responsibility: RTP → NPZ archives (no analytics)")
        
        # Ensure all channels exist in radiod before starting
        logger.info("Verifying radiod channels...")
        self._ensure_channels_exist()
        
        # Start RTP receiver
        self.rtp_receiver.start()
        self.running = True
        
        # Start all channel recorders
        for ssrc, recorder in self.channels.items():
            recorder.start()
            logger.info(f"Started recorder for SSRC {ssrc:x}")
        
        logger.info("Core recorder running. Press Ctrl+C to stop.")
        
        # Write initial status
        self._write_status()
        
        # Initialize quota manager (75% threshold, keep min 7 days)
        self.quota_manager = QuotaManager(
            data_root=self.output_dir,
            threshold_percent=75.0,
            min_days_to_keep=7,
            dry_run=False
        )
        
        # Main loop (status updates and health monitoring)
        last_status_time = 0
        last_health_check = 0
        last_quota_check = 0
        try:
            while self.running:
                time.sleep(1)
                now = time.time()
                
                # Update NTP status cache (every 10 seconds)
                # This is the ONLY place NTP subprocess calls happen
                if now - last_status_time >= 10:
                    self._update_ntp_status()
                    self._write_status()
                    last_status_time = now
                
                # Periodic status logging (every 60 seconds)
                if int(now) % 60 == 0:
                    self._log_status()
                
                # Health monitoring (every 30 seconds)
                if now - last_health_check >= 30:
                    self._monitor_stream_health()
                    last_health_check = now
                
                # Quota enforcement (every 5 minutes)
                if now - last_quota_check >= 300:
                    self._enforce_quota()
                    last_quota_check = now
        
        except KeyboardInterrupt:
            logger.info("Received interrupt signal")
        
        finally:
            self._shutdown()
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
    
    def _write_status(self):
        """Write current status to JSON file for web-ui monitoring"""
        try:
            status = {
                'service': 'core_recorder',
                'version': '2.0',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'uptime_seconds': int(time.time() - self.start_time),
                'pid': os.getpid(),
                'channels': {},
                'overall': {
                    'channels_active': 0,
                    'channels_total': len(self.channels),
                    'total_npz_written': 0,
                    'total_packets_received': 0,
                    'total_gaps_detected': 0
                }
            }
            
            # Gather per-channel stats
            for ssrc, recorder in self.channels.items():
                ch_stats = recorder.get_status()
                status['channels'][hex(ssrc)] = ch_stats
                
                # Aggregate overall stats
                if ch_stats.get('packets_received', 0) > 0:
                    status['overall']['channels_active'] += 1
                status['overall']['total_npz_written'] += ch_stats.get('npz_files_written', 0)
                status['overall']['total_packets_received'] += ch_stats.get('packets_received', 0)
                # GrapeRecorder doesn't track gaps the same way
                # status['overall']['total_gaps_detected'] += ch_stats.get('gaps_detected', 0)
            
            # Write atomically (write to temp file, then rename)
            temp_file = self.status_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(status, f, indent=2)
            temp_file.replace(self.status_file)
            
        except Exception as e:
            logger.error(f"Failed to write status file: {e}")
    
    def _log_status(self):
        """Log periodic status"""
        for ssrc, recorder in self.channels.items():
            stats = recorder.get_stats()
            logger.info(
                f"{recorder.config.description}: "
                f"{stats.get('minutes_written', 0)} minutes, "
                f"{stats.get('packets_received', 0)} packets, "
                f"state={stats.get('state', 'unknown')}"
            )
    
    def _update_ntp_status(self):
        """
        Update centralized NTP status cache (called every 10 seconds in main loop).
        
        This is the ONLY place where NTP subprocess calls happen, eliminating
        redundant calls from ChannelProcessor and CoreNPZWriter critical paths.
        """
        try:
            offset_ms = self._get_ntp_offset_subprocess()
            
            with self.ntp_status_lock:
                self.ntp_status = {
                    'offset_ms': offset_ms,
                    'synced': (offset_ms is not None and abs(offset_ms) < 100),
                    'last_update': time.time()
                }
                
        except Exception as e:
            logger.warning(f"NTP status update failed: {e}")
    
    def get_ntp_status(self):
        """
        Thread-safe accessor for NTP status (used by ChannelProcessors).
        
        Returns:
            dict with keys: offset_ms, synced, last_update
        """
        with self.ntp_status_lock:
            return self.ntp_status.copy()
    
    @staticmethod
    def _get_ntp_offset_subprocess() -> Optional[float]:
        """
        Get NTP offset in milliseconds via subprocess call.
        
        Called ONLY from _update_ntp_status() every 10 seconds.
        
        Returns:
            NTP offset in ms (positive = system ahead of NTP)
            None if NTP not available
        """
        try:
            # Try chronyc first
            result = subprocess.run(
                ['chronyc', 'tracking'],
                capture_output=True, text=True, timeout=2
            )
            
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'System time' in line:
                        # Parse "System time : 0.000012345 seconds fast of NTP time"
                        parts = line.split(':')
                        if len(parts) >= 2:
                            offset_str = parts[1].strip().split()[0]
                            offset_seconds = float(offset_str)
                            return offset_seconds * 1000.0  # Convert to ms
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            pass
        
        try:
            # Try ntpq as fallback
            result = subprocess.run(
                ['ntpq', '-c', 'rv 0 offset'],
                capture_output=True, text=True, timeout=2
            )
            
            if result.returncode == 0:
                # Parse "offset=-0.123"
                for part in result.stdout.split(','):
                    if 'offset=' in part:
                        offset_str = part.split('=')[1].strip()
                        return float(offset_str)  # Already in ms
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            pass
        
        return None
    
    def _ensure_channels_exist(self):
        """
        Verify all configured channels exist in radiod, create if missing.
        Called at startup.
        """
        try:
            # Build channel specifications
            required_channels = []
            for ssrc, ch_cfg in self.channel_configs.items():
                required_channels.append({
                    'ssrc': ssrc,
                    'frequency_hz': ch_cfg['frequency_hz'],
                    'preset': ch_cfg.get('preset', 'iq'),
                    'sample_rate': ch_cfg.get('sample_rate', 16000),
                    'agc': ch_cfg.get('agc', 0),
                    'gain': ch_cfg.get('gain', 0),
                    'description': ch_cfg['description']
                })
            
            if not required_channels:
                logger.warning("No channels configured")
                return
            
            # Ensure channels exist (create missing ones)
            logger.info(f"Ensuring {len(required_channels)} channels exist in radiod...")
            success = self.channel_manager.ensure_channels_exist(
                required_channels, 
                update_existing=False
            )
            
            if success:
                logger.info("✓ All channels verified/created in radiod")
            else:
                logger.warning("⚠ Some channels may be missing - recording may fail")
                
        except Exception as e:
            logger.error(f"Channel verification failed: {e}", exc_info=True)
            logger.warning("Continuing anyway - some channels may work")
    
    def _monitor_stream_health(self):
        """
        Monitor stream health and recreate dead channels.
        Called periodically (every 30 seconds) in main loop.
        """
        try:
            # Check if radiod is alive
            if not self.health_checker.is_radiod_alive(timeout_sec=3.0):
                logger.warning("Radiod appears down - skipping health check")
                return
            
            # Check each channel for stale packets
            for ssrc, recorder in self.channels.items():
                # Check if channel has gone silent
                if not recorder.is_healthy():
                    logger.warning(
                        f"Channel {recorder.config.description} (SSRC {ssrc:x}) appears dead - "
                        f"no packets in {recorder.get_silence_duration():.0f}s"
                    )
                    
                    # Verify channel still exists in radiod
                    if not self.health_checker.verify_channel_exists(ssrc):
                        logger.error(
                            f"Channel {recorder.config.description} missing from radiod - "
                            f"attempting recreation..."
                        )
                        self._recreate_channel(ssrc)
                    else:
                        logger.info(
                            f"Channel {recorder.config.description} exists in radiod but no data - "
                            f"possible network/multicast issue"
                        )
                        
        except Exception as e:
            logger.error(f"Health monitoring error: {e}", exc_info=True)
    
    def _enforce_quota(self):
        """
        Enforce disk quota by removing old files if over threshold.
        Called periodically (every 5 minutes) in main loop.
        """
        try:
            result = self.quota_manager.enforce_quota()
            
            if result.get('files_deleted', 0) > 0:
                logger.info(
                    f"Quota enforcement: deleted {result['files_deleted']} files, "
                    f"freed {result['bytes_freed'] / 1024 / 1024 / 1024:.2f} GB, "
                    f"usage now {result['final_usage_percent']:.1f}%"
                )
        except Exception as e:
            logger.error(f"Quota enforcement error: {e}", exc_info=True)
    
    def _recreate_channel(self, ssrc: int):
        """
        Recreate a missing channel in radiod.
        
        Args:
            ssrc: SSRC of the channel to recreate
        """
        if ssrc not in self.channel_configs:
            logger.error(f"No config found for SSRC {ssrc:x} - cannot recreate")
            return
        
        ch_cfg = self.channel_configs[ssrc]
        
        try:
            logger.info(f"Recreating channel {ch_cfg['description']} (SSRC {ssrc:x})...")
            
            # Build channel spec
            channel_spec = {
                'ssrc': ssrc,
                'frequency_hz': ch_cfg['frequency_hz'],
                'preset': ch_cfg.get('preset', 'iq'),
                'sample_rate': ch_cfg.get('sample_rate', 16000),
                'agc': ch_cfg.get('agc', 0),
                'gain': ch_cfg.get('gain', 0),
                'description': ch_cfg['description']
            }
            
            # Create the channel
            success = self.channel_manager.create_channel(
                ssrc=channel_spec['ssrc'],
                frequency_hz=channel_spec['frequency_hz'],
                preset=channel_spec['preset'],
                sample_rate=channel_spec['sample_rate'],
                agc=channel_spec['agc'],
                gain=channel_spec['gain'],
                description=channel_spec['description']
            )
            
            if success:
                logger.info(f"✓ Successfully recreated channel {ch_cfg['description']}")
                # Reset processor packet timer to avoid immediate re-trigger
                if ssrc in self.channels:
                    self.channels[ssrc].reset_health()
            else:
                logger.error(f"✗ Failed to recreate channel {ch_cfg['description']}")
                
        except Exception as e:
            logger.error(f"Channel recreation exception for SSRC {ssrc:x}: {e}", exc_info=True)
    
    def _shutdown(self):
        """Graceful shutdown"""
        logger.info("Shutting down core recorder...")
        
        # Stop all channel recorders first (they unregister callbacks)
        for ssrc, recorder in self.channels.items():
            try:
                recorder.stop()
            except Exception as e:
                logger.error(f"Error stopping channel {ssrc}: {e}")
        
        # Stop RTP receiver
        self.rtp_receiver.stop()
        
        logger.info("Core recorder stopped")


def main():
    """Entry point for core recorder"""
    import toml
    import argparse
    
    parser = argparse.ArgumentParser(description='GRAPE Core Recorder')
    parser.add_argument('--config', required=True, help='Configuration file (TOML)')
    args = parser.parse_args()
    
    # Load TOML configuration
    toml_config = toml.load(args.config)
    
    # Setup logging
    log_level = toml_config.get('logging', {}).get('level', 'INFO')
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Transform TOML config to CoreRecorder format
    recorder_config = toml_config.get('recorder', {})
    mode = recorder_config.get('mode', 'test')
    
    # Determine output directory based on mode
    if mode == 'production':
        output_dir = recorder_config.get('production_data_root', '/var/lib/signal-recorder')
    else:
        output_dir = recorder_config.get('test_data_root', '/tmp/grape-test')
    
    # Get KA9Q multicast info
    ka9q_config = toml_config.get('ka9q', {})
    status_address = ka9q_config.get('status_address', 'bee1-hf-status.local')
    
    # Resolve status address to multicast group
    # For KA9Q, the default multicast group is 239.1.2.X where X depends on config
    # Default to standard group
    multicast_address = '239.1.2.55'  # Standard KA9Q multicast group
    
    # Build config dict for CoreRecorder
    config = {
        'output_dir': output_dir,
        'multicast_address': multicast_address,
        'port': 5004,
        'status_address': status_address,  # For channel management
        'station': toml_config.get('station', {}),
        'channels': recorder_config.get('channels', [])
    }
    
    logger.info(f"Starting in {mode.upper()} mode")
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Multicast: {multicast_address}:5004")
    logger.info(f"Channels configured: {len(config['channels'])}")
    
    # Create and run recorder
    recorder = CoreRecorder(config)
    recorder.run()


if __name__ == '__main__':
    main()
