#!/usr/bin/env python3
"""
Demonstration of Global Station Lock with Synthetic Data
------------------------------------------------------
This script simulates the "Real World" scenario where:
1. One process (CHU 7.85 MHz) receives a strong, unambiguous signal.
2. Another process (WWV 10 MHz) receives a weak, ambiguous signal.
3. The WWV process uses the CHU anchor to resolve ambiguity via GlobalStationVoter.

Usage:
    ./demo_global_lock.py
"""

import sys
import os
import time
import shutil
import logging
import numpy as np
from pathlib import Path

# Fix path to include src/grape_recorder
sys.path.append(str(Path(__file__).parent.parent / 'src'))

# Import system components
from grape_recorder.grape.global_station_voter import GlobalStationVoter, StationAnchor, AnchorQuality
from grape_recorder.grape.phase2_temporal_engine import Phase2TemporalEngine
from grape_recorder.grape.wwv_constants import SAMPLE_RATE_FULL

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger("DEMO")

def generate_synthetic_iq(sample_rate, duration_sec, freq_offset_hz, snr_db, station="WWV"):
    """
    Generate synthetic IQ samples with a specific tone.
    """
    t = np.arange(int(sample_rate * duration_sec)) / sample_rate
    
    # Signal
    # WWV/CHU uses 1000 Hz for timing (simplified)
    signal = np.exp(1j * 2 * np.pi * freq_offset_hz * t)
    
    # Noise
    noise_power = 10 ** (-snr_db / 10)
    noise = (np.random.normal(scale=np.sqrt(noise_power/2), size=len(t)) + 
             1j * np.random.normal(scale=np.sqrt(noise_power/2), size=len(t)))
             
    return signal + noise

def run_chu_simulation(ipc_dir, minute_rtp):
    """
    Simulate the CHU process finding a strong signal.
    """
    print("\n" + "="*60)
    print(f"📡  PROCESS 1: CHU 7.85 MHz (Simulated)")
    print("="*60)
    
    # Initialize Voter
    voter = GlobalStationVoter(channels=['CHU 7.85 MHz'], use_ipc=True)
    voter.backend.root_dir = ipc_dir # Override for demo isolation
    
    # Simulate a detection
    print(f"[CHU] detecting signal at RTP {minute_rtp}...")
    time.sleep(0.5) # Simulate processing time
    
    # Report strong CHU detection
    # In a real run, this comes from ToneDetector
    voter.report_detection(
        channel='CHU 7.85 MHz',
        rtp_timestamp=minute_rtp, # Perfect alignment
        station='CHU',
        snr_db=18.5, # Strong!
        toa_offset_samples=0,
        confidence=0.98
    )
    print(f"[CHU] ✅ Strong Signal Found: SNR 18.5 dB, Conf=0.98")
    print(f"[CHU] 📢 Publishing Anchor to Shared Memory...")

def run_wwv_ambiguous_simulation(ipc_dir, minute_rtp):
    """
    Simulate the WWV 10 MHz process finding a weak/ambiguous signal
    and using the CHU anchor to resolve it.
    """
    print("\n" + "="*60)
    print(f"📡  PROCESS 2: WWV 10 MHz (Simulated)")
    print("="*60)
    
    # Initialize Voter
    voter = GlobalStationVoter(channels=['WWV 10 MHz'], use_ipc=True)
    voter.backend.root_dir = ipc_dir
    
    # Step 1: Check what we see locally
    print(f"[WWV] detecting signal at RTP {minute_rtp}...")
    print(f"[WWV] ⚠️  Signal is WEAK/AMBIGUOUS (SNR 3.2 dB)")
    
    # Step 2: Ask the ecosystem for help
    print(f"[WWV] 🆘 Requesting Global Lock assistance...")
    
    # This roughly mimics Phase2TemporalEngine logic
    # First, sync with backend
    voter._sync_from_backend(voter._minute_rtp_key(minute_rtp))
    
    # Ask for best anchor
    anchor = voter.get_best_time_snap_anchor(minute_rtp)
    
    if anchor:
        print(f"[WWV] 🔓 GLOBAL LOCK FOUND!")
        print(f"       Constraint Source: {anchor['station']} ({anchor['frequency_mhz']} MHz)")
        print(f"       Anchor Quality:    {anchor['quality']} (SNR {anchor['snr_db']:.1f} dB)")
        print(f"       Timing Reference:  RTP {anchor['rtp_timestamp']}")
        
        # Calculate search window
        window = voter.get_search_window('WWV 10 MHz', minute_rtp, anchor['station'])
        if window:
            print(f"[WWV] 🎯 Defined Narrow Search Window:")
            print(f"       Center: {window['center_rtp']}")
            print(f"       Width:  +/- {window['window_samples']} samples (~{window['window_samples']/20:.1f} ms)")
            print(f"[WWV] ✅ Rescued! Proceeding with Guided Analysis.")
        else:
            print(f"[WWV] ❌ Failed to calculate search window.")
    else:
        print(f"[WWV] ❌ No lock found. Fallback to wide search.")

def main():
    # Setup IPC environment
    test_dir = Path("/tmp/grape_demo")
    if test_dir.exists():
        shutil.rmtree(test_dir)
    test_dir.mkdir(parents=True)
    ipc_dir = test_dir / "shm"
    ipc_dir.mkdir()
    
    minute_rtp = 1000000 # Arbitrary minute boundary
    
    # Run the demo steps
    try:
        run_chu_simulation(ipc_dir, minute_rtp)
        time.sleep(1) # Gap between processes
        run_wwv_ambiguous_simulation(ipc_dir, minute_rtp)
        
    finally:
        # Cleanup
        if test_dir.exists():
            shutil.rmtree(test_dir)
            
if __name__ == "__main__":
    main()
