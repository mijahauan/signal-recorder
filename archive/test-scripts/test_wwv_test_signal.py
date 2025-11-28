#!/usr/bin/env python3
"""
Test WWV Test Signal Generator and Detector

Validates that we can:
1. Generate the test signal
2. Detect it in clean conditions
3. Detect it in noisy conditions
4. Correctly identify minute 8 (WWV) vs minute 44 (WWVH)
"""

import sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt

# Add src to path
src_path = Path(__file__).parent / 'src' / 'signal_recorder'
sys.path.insert(0, str(src_path))

import wwv_test_signal

def test_signal_generation():
    """Test that we can generate all signal components"""
    print("=" * 70)
    print("TEST 1: Signal Generation")
    print("=" * 70)
    
    sample_rate = 16000
    gen = wwv_test_signal.WWVTestSignalGenerator(sample_rate)
    
    # Test individual components
    print("\n1. White noise (2s)...")
    noise = gen.generate_white_noise(2.0, seed=42)
    print(f"   ✅ Generated {len(noise)} samples ({len(noise)/sample_rate:.1f}s)")
    print(f"   Mean: {np.mean(noise):.6f}, Std: {np.std(noise):.6f}")
    
    print("\n2. Multi-tone sequence (10s)...")
    multitone = gen.generate_multitone()
    print(f"   ✅ Generated {len(multitone)} samples ({len(multitone)/sample_rate:.1f}s)")
    # Check frequency content
    fft = np.fft.fft(multitone[:sample_rate])  # First second
    freqs = np.fft.fftfreq(sample_rate, 1/sample_rate)
    peaks = freqs[np.abs(fft) > 0.1 * np.max(np.abs(fft))]
    print(f"   Detected frequencies: {sorted([int(abs(f)) for f in peaks[:10]])[:5]} Hz")
    
    print("\n3. Chirp sequence...")
    chirps = gen.generate_chirp_sequence()
    print(f"   ✅ Generated {len(chirps)} samples ({len(chirps)/sample_rate:.1f}s)")
    
    print("\n4. Burst sequence (2s)...")
    bursts = gen.generate_burst_sequence()
    print(f"   ✅ Generated {len(bursts)} samples ({len(bursts)/sample_rate:.1f}s)")
    
    print("\n5. Full test signal...")
    full_signal = gen.generate_full_signal(include_voice=False)
    print(f"   ✅ Generated {len(full_signal)} samples ({len(full_signal)/sample_rate:.1f}s)")
    
    # Plot time domain
    fig, axes = plt.subplots(3, 1, figsize=(12, 8))
    
    # Full signal
    t = np.arange(len(full_signal)) / sample_rate
    axes[0].plot(t, full_signal)
    axes[0].set_title('Complete Test Signal')
    axes[0].set_xlabel('Time (s)')
    axes[0].set_ylabel('Amplitude')
    axes[0].grid(True)
    
    # Multi-tone detail
    t_mt = np.arange(len(multitone)) / sample_rate
    axes[1].plot(t_mt, multitone)
    axes[1].set_title('Multi-tone with 3dB Attenuation Steps (10s)')
    axes[1].set_xlabel('Time (s)')
    axes[1].set_ylabel('Amplitude')
    axes[1].grid(True)
    
    # Chirp detail
    t_chirp = np.arange(len(chirps)) / sample_rate
    axes[2].plot(t_chirp, chirps)
    axes[2].set_title('Chirp Sequence (~8s)')
    axes[2].set_xlabel('Time (s)')
    axes[2].set_ylabel('Amplitude')
    axes[2].grid(True)
    
    plt.tight_layout()
    plt.savefig('/tmp/test_signal_time_domain.png', dpi=100)
    print(f"\n   📊 Plot saved: /tmp/test_signal_time_domain.png")
    
    print("\n" + "=" * 70)

def test_perfect_detection():
    """Test detection on clean generated signal"""
    print("\n" + "=" * 70)
    print("TEST 2: Perfect Detection (No Noise)")
    print("=" * 70)
    
    sample_rate = 16000
    gen = wwv_test_signal.WWVTestSignalGenerator(sample_rate)
    detector = wwv_test_signal.WWVTestSignalDetector(sample_rate)
    
    # Generate test signal
    test_signal = gen.generate_full_signal(include_voice=False)
    
    # Pad to full minute (16000 * 60 = 960000 samples)
    full_minute = np.zeros(960000)
    full_minute[:len(test_signal)] = test_signal
    
    # Convert to complex IQ (just use real signal for both I and Q)
    iq_samples = full_minute + 1j * np.zeros(len(full_minute))
    
    # Test minute 8 (WWV)
    print("\n1. Minute 8 (WWV):")
    result_wwv = detector.detect(iq_samples, 8, sample_rate)
    print(f"   Detected: {result_wwv.detected}")
    print(f"   Station: {result_wwv.station}")
    print(f"   Confidence: {result_wwv.confidence:.3f}")
    print(f"   Multi-tone score: {result_wwv.multitone_score:.3f}")
    print(f"   Chirp score: {result_wwv.chirp_score:.3f}")
    print(f"   SNR: {result_wwv.snr_db:.1f} dB" if result_wwv.snr_db else "   SNR: N/A")
    
    if result_wwv.detected and result_wwv.station == 'WWV':
        print("   ✅ PASS: Correctly identified WWV")
    else:
        print("   ❌ FAIL: Did not detect WWV")
    
    # Test minute 44 (WWVH)
    print("\n2. Minute 44 (WWVH):")
    result_wwvh = detector.detect(iq_samples, 44, sample_rate)
    print(f"   Detected: {result_wwvh.detected}")
    print(f"   Station: {result_wwvh.station}")
    print(f"   Confidence: {result_wwvh.confidence:.3f}")
    print(f"   Multi-tone score: {result_wwvh.multitone_score:.3f}")
    print(f"   Chirp score: {result_wwvh.chirp_score:.3f}")
    
    if result_wwvh.detected and result_wwvh.station == 'WWVH':
        print("   ✅ PASS: Correctly identified WWVH")
    else:
        print("   ❌ FAIL: Did not detect WWVH")
    
    # Test wrong minute (should not detect)
    print("\n3. Minute 30 (should not detect):")
    result_wrong = detector.detect(iq_samples, 30, sample_rate)
    print(f"   Detected: {result_wrong.detected}")
    print(f"   Confidence: {result_wrong.confidence:.3f}")
    
    if not result_wrong.detected:
        print("   ✅ PASS: Correctly ignored wrong minute")
    else:
        print("   ❌ FAIL: False positive on wrong minute")
    
    print("\n" + "=" * 70)

def test_noisy_detection():
    """Test detection with added noise"""
    print("\n" + "=" * 70)
    print("TEST 3: Noisy Detection")
    print("=" * 70)
    
    sample_rate = 16000
    gen = wwv_test_signal.WWVTestSignalGenerator(sample_rate)
    detector = wwv_test_signal.WWVTestSignalDetector(sample_rate)
    
    # Generate test signal
    test_signal = gen.generate_full_signal(include_voice=False)
    
    # Test at different SNR levels
    snr_levels = [20, 10, 5, 0, -5]  # dB
    
    print("\nDetection at different SNR levels (Minute 8 - WWV):")
    print("   SNR (dB) | Detected | Confidence | Multi-tone | Chirp")
    print("   " + "-" * 60)
    
    for target_snr in snr_levels:
        # Add noise to achieve target SNR
        signal_power = np.mean(test_signal**2)
        noise_power = signal_power / (10**(target_snr/10))
        noise = np.sqrt(noise_power) * np.random.randn(len(test_signal))
        noisy_signal = test_signal + noise
        
        # Pad to full minute
        full_minute = np.zeros(960000)
        full_minute[:len(noisy_signal)] = noisy_signal
        
        # Convert to IQ
        iq_samples = full_minute + 1j * np.zeros(len(full_minute))
        
        # Detect
        result = detector.detect(iq_samples, 8, sample_rate)
        
        status = "✅" if result.detected else "❌"
        print(f"   {target_snr:5.0f}    | {status:8} | {result.confidence:10.3f} | "
              f"{result.multitone_score:10.3f} | {result.chirp_score:6.3f}")
    
    print("\n   Note: Detection should work down to ~0 dB SNR")
    print("   Below that, false negatives are expected")
    
    print("\n" + "=" * 70)

def test_timing_discrimination():
    """Test that we correctly discriminate based on minute"""
    print("\n" + "=" * 70)
    print("TEST 4: Timing-Based Discrimination")
    print("=" * 70)
    
    sample_rate = 16000
    detector = wwv_test_signal.WWVTestSignalDetector(sample_rate)
    
    # Generate some dummy signal
    dummy_iq = np.random.randn(960000) + 1j * np.random.randn(960000)
    
    print("\nMinute-by-minute scan:")
    print("   Minute | Should Detect | Actually Detected | Station")
    print("   " + "-" * 60)
    
    test_minutes = [0, 7, 8, 9, 30, 43, 44, 45, 59]
    
    for minute in test_minutes:
        result = detector.detect(dummy_iq, minute, sample_rate)
        should_detect = minute in [8, 44]
        expected_station = 'WWV' if minute == 8 else 'WWVH' if minute == 44 else None
        
        status = "✅" if (result.detected == should_detect) else "❌"
        print(f"   {minute:4}   | {str(should_detect):13} | {str(result.detected):17} | "
              f"{result.station or 'None':5}  {status}")
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    print("\n🧪 WWV Test Signal - Generator & Detector Test Suite\n")
    
    try:
        test_signal_generation()
        test_perfect_detection()
        test_noisy_detection()
        test_timing_discrimination()
        
        print("\n" + "=" * 70)
        print("✅ All tests completed!")
        print("=" * 70)
        print("\nNext steps:")
        print("  1. Review plots: /tmp/test_signal_time_domain.png")
        print("  2. Integrate into WWVHDiscriminator.analyze_minute_with_440hz()")
        print("  3. Test with real WWV/WWVH recordings at minute 8 and 44")
        print()
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
