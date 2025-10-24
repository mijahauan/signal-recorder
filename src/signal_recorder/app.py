"""
Main application controller

Orchestrates all modules and provides daemon interface.
"""

import logging
import signal
import time
from pathlib import Path
from typing import Dict
from datetime import datetime, timezone, timedelta

from .channel_manager import ChannelManager
from .control_discovery import discover_channels_via_control, ChannelInfo
from .discovery import StreamMetadata, Encoding
from .recorder import RecorderManager, get_band_name_from_frequency
from .storage import StorageManager
from .processor import get_processor
from .uploader import UploadManager

logger = logging.getLogger(__name__)


class SignalRecorderApp:
    """Main application controller"""
    
    def __init__(self, config: Dict):
        """
        Initialize application
        
        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.running = False
        
        # Initialize modules
        logger.info("Initializing Signal Recorder application")
        
        self.storage = StorageManager(config)
        
        # Initialize channel manager if auto-create is enabled
        ka9q_config = config.get('ka9q', {})
        self.status_address = ka9q_config.get('status_address')
        self.auto_create_channels = ka9q_config.get('auto_create_channels', False)
        
        if self.auto_create_channels:
            logger.info("Automatic channel creation enabled")
            self.channel_manager = ChannelManager(self.status_address)
        else:
            self.channel_manager = None
        
        self.recorder_manager = RecorderManager(config)
        
        # Initialize uploader if configured
        upload_config = config.get('uploader', {})
        if upload_config.get('enabled', False) or upload_config.get('upload_enabled', False):
            self.uploader = UploadManager(upload_config, self.storage)
        else:
            self.uploader = None
            logger.info("Uploader disabled")
        
        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down")
        self.running = False
    
    def initialize_recorders(self):
        """Create channels (if needed) and start recorders"""
        logger.info("Initializing channels and recorders")
        
        # Get channel configurations
        channels_config = self.config.get('recorder', {}).get('channels', [])
        
        if not channels_config:
            logger.error("No channels configured in [recorder.channels]")
            return False
        
        # Create channels if auto-create is enabled
        if self.auto_create_channels and self.channel_manager:
            logger.info(f"Creating {len(channels_config)} channels in radiod")
            
            # Convert to required format
            required_channels = []
            for ch in channels_config:
                if not ch.get('enabled', True):
                    continue
                    
                required_channels.append({
                    'ssrc': ch.get('ssrc'),
                    'frequency_hz': ch.get('frequency_hz'),
                    'preset': ch.get('preset', 'iq'),
                    'sample_rate': ch.get('sample_rate'),
                    'description': ch.get('description', '')
                })
            
            # Ensure channels exist
            if not self.channel_manager.ensure_channels_exist(required_channels):
                logger.error("Failed to create all required channels")
                return False
        
        # Discover channels from radiod
        logger.info(f"Discovering channels from {self.status_address}")
        discovered_channels = discover_channels_via_control(self.status_address)
        
        if not discovered_channels:
            logger.error("No channels discovered from radiod!")
            return False
        
        logger.info(f"Discovered {len(discovered_channels)} channels from radiod")
        
        # Start recorders for each configured channel
        started_count = 0
        for ch_config in channels_config:
            if not ch_config.get('enabled', True):
                logger.info(f"Skipping disabled channel {ch_config.get('ssrc')}")
                continue
            
            ssrc = ch_config.get('ssrc')
            
            if ssrc not in discovered_channels:
                logger.warning(f"Channel {ssrc} not found in radiod")
                continue
            
            channel_info = discovered_channels[ssrc]
            
            # Determine band name
            freq = ch_config.get('frequency_hz')
            band_name = ch_config.get('description', f"{freq/1e6:.3f}_MHz")
            
            # Get processor type
            processor_type = ch_config.get('processor', 'grape')
            
            try:
                # Convert ChannelInfo to StreamMetadata expected by recorder
                metadata = StreamMetadata(
                    ssrc=channel_info.ssrc,
                    frequency=channel_info.frequency,
                    sample_rate=channel_info.sample_rate,
                    channels=2,  # IQ is always 2 channels
                    encoding=Encoding.F32LE,  # Assume float32 for IQ
                    description=channel_info.preset,
                    multicast_address=channel_info.multicast_address,
                    port=channel_info.port
                )
                
                self.recorder_manager.start_recorder(metadata, band_name)
                started_count += 1
                logger.info(f"Started recorder for {band_name}: {freq/1e6:.3f} MHz @ {channel_info.multicast_address}:{channel_info.port}")
            except Exception as e:
                logger.error(f"Failed to start recorder for {band_name}: {e}", exc_info=True)
        
        logger.info(f"Started {started_count}/{len(channels_config)} recorders")
        
        return started_count > 0
    
    def run_daemon(self):
        """Run as background daemon"""
        logger.info("Starting Signal Recorder daemon")
        
        # Initialize recorders
        if not self.initialize_recorders():
            logger.error("Failed to initialize recorders")
            return
        
        self.running = True
        
        # Main loop
        last_process_check = 0
        last_upload_check = 0
        process_interval = 3600  # Check for processing every hour
        upload_interval = 600  # Process upload queue every 10 minutes
        
        try:
            while self.running:
                current_time = time.time()
                
                # Check for dates needing processing
                processor_config = self.config.get('processor', {})
                if processor_config.get('enabled', True):
                    if current_time - last_process_check >= process_interval:
                        self._process_complete_days()
                        last_process_check = current_time
                
                # Process upload queue
                if self.uploader and (current_time - last_upload_check >= upload_interval):
                    self.uploader.process_queue()
                    self.uploader.clear_completed()
                    last_upload_check = current_time
                
                # Sleep for a bit
                time.sleep(60)  # Wake up every minute
        
        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)
        
        finally:
            self.shutdown()
    
    def run_once(self, date: str):
        """
        Process a specific date (for manual/cron execution)
        
        Args:
            date: Date string (YYYYMMDD)
        """
        logger.info(f"Processing date: {date}")
        
        self._process_date(date)
        
        # Process upload queue
        if self.uploader:
            self.uploader.process_queue()
    
    def _process_complete_days(self):
        """Check for complete days and process them"""
        logger.info("Checking for complete days to process")
        
        # Get dates that might need processing (last 7 days)
        dates = self.storage.get_dates_needing_processing(max_age_days=7)
        
        # Get yesterday's date (don't process today)
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        yesterday_str = yesterday.strftime("%Y%m%d")
        
        for date in dates:
            # Only process dates up to yesterday
            if date <= yesterday_str:
                self._process_date(date)
    
    def _process_date(self, date: str):
        """
        Process all bands for a given date
        
        Args:
            date: Date string (YYYYMMDD)
        """
        logger.info(f"Processing date: {date}")
        
        # Get all bands for this date
        bands = self.storage.get_bands_for_date(date)
        
        if not bands:
            logger.warning(f"No bands found for date {date}")
            return
        
        logger.info(f"Found {len(bands)} bands for {date}: {bands}")
        
        # Process each band
        for band in bands:
            self._process_band(date, band)
    
    def _process_band(self, date: str, band: str):
        """
        Process a specific band for a date
        
        Args:
            date: Date string (YYYYMMDD)
            band: Band name
        """
        logger.info(f"Processing {date}/{band}")
        
        # Load processing state
        state = self.storage.load_state(date, band)
        
        # Skip if already uploaded
        if state.upload_complete:
            logger.info(f"Already uploaded: {date}/{band}")
            return
        
        # Skip if already processed
        if state.drf_created and state.drf_path:
            logger.info(f"Already processed: {date}/{band}, enqueueing for upload")
            if self.uploader:
                self._enqueue_upload(date, band, Path(state.drf_path))
            return
        
        # Update file counts
        state = self.storage.update_file_counts(date, band)
        
        # Get processor for this band
        processor_config = self._get_processor_config_for_band(band)
        if not processor_config:
            logger.error(f"No processor configuration found for band {band}")
            return
        
        processor_type = processor_config.get('processor', 'grape')
        processor = get_processor(
            processor_type,
            self.config.get('processor', {}).get(processor_type, {})
        )
        
        # Get files
        band_dir = self.storage.get_band_dir(date, band)
        files = self.storage.scan_files(date, band)
        
        if not files:
            logger.warning(f"No files found for {date}/{band}")
            return
        
        # Validate files
        validation = processor.validate_files(files)
        
        logger.info(f"Validation: {validation['files_found']}/{validation['files_expected']} files "
                   f"({validation['completeness']:.1f}% complete)")
        
        if not validation['valid']:
            logger.warning(f"Incomplete data for {date}/{band}, attempting repair")
            
            # Attempt repair
            if not processor.repair_gaps(band_dir, validation['missing_minutes']):
                logger.error(f"Failed to repair gaps for {date}/{band}")
                return
            
            # Re-scan files after repair
            files = self.storage.scan_files(date, band)
        
        # Process
        output_dir = self.storage.get_output_dir(date, band)
        
        metadata = {
            'date': date,
            'band': band,
            'station_id': self.config['station']['id'],
            'instrument_id': self.config['station']['instrument_id'],
            'callsign': self.config['station']['callsign'],
            'grid_square': self.config['station']['grid_square'],
        }
        
        logger.info(f"Processing {len(files)} files for {date}/{band}")
        
        result = processor.process(band_dir, output_dir, processor_config, metadata)
        
        if result:
            logger.info(f"Processing successful: {result}")
            
            # Mark as processed
            if processor.get_upload_format() == "digital_rf":
                self.storage.mark_drf_created(date, band, result)
            
            # Enqueue for upload
            if self.uploader:
                self._enqueue_upload(date, band, result)
        else:
            logger.error(f"Processing failed for {date}/{band}")
    
    def _get_processor_config_for_band(self, band: str) -> Dict:
        """Get processor configuration for a band"""
        # Find the channel config for this band
        for ch_config in self.config.get('recorder', {}).get('channels', []):
            description = ch_config.get('description', '')
            if description == band or f"{ch_config.get('frequency_hz', 0)/1e6:.3f}_MHz" == band:
                return ch_config
        
        # Return default config
        return {}
    
    def _enqueue_upload(self, date: str, band: str, dataset_path: Path):
        """Enqueue dataset for upload"""
        if not self.uploader:
            return
            
        metadata = {
            'date': date,
            'band': band,
            'station_id': self.config['station']['id'],
            'instrument_id': self.config['station']['instrument_id'],
            'callsign': self.config['station']['callsign'],
            'grid_square': self.config['station']['grid_square'],
        }
        
        self.uploader.enqueue(dataset_path, metadata)
    
    def shutdown(self):
        """Shutdown application gracefully"""
        logger.info("Shutting down Signal Recorder")
        
        # Stop all recorders
        self.recorder_manager.stop_all()
        
        # Save upload queue
        if self.uploader:
            self.uploader._save_queue()
        
        # Close channel manager
        if self.channel_manager:
            self.channel_manager.close()
        
        logger.info("Shutdown complete")
    
    def get_status(self) -> Dict:
        """Get application status"""
        status = {
            'recorders': self.recorder_manager.get_status(),
        }
        
        if self.uploader:
            status['uploads'] = self.uploader.get_status()
        
        return status


