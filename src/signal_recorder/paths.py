"""
GRAPE Path Specification - Single Source of Truth for Data Locations

This module provides the canonical path structure for all GRAPE data.
ALL producers and consumers MUST use these functions to avoid path mismatches.

Architecture:
    data_root/
    ├── archives/              # Raw NPZ archives (16 kHz IQ)
    │   └── {CHANNEL}/         # e.g., WWV_10_MHz
    │       └── {YYYYMMDDTHHMMSZ}_{FREQ}_iq.npz
    │
    ├── analytics/             # Per-channel analytics products
    │   └── {CHANNEL}/
    │       ├── digital_rf/    # Digital RF files (10 Hz decimated)
    │       │   └── {YYYYMMDD}/{CALL_GRID}/{RECEIVER}/{OBS}/{CHANNEL}/*.h5
    │       ├── discrimination/ # WWV/WWVH discrimination data
    │       ├── quality/       # Quality metrics
    │       ├── logs/          # Processing logs
    │       └── status/        # Runtime status
    │
    ├── spectrograms/          # Generated spectrograms (web UI)
    │   └── {YYYYMMDD}/
    │       └── {CHANNEL}_{YYYYMMDD}_{type}_spectrogram.png
    │
    ├── state/                 # Service state files
    │   ├── analytics-{channel_key}.json
    │   └── core-recorder-status.json
    │
    └── status/                # System-wide status
        └── analytics-service-status.json

CRITICAL: Use channel_name_to_key() for consistent channel naming conversions.
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
    """Central path manager for GRAPE data structures.
    
    Usage:
        from signal_recorder.paths import GRAPEPaths
        
        paths = GRAPEPaths('/tmp/grape-test')
        
        # Get archive path for a channel
        npz_dir = paths.get_archive_dir('WWV 10 MHz')
        
        # Get digital RF directory
        drf_dir = paths.get_digital_rf_dir('WWV 10 MHz')
        
        # Get spectrogram output path
        spec_path = paths.get_spectrogram_path('WWV 10 MHz', '20251115', 'carrier')
    """
    
    def __init__(self, data_root: str | Path):
        """Initialize path manager.
        
        Args:
            data_root: Root data directory (e.g., /tmp/grape-test)
        """
        self.data_root = Path(data_root)
    
    # ========================================================================
    # Archive Paths (Raw NPZ files)
    # ========================================================================
    
    def get_archive_dir(self, channel_name: str) -> Path:
        """Get archive directory for a channel.
        
        Returns: {data_root}/archives/{CHANNEL}/
        """
        channel_dir = channel_name_to_dir(channel_name)
        return self.data_root / 'archives' / channel_dir
    
    def get_archive_file(self, channel_name: str, timestamp: str, frequency_hz: int) -> Path:
        """Get path for a specific archive NPZ file.
        
        Args:
            channel_name: Channel name
            timestamp: ISO timestamp (YYYYMMDDTHHMMSZ)
            frequency_hz: Frequency in Hz
        
        Returns: {data_root}/archives/{CHANNEL}/{timestamp}_{freq}_iq.npz
        """
        archive_dir = self.get_archive_dir(channel_name)
        return archive_dir / f"{timestamp}_{frequency_hz}_iq.npz"
    
    # ========================================================================
    # Analytics Paths (Per-channel products)
    # ========================================================================
    
    def get_analytics_dir(self, channel_name: str) -> Path:
        """Get analytics directory for a channel.
        
        Returns: {data_root}/analytics/{CHANNEL}/
        """
        channel_dir = channel_name_to_dir(channel_name)
        return self.data_root / 'analytics' / channel_dir
    
    def get_digital_rf_dir(self, channel_name: str) -> Path:
        """Get Digital RF directory for a channel.
        
        Returns: {data_root}/analytics/{CHANNEL}/digital_rf/
        """
        return self.get_analytics_dir(channel_name) / 'digital_rf'
    
    def get_discrimination_dir(self, channel_name: str) -> Path:
        """Get WWV/WWVH discrimination directory.
        
        Returns: {data_root}/analytics/{CHANNEL}/discrimination/
        """
        return self.get_analytics_dir(channel_name) / 'discrimination'
    
    def get_quality_dir(self, channel_name: str) -> Path:
        """Get quality metrics directory.
        
        Returns: {data_root}/analytics/{CHANNEL}/quality/
        """
        return self.get_analytics_dir(channel_name) / 'quality'
    
    def get_analytics_logs_dir(self, channel_name: str) -> Path:
        """Get analytics logs directory.
        
        Returns: {data_root}/analytics/{CHANNEL}/logs/
        """
        return self.get_analytics_dir(channel_name) / 'logs'
    
    def get_analytics_status_dir(self, channel_name: str) -> Path:
        """Get analytics status directory.
        
        Returns: {data_root}/analytics/{CHANNEL}/status/
        """
        return self.get_analytics_dir(channel_name) / 'status'
    
    # ========================================================================
    # Spectrogram Paths (Web UI)
    # ========================================================================
    
    def get_spectrograms_root(self) -> Path:
        """Get spectrograms root directory.
        
        Returns: {data_root}/spectrograms/
        """
        return self.data_root / 'spectrograms'
    
    def get_spectrograms_date_dir(self, date: str) -> Path:
        """Get spectrograms directory for a specific date.
        
        Args:
            date: Date in YYYYMMDD format
        
        Returns: {data_root}/spectrograms/{YYYYMMDD}/
        """
        return self.get_spectrograms_root() / date
    
    def get_spectrogram_path(self, channel_name: str, date: str, spec_type: str = 'carrier') -> Path:
        """Get path for a specific spectrogram PNG.
        
        Args:
            channel_name: Channel name
            date: Date in YYYYMMDD format
            spec_type: Type ('carrier', 'archive', etc.)
        
        Returns: {data_root}/spectrograms/{YYYYMMDD}/{CHANNEL}_{YYYYMMDD}_{type}_spectrogram.png
        """
        channel_dir = channel_name_to_dir(channel_name)
        filename = f"{channel_dir}_{date}_{spec_type}_spectrogram.png"
        return self.get_spectrograms_date_dir(date) / filename
    
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
        
        Returns: {data_root}/state/core-recorder-status.json
        """
        return self.get_state_dir() / 'core-recorder-status.json'
    
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
    
    # ========================================================================
    # Discovery Methods
    # ========================================================================
    
    def discover_channels(self) -> list[str]:
        """Discover all channels with archive data.
        
        Returns:
            List of channel names (human-readable format)
        """
        archives_dir = self.data_root / 'archives'
        if not archives_dir.exists():
            return []
        
        channels = []
        for channel_dir in archives_dir.iterdir():
            if channel_dir.is_dir():
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
        data_root = config.get('recorder', {}).get('production_data_root', '/var/lib/signal-recorder')
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
