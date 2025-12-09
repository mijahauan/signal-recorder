"""
GRAPE Path Specification - Three-Phase Pipeline Architecture

This module provides the canonical path structure for all GRAPE data.
ALL producers and consumers MUST use these functions to avoid path mismatches.

SYNC VERSION: 2025-12-08-v3-discovery-fix
Must stay synchronized with web-ui/grape-paths.js

Change History:
  2025-12-08-v3: Issue 2.2 fix - discover_channels() now checks all phases
  2025-12-04-v2: Three-phase architecture paths
  2025-11-01-v1: Initial implementation

Three-Phase Architecture:

    data_root/
    ├── raw_archive/               # PHASE 1: Immutable Raw Archive (DRF)
    │   └── {CHANNEL}/              
    │       └── {YYYYMMDD}/         
    │           ├── {YYYY-MM-DDTHH}/ 
    │           │   └── rf@{ts}.h5  # 20 kHz complex64 IQ
    │           ├── drf_properties.h5
    │           └── metadata/       # NTP status, gaps, provenance
    │
    ├── phase2/                    # PHASE 2: Analytical Engine
    │   └── {CHANNEL}/
    │       ├── clock_offset/       # D_clock(t) time series
    │       ├── carrier_analysis/   # Amplitude, phase, Doppler
    │       ├── channel_quality/    # Delay spread, coherence
    │       ├── discrimination/     # WWV/WWVH per-minute
    │       ├── bcd_correlation/    # 100 Hz BCD analysis
    │       ├── tone_detections/    # 1000/1200 Hz markers
    │       ├── ground_truth/       # 440/500/600 Hz station ID
    │       └── state/              # Processing state
    │
    ├── products/                  # PHASE 3: Derived Products
    │   └── {CHANNEL}/
    │       ├── decimated/          # 10 Hz DRF time series
    │       ├── spectrograms/       # PNG images
    │       └── psws_upload/        # PSWS format files
    │
    ├── state/                     # Global state
    ├── status/                    # System status
    └── logs/                      # Global logs

CRITICAL: Use channel_name_to_key() for consistent channel naming.
"""

from pathlib import Path
from typing import Optional
import toml


def channel_name_to_key(channel_name: str) -> str:
    """Convert channel name to consistent key format.
    
    Args:
        channel_name: Human-readable name (e.g., "WWV 10 MHz", "CHU 3.33 MHz")
    
    Returns:
        Key format: "wwv10", "chu3.33", etc.
    
    Examples:
        >>> channel_name_to_key("WWV 10 MHz")
        'wwv10'
        >>> channel_name_to_key("WWV 2.5 MHz")
        'wwv2.5'
        >>> channel_name_to_key("CHU 3.33 MHz")
        'chu3.33'
    """
    parts = channel_name.split()
    if len(parts) < 2:
        # Fallback: underscored lowercase
        return channel_name.replace(' ', '_').lower()
    
    station = parts[0].lower()  # wwv, chu
    freq = parts[1]             # 10, 2.5, 3.33
    
    return f"{station}{freq}"


def channel_name_to_dir(channel_name: str) -> str:
    """Convert channel name to directory format.
    
    Args:
        channel_name: Human-readable name (e.g., "WWV 10 MHz")
    
    Returns:
        Directory format: "WWV_10_MHz", "CHU_3.33_MHz", etc.
    
    Examples:
        >>> channel_name_to_dir("WWV 10 MHz")
        'WWV_10_MHz'
    """
    return channel_name.replace(' ', '_')


def dir_to_channel_name(dir_name: str) -> str:
    """Convert directory name back to human-readable format.
    
    Args:
        dir_name: Directory name (e.g., "WWV_10_MHz")
    
    Returns:
        Human-readable: "WWV 10 MHz"
    """
    return dir_name.replace('_', ' ')


class GRAPEPaths:
    """Central path manager for GRAPE three-phase pipeline.
    
    Usage:
        from grape_recorder.paths import GRAPEPaths
        
        paths = GRAPEPaths('/tmp/grape-test')
        
        # Phase 1: Raw archive (immutable DRF)
        raw_dir = paths.get_raw_archive_dir('WWV 10 MHz')
        
        # Phase 2: Analytical engine outputs
        clock_dir = paths.get_clock_offset_dir('WWV 10 MHz')
        
        # Phase 3: Derived products
        spec_dir = paths.get_spectrograms_dir('WWV 10 MHz')
    """
    
    def __init__(self, data_root: str | Path):
        """Initialize path manager.
        
        Args:
            data_root: Root data directory (e.g., /tmp/grape-test)
        """
        self.data_root = Path(data_root)
    
    # ========================================================================
    # PHASE 1: RAW ARCHIVE (Immutable Digital RF)
    # ========================================================================
    
    def get_raw_archive_root(self) -> Path:
        """Get raw archive root directory.
        
        Returns: {data_root}/raw_archive/
        """
        return self.data_root / 'raw_archive'
    
    def get_raw_archive_dir(self, channel_name: str) -> Path:
        """Get raw archive directory for a channel.
        
        Returns: {data_root}/raw_archive/{CHANNEL}/
        """
        channel_dir = channel_name_to_dir(channel_name)
        return self.get_raw_archive_root() / channel_dir
    
    def get_raw_archive_date_dir(self, channel_name: str, date: str) -> Path:
        """Get raw archive date directory.
        
        Args:
            channel_name: Channel name
            date: Date in YYYYMMDD format
        
        Returns: {data_root}/raw_archive/{CHANNEL}/{YYYYMMDD}/
        """
        return self.get_raw_archive_dir(channel_name) / date
    
    def get_raw_archive_metadata_dir(self, channel_name: str, date: str) -> Path:
        """Get raw archive metadata directory.
        
        Returns: {data_root}/raw_archive/{CHANNEL}/{YYYYMMDD}/metadata/
        """
        return self.get_raw_archive_date_dir(channel_name, date) / 'metadata'
    
    # ========================================================================
    # PHASE 2: ANALYTICAL ENGINE
    # ========================================================================
    
    def get_phase2_root(self) -> Path:
        """Get Phase 2 root directory.
        
        Returns: {data_root}/phase2/
        """
        return self.data_root / 'phase2'
    
    def get_phase2_dir(self, channel_name: str) -> Path:
        """Get Phase 2 directory for a channel.
        
        Returns: {data_root}/phase2/{CHANNEL}/
        """
        channel_dir = channel_name_to_dir(channel_name)
        return self.get_phase2_root() / channel_dir
    
    def get_clock_offset_dir(self, channel_name: str) -> Path:
        """Get clock offset series directory.
        
        Contains D_clock(t) time series - the primary Phase 2 output.
        
        Returns: {data_root}/phase2/{CHANNEL}/clock_offset/
        """
        return self.get_phase2_dir(channel_name) / 'clock_offset'
    
    def get_carrier_analysis_dir(self, channel_name: str) -> Path:
        """Get carrier analysis directory.
        
        Contains amplitude, phase, and Doppler measurements.
        
        Returns: {data_root}/phase2/{CHANNEL}/carrier_analysis/
        """
        return self.get_phase2_dir(channel_name) / 'carrier_analysis'
    
    def get_channel_quality_dir(self, channel_name: str) -> Path:
        """Get channel quality metrics directory.
        
        Contains delay spread, coherence time, spreading factor.
        
        Returns: {data_root}/phase2/{CHANNEL}/channel_quality/
        """
        return self.get_phase2_dir(channel_name) / 'channel_quality'
    
    def get_discrimination_dir(self, channel_name: str) -> Path:
        """Get WWV/WWVH discrimination directory.
        
        Contains per-minute station identification results.
        
        Returns: {data_root}/phase2/{CHANNEL}/discrimination/
        """
        return self.get_phase2_dir(channel_name) / 'discrimination'
    
    def get_bcd_correlation_dir(self, channel_name: str) -> Path:
        """Get BCD correlation directory.
        
        Contains 100 Hz subcarrier cross-correlation results.
        
        Returns: {data_root}/phase2/{CHANNEL}/bcd_correlation/
        """
        return self.get_phase2_dir(channel_name) / 'bcd_correlation'
    
    def get_tone_detections_dir(self, channel_name: str) -> Path:
        """Get tone detections directory.
        
        Contains 1000/1200 Hz minute marker detection results.
        
        Returns: {data_root}/phase2/{CHANNEL}/tone_detections/
        """
        return self.get_phase2_dir(channel_name) / 'tone_detections'
    
    def get_ground_truth_dir(self, channel_name: str) -> Path:
        """Get ground truth directory.
        
        Contains 440/500/600 Hz exclusive tone detections.
        
        Returns: {data_root}/phase2/{CHANNEL}/ground_truth/
        """
        return self.get_phase2_dir(channel_name) / 'ground_truth'
    
    def get_doppler_dir(self, channel_name: str) -> Path:
        """Get Doppler estimation directory.
        
        Contains per-tick phase tracking and coherence estimates.
        
        Returns: {data_root}/phase2/{CHANNEL}/doppler/
        """
        return self.get_phase2_dir(channel_name) / 'doppler'
    
    def get_phase2_state_dir(self, channel_name: str) -> Path:
        """Get Phase 2 processing state directory.
        
        Returns: {data_root}/phase2/{CHANNEL}/state/
        """
        return self.get_phase2_dir(channel_name) / 'state'
    
    # ========================================================================
    # PHASE 3: DERIVED PRODUCTS
    # ========================================================================
    
    def get_products_root(self) -> Path:
        """Get products root directory.
        
        Returns: {data_root}/products/
        """
        return self.data_root / 'products'
    
    def get_products_dir(self, channel_name: str) -> Path:
        """Get products directory for a channel.
        
        Returns: {data_root}/products/{CHANNEL}/
        """
        channel_dir = channel_name_to_dir(channel_name)
        return self.get_products_root() / channel_dir
    
    def get_decimated_dir(self, channel_name: str) -> Path:
        """Get decimated time series directory.
        
        Contains 10 Hz DRF files for telemetry.
        
        Returns: {data_root}/products/{CHANNEL}/decimated/
        """
        return self.get_products_dir(channel_name) / 'decimated'
    
    def get_spectrograms_dir(self, channel_name: str) -> Path:
        """Get spectrograms directory for a channel.
        
        Returns: {data_root}/products/{CHANNEL}/spectrograms/
        """
        return self.get_products_dir(channel_name) / 'spectrograms'
    
    def get_psws_upload_dir(self, channel_name: str) -> Path:
        """Get PSWS upload directory.
        
        Contains files formatted for PSWS upload.
        
        Returns: {data_root}/products/{CHANNEL}/psws_upload/
        """
        return self.get_products_dir(channel_name) / 'psws_upload'
    
    # ========================================================================
    # LEGACY COMPATIBILITY (deprecated - use phase-specific methods)
    # ========================================================================
    
    def get_archive_dir(self, channel_name: str) -> Path:
        """DEPRECATED: Get legacy NPZ archive directory.
        
        Use get_raw_archive_dir() for new code.
        
        Returns: {data_root}/archives/{CHANNEL}/
        """
        channel_dir = channel_name_to_dir(channel_name)
        return self.data_root / 'archives' / channel_dir
    
    def get_archive_file(self, channel_name: str, timestamp: str, frequency_hz: int) -> Path:
        """DEPRECATED: Get path for legacy NPZ archive file.
        
        Returns: {data_root}/archives/{CHANNEL}/{timestamp}_{freq}_iq.npz
        """
        archive_dir = self.get_archive_dir(channel_name)
        return archive_dir / f"{timestamp}_{frequency_hz}_iq.npz"
    
    def get_analytics_dir(self, channel_name: str) -> Path:
        """DEPRECATED: Get legacy analytics directory.
        
        Use get_phase2_dir() for new code.
        
        Returns: {data_root}/analytics/{CHANNEL}/
        """
        channel_dir = channel_name_to_dir(channel_name)
        return self.data_root / 'analytics' / channel_dir
    
    def get_digital_rf_dir(self, channel_name: str) -> Path:
        """DEPRECATED: Get legacy Digital RF directory.
        
        Use get_decimated_dir() for Phase 3 decimated DRF.
        
        Returns: {data_root}/analytics/{CHANNEL}/digital_rf/
        """
        return self.get_analytics_dir(channel_name) / 'digital_rf'
    
    # Legacy analytics subdirectories (for backward compatibility)
    
    def get_tick_windows_dir(self, channel_name: str) -> Path:
        """DEPRECATED: Use get_doppler_dir() instead."""
        return self.get_analytics_dir(channel_name) / 'tick_windows'
    
    def get_station_id_440hz_dir(self, channel_name: str) -> Path:
        """DEPRECATED: Use get_ground_truth_dir() instead."""
        return self.get_analytics_dir(channel_name) / 'station_id_440hz'
    
    def get_bcd_discrimination_dir(self, channel_name: str) -> Path:
        """DEPRECATED: Use get_bcd_correlation_dir() instead."""
        return self.get_analytics_dir(channel_name) / 'bcd_discrimination'
    
    def get_test_signal_dir(self, channel_name: str) -> Path:
        """DEPRECATED: Use get_ground_truth_dir() instead."""
        return self.get_analytics_dir(channel_name) / 'test_signal'
    
    def get_timing_dir(self, channel_name: str) -> Path:
        """DEPRECATED: Use get_clock_offset_dir() instead."""
        return self.get_analytics_dir(channel_name) / 'timing'
    
    def get_quality_dir(self, channel_name: str) -> Path:
        """DEPRECATED: Use get_channel_quality_dir() instead."""
        return self.get_analytics_dir(channel_name) / 'quality'
    
    def get_analytics_logs_dir(self, channel_name: str) -> Path:
        """DEPRECATED: Get analytics logs directory."""
        return self.get_analytics_dir(channel_name) / 'logs'
    
    def get_analytics_status_dir(self, channel_name: str) -> Path:
        """DEPRECATED: Use get_phase2_state_dir() instead."""
        return self.get_analytics_dir(channel_name) / 'status'
    
    # ========================================================================
    # Spectrogram Paths (Legacy - now in products)
    # ========================================================================
    
    def get_spectrograms_root(self) -> Path:
        """DEPRECATED: Get legacy spectrograms root.
        
        Returns: {data_root}/spectrograms/
        """
        return self.data_root / 'spectrograms'
    
    def get_spectrograms_date_dir(self, date: str) -> Path:
        """DEPRECATED: Get spectrograms directory for a date.
        
        Returns: {data_root}/spectrograms/{YYYYMMDD}/
        """
        return self.get_spectrograms_root() / date
    
    def get_spectrogram_path(self, channel_name: str, date: str, spec_type: str = 'decimated') -> Path:
        """Get path for a spectrogram PNG.
        
        Now routes to Phase 3 products directory.
        
        Returns: {data_root}/products/{CHANNEL}/spectrograms/{date}_{type}.png
        """
        filename = f"{date}_{spec_type}.png"
        return self.get_spectrograms_dir(channel_name) / filename
    
    # ========================================================================
    # State Paths (Service persistence)
    # ========================================================================
    
    def get_state_dir(self) -> Path:
        """Get state directory.
        
        Returns: {data_root}/state/
        """
        return self.data_root / 'state'
    
    def get_analytics_state_file(self, channel_name: str) -> Path:
        """Get analytics state file for a channel.
        
        Args:
            channel_name: Channel name
        
        Returns: {data_root}/state/analytics-{key}.json
        
        Example:
            WWV 10 MHz -> analytics-wwv10.json
        """
        channel_key = channel_name_to_key(channel_name)
        return self.get_state_dir() / f"analytics-{channel_key}.json"
    
    def get_core_status_file(self) -> Path:
        """Get core recorder status file.
        
        Returns: {data_root}/status/core-recorder-status.json
        """
        return self.get_status_dir() / 'core-recorder-status.json'
    
    # ========================================================================
    # System Status Paths
    # ========================================================================
    
    def get_status_dir(self) -> Path:
        """Get system status directory.
        
        Returns: {data_root}/status/
        """
        return self.data_root / 'status'
    
    def get_analytics_service_status_file(self) -> Path:
        """Get analytics service status file.
        
        Returns: {data_root}/status/analytics-service-status.json
        """
        return self.get_status_dir() / 'analytics-service-status.json'
    
    def get_gpsdo_status_file(self) -> Path:
        """Get GPSDO monitor status file.
        
        Written by analytics service GPSDOMonitor, read by web-ui.
        
        Returns: {data_root}/status/gpsdo_status.json
        """
        return self.get_status_dir() / 'gpsdo_status.json'
    
    def get_timing_status_file(self) -> Path:
        """Get timing status file (primary time reference).
        
        Written by analytics service, read by web-ui.
        
        Returns: {data_root}/status/timing_status.json
        """
        return self.get_status_dir() / 'timing_status.json'
    
    # ========================================================================
    # Discovery Methods
    # ========================================================================
    
    # Directories that are not channels (exclude from discovery)
    _EXCLUDE_DIRS = {'status', 'metadata', 'state', 'logs', 'fusion', 'upload'}
    
    def discover_channels(self) -> list[str]:
        """Discover all channels from any available data source.
        
        Issue 2.2 Fix (2025-12-08): Now checks all three phases (raw_archive,
        phase2, products) to find channels. Previously only checked raw_archive,
        which missed channels that had Phase 2/3 data but no raw archive
        (e.g., after storage quota cleanup).
        
        This now matches the JavaScript implementation in grape-paths.js.
        
        Returns:
            List of channel names (human-readable format)
        """
        channels = set()
        
        # Check Phase 1: raw_archive/
        raw_dir = self.get_raw_archive_root()
        if raw_dir.exists():
            for channel_dir in raw_dir.iterdir():
                if channel_dir.is_dir() and channel_dir.name not in self._EXCLUDE_DIRS:
                    channels.add(dir_to_channel_name(channel_dir.name))
        
        # Check Phase 2: phase2/
        phase2_dir = self.get_phase2_root()
        if phase2_dir.exists():
            for channel_dir in phase2_dir.iterdir():
                if channel_dir.is_dir() and channel_dir.name not in self._EXCLUDE_DIRS:
                    channels.add(dir_to_channel_name(channel_dir.name))
        
        # Check Phase 3: products/
        products_dir = self.get_products_root()
        if products_dir.exists():
            for channel_dir in products_dir.iterdir():
                if channel_dir.is_dir() and channel_dir.name not in self._EXCLUDE_DIRS:
                    channels.add(dir_to_channel_name(channel_dir.name))
        
        # Fall back to legacy archives directory if nothing found
        if not channels:
            archives_dir = self.data_root / 'archives'
            if archives_dir.exists():
                for channel_dir in archives_dir.iterdir():
                    if channel_dir.is_dir() and channel_dir.name not in self._EXCLUDE_DIRS:
                        channels.add(dir_to_channel_name(channel_dir.name))
        
        return sorted(channels)
    
    def discover_phase2_channels(self) -> list[str]:
        """Discover channels with Phase 2 analytical results.
        
        Returns:
            List of channel names with Phase 2 data
        """
        phase2_dir = self.get_phase2_root()
        if not phase2_dir.exists():
            return []
        
        channels = []
        for channel_dir in phase2_dir.iterdir():
            if channel_dir.is_dir() and channel_dir.name not in self._EXCLUDE_DIRS:
                channels.append(dir_to_channel_name(channel_dir.name))
        
        return sorted(channels)
    
    def discover_products_channels(self) -> list[str]:
        """Discover channels with Phase 3 derived products.
        
        Returns:
            List of channel names with Phase 3 products
        """
        products_dir = self.get_products_root()
        if not products_dir.exists():
            return []
        
        channels = []
        for channel_dir in products_dir.iterdir():
            if channel_dir.is_dir() and channel_dir.name not in self._EXCLUDE_DIRS:
                channels.append(dir_to_channel_name(channel_dir.name))
        
        return sorted(channels)


def load_paths_from_config(config_path: Optional[str | Path] = None) -> GRAPEPaths:
    """Load GRAPEPaths from configuration file.
    
    Args:
        config_path: Path to grape-config.toml (default: ./config/grape-config.toml)
    
    Returns:
        GRAPEPaths instance configured from TOML
    
    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config is invalid
    """
    if config_path is None:
        # Default location
        config_path = Path(__file__).parent.parent.parent / 'config' / 'grape-config.toml'
    
    config_path = Path(config_path)
    
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(config_path, 'r') as f:
        config = toml.load(f)
    
    # Determine data root based on mode
    mode = config.get('recorder', {}).get('mode', 'test')
    
    if mode == 'production':
        data_root = config.get('recorder', {}).get('production_data_root', '/var/lib/grape-recorder')
    else:
        data_root = config.get('recorder', {}).get('test_data_root', '/tmp/grape-test')
    
    return GRAPEPaths(data_root)


# Convenience function for scripts
def get_paths(data_root: Optional[str | Path] = None, 
              config_path: Optional[str | Path] = None) -> GRAPEPaths:
    """Get GRAPEPaths instance.
    
    Args:
        data_root: Explicit data root (overrides config)
        config_path: Path to config file (if using config)
    
    Returns:
        GRAPEPaths instance
    
    Usage:
        # Use explicit data root
        paths = get_paths('/tmp/grape-test')
        
        # Use config file
        paths = get_paths(config_path='config/grape-config.toml')
        
        # Use default config
        paths = get_paths()
    """
    if data_root is not None:
        return GRAPEPaths(data_root)
    
    return load_paths_from_config(config_path)
