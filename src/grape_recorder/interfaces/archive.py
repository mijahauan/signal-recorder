"""
Archive Writer Interface (Function 2)

Defines the contract for full-bandwidth compressed storage.
Stores 16 kHz IQ data with quality metadata in compressed format.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Tuple, List
import numpy as np
from .data_models import QualityInfo, TimeSnapReference, Discontinuity


class ArchiveWriter(ABC):
    """
    Interface for Function 2: Full-Bandwidth Compressed Storage
    
    Stores raw 16 kHz IQ samples with quality metadata in compressed
    format (NPZ, HDF5, etc.). Implementation details hidden from consumers.
    
    Key requirements:
    - Lossless compression
    - Quality metadata embedded
    - Time_snap reference preserved
    - Discontinuities logged
    - Minute-boundary file organization
    
    Design principle:
        Consumer (Function 1) doesn't care about file format, compression
        algorithm, or directory structure. Just needs to write samples
        with metadata.
    """
    
    @abstractmethod
    def write_samples(
        self,
        timestamp: float,
        samples: np.ndarray,
        quality: QualityInfo,
        time_snap: Optional[TimeSnapReference] = None
    ) -> Optional[Path]:
        """
        Write samples to compressed archive.
        
        Accumulates samples and writes when minute boundary crossed.
        All quality metadata and time_snap reference are embedded.
        
        Args:
            timestamp: UTC timestamp of first sample (time_snap corrected)
            samples: Complex IQ samples (np.ndarray, complex64/128)
            quality: Quality metadata for this batch
            time_snap: Current time_snap reference (optional)
            
        Returns:
            Path to completed file if minute boundary was crossed,
            None if still accumulating samples for current minute
            
        Thread safety:
            Not thread-safe. Single writer per channel.
            
        Example:
            # Write samples continuously
            completed_file = archive.write_samples(
                timestamp=1699876543.0,
                samples=iq_data,
                quality=quality_info,
                time_snap=time_snap_ref
            )
            
            if completed_file:
                print(f"Completed: {completed_file}")
                # Queue for processing/backup
        """
        pass
    
    @abstractmethod
    def add_discontinuity(self, discontinuity: Discontinuity) -> None:
        """
        Add discontinuity record to current minute's metadata.
        
        Called when Function 1 detects a gap, time_snap correction,
        or other timing irregularity.
        
        Args:
            discontinuity: Discontinuity record with full context
            
        Usage:
            When gap detected:
                archive.add_discontinuity(Discontinuity(
                    timestamp=utc_time,
                    discontinuity_type=DiscontinuityType.GAP,
                    magnitude_samples=320,
                    magnitude_ms=20.0,
                    explanation="Missed 2 RTP packets"
                ))
        """
        pass
    
    @abstractmethod
    def flush(self) -> Optional[Path]:
        """
        Flush current buffer and finalize file.
        
        Forces write of incomplete minute (e.g., at shutdown).
        Returns path to written file, or None if buffer was empty.
        
        Returns:
            Path to flushed file, or None if nothing to flush
            
        Usage:
            Called at shutdown to ensure no data loss:
                final_file = archive.flush()
                if final_file:
                    print(f"Flushed final data to: {final_file}")
        """
        pass
    
    @abstractmethod
    def get_output_directory(self) -> Path:
        """
        Get base output directory for archived files.
        
        Returns:
            Path to archive directory
            
        Usage:
            Useful for backup scripts, disk space monitoring, etc.
        """
        pass
    
    @abstractmethod
    def get_files_written(self) -> int:
        """
        Get count of files written so far.
        
        Returns:
            Number of completed minute files
            
        Usage:
            Status monitoring, progress tracking
        """
        pass
    
    @abstractmethod
    def get_total_samples_written(self) -> int:
        """
        Get total samples written to archive.
        
        Returns:
            Total sample count across all files
            
        Usage:
            Verify data completeness, storage estimates
        """
        pass
    
    @abstractmethod
    def get_current_file_path(self) -> Optional[Path]:
        """
        Get path where current minute will be written.
        
        Returns:
            Path to in-progress file (not yet written), or None if buffer empty
            
        Usage:
            Status display, debugging
        """
        pass
    
    @abstractmethod
    def verify_file_integrity(self, file_path: Path) -> bool:
        """
        Verify integrity of an archived file.
        
        Checks that file can be opened, samples can be read,
        and metadata is valid.
        
        Args:
            file_path: Path to archived file
            
        Returns:
            True if file is valid and readable
            
        Usage:
            Post-write verification, integrity checks
            
        Example:
            completed = archive.write_samples(...)
            if completed:
                if not archive.verify_file_integrity(completed):
                    logger.error(f"Corrupt file: {completed}")
        """
        pass


class ArchiveReader(ABC):
    """
    Interface for reading archived data.
    
    Separate from writer to allow different implementations
    (e.g., streaming reader, batch reader, index-based reader).
    """
    
    @abstractmethod
    def read_minute(self, file_path: Path) -> Tuple[np.ndarray, dict]:
        """
        Read a single minute file.
        
        Args:
            file_path: Path to archived minute file
            
        Returns:
            Tuple of (samples, metadata) where:
            - samples: np.ndarray of complex IQ
            - metadata: dict with quality info, time_snap, discontinuities
            
        Raises:
            FileNotFoundError: File doesn't exist
            ValueError: File corrupt or invalid format
        """
        pass
    
    @abstractmethod
    def read_time_range(
        self,
        start_time: float,
        end_time: float,
        channel_name: str
    ) -> Tuple[np.ndarray, List[dict]]:
        """
        Read samples across multiple minutes.
        
        Args:
            start_time: UTC start timestamp
            end_time: UTC end timestamp
            channel_name: Channel identifier
            
        Returns:
            Tuple of (samples, metadata_list) where:
            - samples: Concatenated IQ samples
            - metadata_list: List of metadata dicts (one per minute)
            
        Usage:
            # Read 10 minutes of data
            samples, metadata = reader.read_time_range(
                start_time=1699876800.0,
                end_time=1699877400.0,
                channel_name="WWV 5.0 MHz"
            )
        """
        pass
    
    @abstractmethod
    def get_available_minutes(
        self,
        channel_name: str,
        date_str: str
    ) -> List[Path]:
        """
        List available minute files for a channel/date.
        
        Args:
            channel_name: Channel identifier
            date_str: Date string (YYYYMMDD format)
            
        Returns:
            List of available minute file paths, sorted by time
            
        Usage:
            # Check what data is available
            files = reader.get_available_minutes(
                channel_name="WWV 5.0 MHz",
                date_str="20241108"
            )
            print(f"Found {len(files)} minutes")
        """
        pass
