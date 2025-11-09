#!/usr/bin/env python3
"""
Decimation utilities for GRAPE recorder

Provides sample rate reduction with anti-aliasing filters.
Isolated module for easy replacement with optimized implementations.
"""

import numpy as np
from scipy import signal
import logging

logger = logging.getLogger(__name__)


def decimate_for_upload(iq_samples: np.ndarray, input_rate: int = 16000, 
                        output_rate: int = 10) -> np.ndarray:
    """
    Decimate IQ samples for Digital RF upload
    
    Current implementation: scipy.signal.decimate (simple, reliable)
    Future: Can replace with multi-stage cascade for efficiency
    
    Args:
        iq_samples: Complex IQ samples at input_rate
        input_rate: Input sample rate (Hz)
        output_rate: Output sample rate (Hz)
        
    Returns:
        Decimated complex IQ samples at output_rate
        
    Example:
        >>> iq_16k = np.random.randn(16000) + 1j*np.random.randn(16000)
        >>> iq_10 = decimate_for_upload(iq_16k, 16000, 10)
        >>> len(iq_10)
        10
    """
    if input_rate % output_rate != 0:
        raise ValueError(f"Input rate {input_rate} must be integer multiple of output rate {output_rate}")
    
    total_factor = input_rate // output_rate
    
    if total_factor == 1:
        return iq_samples  # No decimation needed
    
    # Three-stage decimation for 16000 Hz → 10 Hz (factor 1600)
    # This balances efficiency and code simplicity
    
    # Stage 1: 16000 → 1600 Hz (factor 10)
    if total_factor >= 10:
        iq_samples = signal.decimate(iq_samples, q=10, ftype='iir', zero_phase=True)
        logger.debug(f"Stage 1: decimated to {input_rate // 10} Hz, {len(iq_samples)} samples")
        total_factor //= 10
    
    # Stage 2: 1600 → 160 Hz (factor 10)
    if total_factor >= 10:
        iq_samples = signal.decimate(iq_samples, q=10, ftype='iir', zero_phase=True)
        logger.debug(f"Stage 2: decimated to {input_rate // 100} Hz, {len(iq_samples)} samples")
        total_factor //= 10
    
    # Stage 3: 160 → 10 Hz (factor 16)
    if total_factor >= 16:
        iq_samples = signal.decimate(iq_samples, q=16, ftype='iir', zero_phase=True)
        logger.debug(f"Stage 3: decimated to {output_rate} Hz, {len(iq_samples)} samples")
        total_factor //= 16
    
    # Handle any remaining factor
    if total_factor > 1:
        iq_samples = signal.decimate(iq_samples, q=total_factor, ftype='iir', zero_phase=True)
        logger.debug(f"Final stage: decimated by {total_factor}, {len(iq_samples)} samples")
    
    return iq_samples


def decimate_for_upload_optimized(iq_samples: np.ndarray, input_rate: int = 16000,
                                   output_rate: int = 10) -> np.ndarray:
    """
    FUTURE: Optimized multi-stage decimation with manual filter design
    
    This function is a placeholder for future optimization if scipy proves too slow.
    Would implement manual Chebyshev/Butterworth cascade for better control.
    
    Args:
        iq_samples: Complex IQ samples at input_rate
        input_rate: Input sample rate (Hz)
        output_rate: Output sample rate (Hz)
        
    Returns:
        Decimated complex IQ samples at output_rate
    """
    # TODO: Implement manual cascade if needed
    # For now, just call the scipy version
    return decimate_for_upload(iq_samples, input_rate, output_rate)


# Module configuration - easy to swap implementations
DECIMATION_FUNCTION = decimate_for_upload  # Change to decimate_for_upload_optimized later


def get_decimator(input_rate: int, output_rate: int):
    """
    Factory function to get appropriate decimator
    
    Returns a configured decimation function for the given rates.
    Makes it easy to select different implementations based on requirements.
    
    Args:
        input_rate: Input sample rate (Hz)
        output_rate: Output sample rate (Hz)
        
    Returns:
        Callable that decimates from input_rate to output_rate
    """
    def decimator(samples: np.ndarray) -> np.ndarray:
        return DECIMATION_FUNCTION(samples, input_rate, output_rate)
    
    return decimator
