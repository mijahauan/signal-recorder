
import os
import sys
import numpy as np
import h5py
from pathlib import Path
from datetime import datetime, timezone
import shutil

def create_synthetic_archive(
    archive_dir: Path,
    channel_name: str,
    frequency_hz: float,
    duration_minutes: int = 5,
    sample_rate: int = 20000
):
    """
    Create a synthetic Phase 1 Digital RF archive.
    Simulates a WWV signal with varying SNR to test uncertainty scaling.
    """
    channel_dir = archive_dir / channel_name
    if channel_dir.exists():
        shutil.rmtree(channel_dir)
    channel_dir.mkdir(parents=True)
    
    # Metadata files would go here (drf_properties.h5), but engine might skip
    # strict validation if we format H5 properly.
    
    # Start time (aligned to minute)
    start_ts = int(datetime.now(timezone.utc).timestamp() // 60) * 60
    
    logger_print(f"Generating {duration_minutes} minutes of synthetic data at {archive_dir}...")
    
    for i in range(duration_minutes):
        minute_start = start_ts + (i * 60)
        
        # Create HDF5 file for this minute
        # Filename format: rf_@{timestamp}_{frac}.h5  (Simplified: just use timestamp)
        # Standard Digital RF uses subdirectories by time, but simplified for this test
        # Let's start with a simple file per minute structure if the reader supports it,
        # or just put it in a subdirectory.
        
        # Digital RF standard: 
        # /archive/channel/2023-10-27T00-00-00/rf_data.h5 (blocks of files)
        # We'll mimic the file structure expected by the simple reader,
        # or rely on the engine reading whatever valid H5 we give it if we point directly.
        
        # For this test, we create a file named by timestamp
        subdir = channel_dir / datetime.fromtimestamp(minute_start, timezone.utc).strftime('%Y-%m-%dT%H-%M-%S')
        subdir.mkdir()
        h5_path = subdir / 'rf_data.h5'
        
        with h5py.File(h5_path, 'w') as f:
            # Generate 60 seconds of complex IQ
            t = np.arange(0, 60, 1/sample_rate)
            n_samples = len(t)
            
            # Synthetic Signal:
            # minute 0: Strong WWV (30dB)
            # minute 1: Weak WWV (10dB)
            # minute 2: Strong WWVH (simulate discriminator check)
            
            sig_amp = 0.0
            noise_amp = 1.0
            
            if i == 0: # High SNR
                sig_amp = 10.0 # ~20dB SNR
                freq_offset = 0.0
            elif i == 1: # Low SNR
                sig_amp = 1.0  # ~0dB SNR
                freq_offset = 0.0
            else: # Random noise (Low Confidence)
                sig_amp = 0.5
                freq_offset = 5.0
                
            # Carrier (DC offset from center freq)
            signal = sig_amp * np.exp(1j * 2 * np.pi * freq_offset * t)
            
            # Add tones (1000 Hz)
            # 1000 Hz tone at 5ms delay
            signal += (sig_amp * 0.5) * np.exp(1j * 2 * np.pi * 1000 * (t - 0.005))
            
            # Noise
            noise = noise_amp * (np.random.randn(n_samples) + 1j * np.random.randn(n_samples))
            
            raw_data = (signal + noise).astype(np.float32) # Standard is complex64 (float32, float32)
            
            # Digital RF writes complex as (N, 2) compound or separate fields usually,
            # but grape engine reader expects simple matching format.
            # Let's write as compound complex for now or separate I/Q if that's what h5py does for complex.
            # h5py handles complex64 natively.
            
            dset = f.create_dataset('rf_data', data=raw_data, compression='gzip')
            
            # Write attributes tailored to DrfReader checks
            dset.attrs['sample_rate'] = sample_rate
            dset.attrs['start_time'] = minute_start
            
    logger_print("Synthetic production archive created.")

def logger_print(msg):
    print(f"[SyntheticGen] {msg}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 generate_synthetic_data.py <output_root>")
        sys.exit(1)
        
    out_dir = Path(sys.argv[1])
    create_synthetic_archive(
        out_dir, 
        'WWV_10MHz', 
        10000000, 
        duration_minutes=3
    )
