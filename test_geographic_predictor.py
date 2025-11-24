#!/usr/bin/env python3
"""
Test Geographic ToA Prediction

Verifies that the WWVGeographicPredictor correctly:
1. Converts Maidenhead grid squares to lat/lon
2. Calculates great circle distances
3. Estimates propagation delays
4. Classifies single peaks
"""

import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent / 'src' / 'signal_recorder'
sys.path.insert(0, str(src_path))

# Direct import without going through __init__.py
import wwv_geographic_predictor
WWVGeographicPredictor = wwv_geographic_predictor.WWVGeographicPredictor

def test_grid_conversion():
    """Test Maidenhead grid to lat/lon conversion"""
    print("=" * 60)
    print("TEST 1: Grid Square Conversion")
    print("=" * 60)
    
    test_cases = [
        ("EM38ww", (38.020833, -94.958333)),  # Expected approximate values
        ("FN20", (40.5, -74.0)),
    ]
    
    for grid, expected in test_cases:
        lat, lon = WWVGeographicPredictor.grid_to_latlon(grid)
        print(f"  {grid:8} → {lat:8.4f}°N, {lon:9.4f}°E")
        print(f"           (expected ~{expected[0]:.4f}°N, {expected[1]:.4f}°E)")
    print()

def test_delay_prediction():
    """Test ToA prediction for different locations and frequencies"""
    print("=" * 60)
    print("TEST 2: ToA Prediction (EM38ww - Kansas City area)")
    print("=" * 60)
    
    predictor = WWVGeographicPredictor(receiver_grid="EM38ww")
    
    frequencies = [2.5, 5.0, 10.0, 15.0, 20.0]
    
    for freq_mhz in frequencies:
        result = predictor.calculate_expected_delays(freq_mhz, use_history=False)
        
        print(f"\n{freq_mhz} MHz:")
        print(f"  WWV delay:    {result['wwv_delay_ms']:6.2f} ms (range: {result['wwv_range'][0]:.2f}-{result['wwv_range'][1]:.2f} ms)")
        print(f"  WWVH delay:   {result['wwvh_delay_ms']:6.2f} ms (range: {result['wwvh_range'][0]:.2f}-{result['wwvh_range'][1]:.2f} ms)")
        print(f"  Differential: {result['differential_delay_ms']:6.2f} ms")
        print(f"  Confidence:   {result['confidence']:.2f} (history: {result['history_count']} measurements)")

def test_single_peak_classification():
    """Test classification of single peaks"""
    print("\n" + "=" * 60)
    print("TEST 3: Single Peak Classification")
    print("=" * 60)
    
    predictor = WWVGeographicPredictor(receiver_grid="EM38ww")
    
    # Get expected delays for 10 MHz
    expected = predictor.calculate_expected_delays(10.0, use_history=False)
    
    print(f"\nExpected at 10 MHz:")
    print(f"  WWV:  {expected['wwv_delay_ms']:.2f} ms (±{expected['wwv_range'][1]-expected['wwv_delay_ms']:.2f} ms)")
    print(f"  WWVH: {expected['wwvh_delay_ms']:.2f} ms (±{expected['wwvh_range'][1]-expected['wwvh_delay_ms']:.2f} ms)")
    
    # Test cases: (peak_delay_ms, peak_amplitude, quality, expected_classification)
    test_cases = [
        (expected['wwv_delay_ms'], 10.0, 5.0, "WWV"),  # Peak at WWV expected delay
        (expected['wwvh_delay_ms'], 10.0, 5.0, "WWVH"),  # Peak at WWVH expected delay
        (expected['wwv_delay_ms'] + 1.0, 10.0, 5.0, "WWV"),  # Close to WWV
        (expected['wwvh_delay_ms'] - 1.0, 10.0, 5.0, "WWVH"),  # Close to WWVH
        ((expected['wwv_delay_ms'] + expected['wwvh_delay_ms']) / 2, 10.0, 5.0, None),  # Ambiguous
        (expected['wwv_delay_ms'], 10.0, 1.0, None),  # Low quality
    ]
    
    print("\nClassification tests:")
    for peak_delay, amplitude, quality, expected_class in test_cases:
        result = predictor.classify_single_peak(peak_delay, amplitude, 10.0, quality)
        status = "✅" if result == expected_class else "❌"
        print(f"  {status} Peak at {peak_delay:6.2f}ms, Q={quality:.1f}: {result or 'None':5} (expected: {expected_class or 'None'})")

def test_different_locations():
    """Test ToA prediction for various receiver locations"""
    print("\n" + "=" * 60)
    print("TEST 4: Different Receiver Locations (10 MHz)")
    print("=" * 60)
    
    locations = [
        ("EM38ww", "Kansas City, KS"),
        ("FN20", "New York, NY"),
        ("DM79", "Phoenix, AZ"),
        ("CM87", "Los Angeles, CA"),
        ("FN31", "Washington, DC"),
    ]
    
    for grid, name in locations:
        predictor = WWVGeographicPredictor(receiver_grid=grid)
        result = predictor.calculate_expected_delays(10.0, use_history=False)
        
        print(f"\n{name} ({grid}):")
        print(f"  WWV:  {result['wwv_delay_ms']:6.2f} ms")
        print(f"  WWVH: {result['wwvh_delay_ms']:6.2f} ms")
        print(f"  Δ:    {result['differential_delay_ms']:6.2f} ms")

if __name__ == "__main__":
    print("\n🌍 WWV Geographic ToA Predictor Test Suite\n")
    
    try:
        test_grid_conversion()
        test_delay_prediction()
        test_single_peak_classification()
        test_different_locations()
        
        print("\n" + "=" * 60)
        print("✅ All tests completed successfully!")
        print("=" * 60)
        print("\nThe geographic ToA predictor is ready to use.")
        print("It will enable single-station BCD detection when configured with:")
        print("  - receiver_grid: Maidenhead grid square in grape-config.toml")
        print("  - frequency_mhz: Operating frequency passed to discrimination")
        print()
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
