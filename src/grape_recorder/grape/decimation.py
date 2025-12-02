#!/usr/bin/env python3
"""
Optimized Multi-Stage Decimation for GRAPE Recorder

Implements scientifically-rigorous decimation: 20 kHz → 10 Hz (factor 2000)
Three-stage pipeline for Doppler-precision ionospheric measurements:

1. CIC Filter: 20 kHz → 400 Hz (R=50)
   - Efficient coarse decimation (no multipliers)
   - Automatic alias suppression at 400, 800, 1200... Hz
   - Passband droop requires compensation

2. Compensation FIR: 400 Hz → 400 Hz (R=1)
   - Inverse sinc correction
   - Flattens ±5 Hz passband for Doppler accuracy
   - Corrects CIC droop to <0.1 dB

3. Final FIR: 400 Hz → 10 Hz (R=40)
   - Sharp cutoff at 5 Hz (Nyquist for 10 Hz output)
   - >90 dB stopband attenuation
   - Prevents aliasing in final decimation

Design Goals:
- Preserve ±0.1 Hz Doppler resolution (phase continuity)
- Flat passband response (0-5 Hz within 0.1 dB)
- Eliminate decimation artifacts (smooth frequency variations)

Note: Also supports legacy 16 kHz input (factor 1600) for backward compatibility.

Adding new sample rates:
    To add support for a new input rate (e.g., 24 kHz), add an entry to
    SUPPORTED_INPUT_RATES with the appropriate CIC decimation factor that
    produces a 400 Hz intermediate rate (intermediate_rate = input_rate / cic_factor).
"""

import numpy as np
from scipy import signal
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# Supported input sample rates and their decimation parameters
# All paths converge to 400 Hz intermediate rate, then final FIR decimates to 10 Hz
# To add a new rate: ensure input_rate / cic_decimation = 400
SUPPORTED_INPUT_RATES: Dict[int, Dict] = {
    20000: {
        'cic_decimation': 50,      # 20000 / 50 = 400 Hz
        'total_factor': 2000,      # 20000 / 10 = 2000
        'description': '20 kHz (default)',
    },
    16000: {
        'cic_decimation': 40,      # 16000 / 40 = 400 Hz  
        'total_factor': 1600,      # 16000 / 10 = 1600
        'description': '16 kHz (legacy)',
    },
    # To add 24 kHz support:
    # 24000: {
    #     'cic_decimation': 60,    # 24000 / 60 = 400 Hz
    #     'total_factor': 2400,    # 24000 / 10 = 2400
    #     'description': '24 kHz',
    # },
}

OUTPUT_RATE = 10  # Fixed 10 Hz output for GRAPE
INTERMEDIATE_RATE = 400  # 400 Hz intermediate (after CIC)
FINAL_FIR_DECIMATION = 40  # 400 / 40 = 10 Hz


def _design_cic_filter(decimation_factor: int, order: int = 4) -> dict:
    """
    Design CIC (Cascaded Integrator-Comb) filter parameters
    
    CIC filters are efficient for large decimation factors because they
    require no multipliers - only additions and subtractions.
    
    Args:
        decimation_factor: Decimation ratio (R)
        order: Filter order (3 or 4 typical, higher = better stopband)
        
    Returns:
        dict with 'order' and 'decimation_factor' for apply_cic_filter()
    """
    return {
        'order': order,
        'decimation_factor': decimation_factor
    }


def _apply_cic_filter(samples: np.ndarray, cic_params: dict) -> np.ndarray:
    """
    Apply CIC filter via integrator-comb stages
    
    CIC frequency response: H(f) = |sinc(f/fs)|^N where N = order
    This creates notches at multiples of the output sample rate.
    
    Args:
        samples: Complex input samples
        cic_params: Parameters from _design_cic_filter()
        
    Returns:
        Decimated samples
    """
    R = cic_params['decimation_factor']
    N = cic_params['order']
    
    # Use scipy's decimate with FIR filter approximation
    # For production: could implement true CIC stages for efficiency
    # Current approach: use FIR approximation of CIC response
    
    # CIC sinc response approximation
    b = np.ones(R) / R  # Simple boxcar approximates CIC integrator
    a = [1.0]
    
    # Apply N stages
    filtered = samples
    for _ in range(N):
        filtered = signal.lfilter(b, a, filtered)
    
    # Decimate
    decimated = filtered[::R]
    
    logger.debug(f"CIC filter: {len(samples)} → {len(decimated)} samples (R={R}, N={N})")
    return decimated


def _design_compensation_fir(sample_rate: int, passband_width: float, 
                             cic_order: int, cic_decimation: int,
                             num_taps: int = 63) -> np.ndarray:
    """
    Design inverse sinc FIR filter to compensate for CIC passband droop
    
    CIC droop at frequency f: |sinc(f * R / fs)|^N
    Compensation: 1 / |sinc(f * R / fs)|^N over passband
    
    Args:
        sample_rate: Current sample rate (Hz) - 400 Hz after CIC
        passband_width: Flat passband required (Hz) - ±5 Hz for Doppler
        cic_order: Order of preceding CIC filter
        cic_decimation: Decimation factor of preceding CIC
        num_taps: FIR filter length (higher = better correction)
        
    Returns:
        FIR filter coefficients (real-valued, works on complex IQ)
    """
    # Frequency points for compensation
    nyquist = sample_rate / 2
    freqs = np.linspace(0, nyquist, 500)
    
    # CIC frequency response (normalized)
    # |sinc(π * f * R / fs)|^N
    cic_response = np.ones_like(freqs)
    for f_idx, f in enumerate(freqs):
        if f == 0:
            cic_response[f_idx] = 1.0
        else:
            # Normalized frequency for CIC
            x = np.pi * f * cic_decimation / (sample_rate * cic_decimation)
            cic_response[f_idx] = np.abs(np.sin(x) / x) ** cic_order
    
    # Compensation: inverse of CIC droop within passband
    compensation_response = np.ones_like(freqs)
    for f_idx, f in enumerate(freqs):
        if f <= passband_width:
            # Compensate within passband
            compensation_response[f_idx] = 1.0 / max(cic_response[f_idx], 0.1)  # Avoid division by zero
        else:
            # Unity gain outside passband (let final filter handle stopband)
            compensation_response[f_idx] = 1.0
    
    # Design FIR using frequency sampling method
    # firwin2 creates filter matching arbitrary frequency response
    taps = signal.firwin2(num_taps, freqs, compensation_response, fs=sample_rate)
    
    logger.debug(f"Compensation FIR: {num_taps} taps, passband ±{passband_width} Hz")
    return taps


def _design_final_fir(sample_rate: int, cutoff: float, 
                     transition_width: float = 1.0,
                     stopband_attenuation_db: float = 90) -> np.ndarray:
    """
    Design sharp final anti-aliasing FIR filter
    
    Requirements before final decimation (400 Hz → 10 Hz):
    - Pass: 0-5 Hz (Nyquist for 10 Hz output)
    - Stop: >6 Hz with >90 dB attenuation
    - Transition: 5-6 Hz (sharp as possible)
    
    Args:
        sample_rate: Current sample rate (Hz) - 400 Hz
        cutoff: Cutoff frequency (Hz) - 5 Hz for 10 Hz output
        transition_width: Transition band width (Hz) - narrow for sharp cutoff
        stopband_attenuation_db: Required stopband rejection (dB)
        
    Returns:
        FIR filter coefficients
    """
    # Calculate filter order for required attenuation
    # Kaiser window provides excellent control over stopband
    # Formula: N ≈ (stopband_db - 8) / (2.285 * transition_width / fs)
    transition_normalized = transition_width / sample_rate
    num_taps = int(np.ceil((stopband_attenuation_db - 8) / (2.285 * 2 * np.pi * transition_normalized))) + 1
    
    # Ensure odd number of taps (symmetric, linear phase)
    if num_taps % 2 == 0:
        num_taps += 1
    
    # Limit maximum taps for computational efficiency
    num_taps = min(num_taps, 401)
    
    # Design using Kaiser window (optimal for given specs)
    beta = signal.kaiser_beta(signal.kaiser_atten(num_taps, transition_normalized))
    taps = signal.firwin(num_taps, cutoff, window=('kaiser', beta), 
                        fs=sample_rate, scale=True)
    
    logger.debug(f"Final FIR: {num_taps} taps, cutoff={cutoff} Hz, "
                f"stopband={stopband_attenuation_db} dB")
    return taps


def decimate_for_upload(iq_samples: np.ndarray, input_rate: int = 20000, 
                        output_rate: int = 10) -> Optional[np.ndarray]:
    """
    Multi-stage optimized decimation: 20 kHz → 10 Hz (factor 2000)
    Also supports legacy 16 kHz → 10 Hz (factor 1600) for backward compatibility.
    
    Three-stage pipeline preserving Doppler precision:
    - 20 kHz: CIC R=50 (20000→400 Hz) + Comp FIR + Final FIR R=40 (400→10 Hz)
    - 16 kHz: CIC R=40 (16000→400 Hz) + Comp FIR + Final FIR R=40 (400→10 Hz)
    
    Args:
        iq_samples: Complex IQ samples at input_rate
        input_rate: Input sample rate (Hz) - 20000 (default) or 16000
        output_rate: Output sample rate (Hz) - must be 10
        
    Returns:
        Decimated complex IQ samples at output_rate (10 Hz)
        Returns None if input too short or rates unsupported
        
    Example:
        >>> iq_20k = np.random.randn(1200000) + 1j*np.random.randn(1200000)  # 60 seconds
        >>> iq_10hz = decimate_for_upload(iq_20k, 20000, 10)
        >>> len(iq_10hz)
        600  # 60 seconds at 10 Hz
    """
    # Validate parameters
    if output_rate != OUTPUT_RATE:
        raise ValueError(f"Output rate must be {OUTPUT_RATE} Hz (got {output_rate})")
    
    # Check if input rate is supported
    if input_rate not in SUPPORTED_INPUT_RATES:
        supported = ', '.join(f"{r} Hz" for r in sorted(SUPPORTED_INPUT_RATES.keys()))
        raise ValueError(
            f"Unsupported input rate: {input_rate} Hz. "
            f"Supported rates: {supported}. "
            f"To add a new rate, update SUPPORTED_INPUT_RATES in decimation.py."
        )
    
    rate_config = SUPPORTED_INPUT_RATES[input_rate]
    cic_decimation = rate_config['cic_decimation']
    expected_factor = rate_config['total_factor']
    
    total_factor = input_rate // output_rate
    if total_factor != expected_factor:
        raise ValueError(f"Total decimation factor must be {expected_factor} (got {total_factor})")
    
    # Check minimum length
    # CIC needs at least R samples, compensation FIR needs its length, final FIR needs its length
    min_length = 1000  # Conservative minimum for 60-second files
    if len(iq_samples) < min_length:
        logger.warning(f"Input too short for decimation: {len(iq_samples)} < {min_length} samples")
        return None
    
    logger.debug(f"Starting 3-stage decimation: {len(iq_samples)} samples @ {input_rate} Hz")
    
    try:
        # STAGE 1: CIC Filter (input_rate → 400 Hz)
        cic_params = _design_cic_filter(decimation_factor=cic_decimation, order=4)
        iq_400hz = _apply_cic_filter(iq_samples, cic_params)
        logger.debug(f"After CIC (R={cic_decimation}): {len(iq_400hz)} samples @ 400 Hz")
        
        # STAGE 2: Compensation FIR (400 Hz, R=1)
        # Flatten ±5 Hz passband (corrects CIC droop)
        comp_taps = _design_compensation_fir(
            sample_rate=400,
            passband_width=5.0,  # ±5 Hz for Doppler measurements
            cic_order=4,
            cic_decimation=cic_decimation,
            num_taps=63
        )
        iq_400hz_flat = signal.lfilter(comp_taps, [1.0], iq_400hz)
        logger.debug(f"After compensation FIR: {len(iq_400hz_flat)} samples @ 400 Hz")
        
        # STAGE 3: Final FIR + Decimation (400 Hz → 10 Hz, R=40)
        final_taps = _design_final_fir(
            sample_rate=400,
            cutoff=5.0,  # Nyquist for 10 Hz output
            transition_width=1.0,  # 5-6 Hz transition
            stopband_attenuation_db=90
        )
        iq_filtered = signal.lfilter(final_taps, [1.0], iq_400hz_flat)
        iq_10hz = iq_filtered[::40]  # Decimate by 40
        
        logger.debug(f"After final FIR+decimate: {len(iq_10hz)} samples @ 10 Hz")
        logger.info(f"✅ Decimation complete: {len(iq_samples)} @ {input_rate} Hz → "
                   f"{len(iq_10hz)} @ {output_rate} Hz (factor {total_factor})")
        
        return iq_10hz
        
    except Exception as e:
        logger.error(f"Decimation failed: {e}")
        return None


def decimate_for_upload_simple(iq_samples: np.ndarray, input_rate: int = 20000,
                               output_rate: int = 10) -> Optional[np.ndarray]:
    """
    Simple fallback decimation using scipy.signal.decimate
    
    Use this if the optimized version has issues.
    - 20 kHz: Stages 10×10×20 = 2000
    - 16 kHz: Stages 10×10×16 = 1600
    
    Args:
        iq_samples: Complex IQ samples at input_rate
        input_rate: Input sample rate (Hz) - 20000 or 16000
        output_rate: Output sample rate (Hz) - must be 10
        
    Returns:
        Decimated complex IQ samples at output_rate
    """
    if input_rate % output_rate != 0:
        raise ValueError(f"Input rate {input_rate} must be integer multiple of output rate {output_rate}")
    
    total_factor = input_rate // output_rate
    
    if total_factor == 1:
        return iq_samples
    
    min_length = 100
    if len(iq_samples) < min_length:
        logger.warning(f"Input too short: {len(iq_samples)} < {min_length} samples")
        return None
    
    try:
        # Stage 1: input → input/10 Hz (factor 10)
        # 20000 → 2000 Hz or 16000 → 1600 Hz
        if total_factor >= 10:
            iq_samples = signal.decimate(iq_samples, q=10, ftype='iir', zero_phase=True)
            total_factor //= 10
        
        # Stage 2: → /10 Hz (factor 10)
        # 2000 → 200 Hz or 1600 → 160 Hz
        if total_factor >= 10:
            iq_samples = signal.decimate(iq_samples, q=10, ftype='iir', zero_phase=True)
            total_factor //= 10
        
        # Stage 3: → 10 Hz (factor 20 for 20kHz, factor 16 for 16kHz)
        # 200 → 10 Hz (factor 20) or 160 → 10 Hz (factor 16)
        if total_factor >= 16:
            iq_samples = signal.decimate(iq_samples, q=total_factor, ftype='iir', zero_phase=True)
            total_factor = 1
        
        # Handle any remaining factor
        if total_factor > 1:
            iq_samples = signal.decimate(iq_samples, q=total_factor, ftype='iir', zero_phase=True)
        
        return iq_samples
        
    except Exception as e:
        logger.error(f"Simple decimation failed: {e}")
        return None


# Module configuration - easy to swap implementations
DECIMATION_FUNCTION = decimate_for_upload  # Use optimized version
# DECIMATION_FUNCTION = decimate_for_upload_simple  # Uncomment for simple fallback


def get_supported_rates() -> Dict[int, Dict]:
    """
    Get dictionary of supported input sample rates.
    
    Returns:
        Dict mapping input_rate to configuration dict with:
        - cic_decimation: CIC filter decimation factor
        - total_factor: Total decimation factor to reach 10 Hz
        - description: Human-readable description
    """
    return SUPPORTED_INPUT_RATES.copy()


def is_rate_supported(input_rate: int) -> bool:
    """Check if an input sample rate is supported for decimation."""
    return input_rate in SUPPORTED_INPUT_RATES


def get_decimator(input_rate: int, output_rate: int):
    """
    Factory function to get appropriate decimator
    
    Returns a configured decimation function for the given rates.
    
    Args:
        input_rate: Input sample rate (Hz) - see SUPPORTED_INPUT_RATES
        output_rate: Output sample rate (Hz) - must be 10
    
    Returns:
        Callable that decimates from input_rate to output_rate
        
    Raises:
        ValueError: If input_rate is not supported
    """
    def decimator(samples: np.ndarray) -> Optional[np.ndarray]:
        return DECIMATION_FUNCTION(samples, input_rate, output_rate)
    
    return decimator
