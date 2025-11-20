# Decimation Investigation Summary - November 20, 2025

## Original Concern
User observed spectral "incursions" in 10 Hz decimated spectrograms and hypothesized they were caused by:
1. Fixed-point arithmetic issues (quantization noise, overflow)
2. Decimation filter artifacts

## Investigation Results

### Fixed-Point Hypothesis: ❌ INCORRECT
- System uses `float32` (complex64) throughout entire DSP chain
- Conversion from `int16` to `float32` happens immediately upon RTP packet reception
- Dynamic range: ~150 dB (far exceeds 16-bit ~96 dB)
- No quantization or overflow possible

### Decimation Artifacts Hypothesis: ❌ INCORRECT
- Compared original `decimation.py` against proposed scipy-based alternative
- Generated 24-hour spectrograms from real WWV 5 MHz data (2025-11-19)
- **Result:** Both methods produce virtually identical spectrograms
- Numerical analysis shows no significant improvement (actually 7 dB worse at 4 Hz in "improved" method)

### Root Cause: ✅ NO DECIMATION PROBLEM
The current `decimation.py` implementation is working correctly. The spectral "incursions" observed are:
- **NOT** from decimation artifacts
- **NOT** from fixed-point arithmetic issues
- Likely real RF phenomena: propagation effects, interference, signal fading

## Conclusion
**No changes needed to decimation.py.** The current implementation is correct and performs well.

## Files Archived
- `decimation_improved.py` - Removed (no benefit)
- `DECIMATION_ARTIFACTS_ANALYSIS.md` - Archived (incorrect hypothesis)
- `DECIMATION_ARTIFACTS_RESOLUTION.md` - Archived (unnecessary)
- `test-improved-decimation.py` - Archived
- `diagnose_decimation_artifacts.py` - Archived
- Comparison spectrograms - Deleted

## Lesson Learned
Always validate synthetic test signals carefully. Initial diagnostic was flawed - detected intentional DC component, not aliasing. Real-world data is the ultimate test.
