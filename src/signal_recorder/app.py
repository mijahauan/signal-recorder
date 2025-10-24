"""
Main application controller

Orchestrates all modules and provides daemon interface.
"""

import logging
import signal
import time
from pathlib import Path
from typing import Dict
from datetime import datetime, timezone

from .discovery import StreamManager
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
        self.stream_manager = StreamManager({'streams': config['recorder']['streams']})
        self.recorder_manager = RecorderManager(config)
        self.uploader = UploadManager(config['upload'], self.storage)
        
        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down")
        self.running = False
    
    def initialize_recorders(self):
        """Discover streams and start recorders"""
        logger.info("Discovering streams and starting recorders")
        
        # Discover all configured streams
        discovered_streams = self.stream_manager.discover_all()
        
        if not discovered_streams:
            logger.error("No streams discovered!")
            return False
        
        # Start recorders for each discovered stream
        for stream_config in self.config['recorder']['streams']:
            processor_type = stream_config.get('processor', 'grape')
            band_mapping = stream_config.get('band_mapping', {})
            
            for freq in stream_config.get('frequencies', []):
                metadata = self.stream_manager.get_metadata_for_frequency(freq)
                
                if metadata:
                    band_name = get_band_name_from_frequency(freq, band_mapping)
                    
                    try:
                        self.recorder_manager.start_recorder(metadata, band_name)
                    except Exception as e:
                        logger.error(f"Failed to start recorder for {band_name}: {e}")
                else:
                    logger.warning(f"No stream found for {freq/1e6:.3f} MHz")
        
        # Log recorder status
        status = self.recorder_manager.get_status()
        logger.info(f"Started {len(status)} recorders")
        for ssrc, info in status.items():
            logger.info(f"  {info['band_name']}: {info['frequency']/1e6:.3f} MHz → {info['output_dir']}")
        
        return True
    
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
                if current_time - last_process_check >= process_interval:
                    self._process_complete_days()
                    last_process_check = current_time
                
                # Process upload queue
                if current_time - last_upload_check >= upload_interval:
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
        self.uploader.process_queue()
    
    def _process_complete_days(self):
        """Check for complete days and process them"""
        logger.info("Checking for complete days to process")
        
        # Get dates that might need processing (last 7 days)
        dates = self.storage.get_dates_needing_processing(max_age_days=7)
        
        # Get yesterday's date (don't process today)
        yesterday = datetime.now(timezone.utc).date() - datetime.timedelta(days=1)
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
            self.config.get('processors', {}).get(processor_type, {})
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
            self._enqueue_upload(date, band, result)
        else:
            logger.error(f"Processing failed for {date}/{band}")
    
    def _get_processor_config_for_band(self, band: str) -> Dict:
        """Get processor configuration for a band"""
        for stream_config in self.config['recorder']['streams']:
            band_mapping = stream_config.get('band_mapping', {})
            
            # Check if this band is in the mapping
            for freq, band_name in band_mapping.items():
                if band_name == band:
                    return stream_config
        
        # Default to first stream config
        if self.config['recorder']['streams']:
            return self.config['recorder']['streams'][0]
        
        return {}
    
    def _enqueue_upload(self, date: str, band: str, dataset_path: Path):
        """Enqueue dataset for upload"""
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
        self.uploader._save_queue()
        
        logger.info("Shutdown complete")
    
    def get_status(self) -> Dict:
        """Get application status"""
        return {
            'recorders': self.recorder_manager.get_status(),
            'uploads': self.uploader.get_status(),
        }

