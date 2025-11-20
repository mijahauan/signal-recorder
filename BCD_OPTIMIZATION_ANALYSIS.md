# BCD Correlation Optimization Analysis

## Current Performance Bottleneck

**Problem:** Cross-correlating 240,000-sample windows is extremely expensive
- 45 windows per minute × 1,300 minutes = 58,500 correlations
- Each correlation: 240K × 240K operations
- Total: ~28 billion floating-point operations

**Current timing:**
- ~0.5s per correlation window (default scipy method)
- ~22.7s per minute of data
- ~8.2 hours for 1,300 minutes (with 16-core parallelization)

## Optimization Options

### 1. ✅ Use Explicit FFT Method (30% speedup)

**Change:** Add `method='fft'` parameter to `scipy.signal.correlate()`

```python
# Current (line 754 in wwvh_discrimination.py):
correlation = scipy_signal.correlate(signal_window, template_window, mode='full')

# Optimized:
correlation = scipy_signal.correlate(signal_window, template_window, mode='full', method='fft')
```

**Benefit:** 0.504s → 0.349s per window (30% faster)
**New total time:** ~5.7 hours for 1,300 minutes (16 cores)
**Effort:** 1-line change

---

### 2. 🚀 GPU Acceleration with CuPy (10-50x speedup)

**Requirements:**
- NVIDIA GPU with CUDA
- CuPy library (`pip install cupy-cuda11x`)
- cuSignal for GPU signal processing

**Implementation:**
```python
import cupy as cp
import cusignal

# Move data to GPU
signal_gpu = cp.asarray(signal_window)
template_gpu = cp.asarray(template_window)

# Correlate on GPU
correlation_gpu = cusignal.correlate(signal_gpu, template_gpu, mode='full')
correlation = cp.asnumpy(correlation_gpu)  # Back to CPU
```

**Benefit:** 10-50x speedup (depends on GPU)
**New total time:** ~20-40 minutes for 1,300 minutes
**Effort:** Install CuPy, modify detection code
**Limitation:** Requires NVIDIA GPU

---

### 3. 📉 Reduce Window Count (80% speedup)

**Change:** Use larger step size (3-5 seconds instead of 1 second)

```python
# Current: 1-second steps = 45 windows/minute
step_seconds: int = 1

# Optimized: 3-second steps = 15 windows/minute
step_seconds: int = 3
```

**Benefit:** 45 → 15 windows (66% reduction)
**New total time:** ~2.7 hours for 1,300 minutes (16 cores)
**Trade-off:** Lower temporal resolution (still captures ionospheric dynamics)
**Effort:** 1-line change

---

### 4. 🔽 Decimate Before Correlation (2-4x speedup)

**Approach:** Reduce sample rate before correlation (e.g., 16 kHz → 4 kHz)

```python
from scipy.signal import decimate

# Decimate by factor of 4: 16 kHz → 4 kHz
signal_decimated = decimate(signal_window, 4, ftype='fir')
template_decimated = decimate(template_window, 4, ftype='fir')

# Correlation is now 4x faster (60K samples instead of 240K)
correlation = scipy_signal.correlate(signal_decimated, template_decimated, mode='full', method='fft')
```

**Benefit:** 2-4x speedup (16x fewer samples, but FFT is O(N log N))
**New total time:** ~3 hours for 1,300 minutes (16 cores)
**Trade-off:** Lower frequency resolution, may miss fine temporal structure
**Effort:** Add decimation step, adjust peak detection thresholds

---

### 5. ⚡ Intel MKL or OpenBLAS (10-30% speedup)

**Approach:** Use optimized BLAS library for NumPy/SciPy

**Install Intel MKL:**
```bash
pip install intel-numpy intel-scipy
```

**Or use OpenBLAS:**
```bash
sudo apt install libopenblas-dev
pip install --force-reinstall --no-binary numpy,scipy numpy scipy
```

**Benefit:** 10-30% speedup for FFT operations
**New total time:** ~5 hours for 1,300 minutes (16 cores)
**Effort:** Reinstall NumPy/SciPy with optimized BLAS

---

### 6. 🎯 Hybrid Approach: Coarse + Fine (2-3x speedup)

**Strategy:** Use two-stage correlation

1. **Coarse search:** Decimate to 4 kHz, find approximate peak locations
2. **Fine search:** Only correlate ±100ms around coarse peaks at full 16 kHz resolution

```python
# Stage 1: Coarse correlation (4 kHz, full range)
signal_coarse = decimate(signal_window, 4)
template_coarse = decimate(template_window, 4)
corr_coarse = correlate(signal_coarse, template_coarse, mode='full', method='fft')
coarse_peaks = find_peaks(corr_coarse)  # Fast, low resolution

# Stage 2: Fine correlation only near peaks (16 kHz, small windows)
for peak in coarse_peaks:
    # Extract ±100ms windows around each coarse peak
    start = max(0, peak * 4 - 1600)  # 100ms at 16 kHz
    end = min(len(signal_window), peak * 4 + 1600)
    fine_window = signal_window[start:end]
    fine_template = template_window[start:end]
    fine_corr = correlate(fine_window, fine_template, mode='full', method='fft')
    # Refine peak location
```

**Benefit:** 2-3x speedup (coarse stage is fast, fine stage is small)
**New total time:** ~2.5 hours for 1,300 minutes (16 cores)
**Trade-off:** More complex code, marginal accuracy loss
**Effort:** Moderate refactoring

---

## Recommended Optimization Strategy

### **Immediate (Quick Wins):**

1. **Add `method='fft'`** (30% speedup, 1 line)
2. **Increase step to 3 seconds** (66% reduction, 1 line)

**Combined effect:** ~5x speedup → **1 hour for 1,300 minutes (16 cores)**

### **Short-term (If reprocessing often):**

3. **Add decimation to 8 kHz** (2x speedup)

**Combined effect:** ~10x speedup → **30 minutes for 1,300 minutes**

### **Long-term (If GPU available):**

4. **GPU acceleration with CuPy/cuSignal** (50x speedup)

**Effect:** **5-10 minutes for 1,300 minutes**

---

## Implementation Priority

| Optimization | Speedup | Effort | When to Use |
|-------------|---------|--------|-------------|
| FFT method | 1.3x | Trivial | Always |
| 3-sec steps | 3x | Trivial | Default |
| Decimation | 2x | Easy | If 3-sec resolution sufficient |
| GPU | 50x | Moderate | For large-scale reprocessing |
| MKL/OpenBLAS | 1.2x | Easy | One-time setup improvement |

---

## Scientific Trade-offs

**Temporal resolution needs:**
- **1-second steps:** Captures <5s ionospheric scintillation (rarely needed)
- **3-second steps:** Captures 5-15s coherence time variations (typical)
- **5-second steps:** Captures large-scale fading (sufficient for most analysis)

**Recommendation:** Use 3-second steps as default (15 data points/minute still excellent)

**Frequency resolution:**
- **16 kHz:** Full bandwidth, captures all timing precision
- **8 kHz:** Still adequate for 5-30ms delay detection
- **4 kHz:** Marginal for fine timing, but usable

**Recommendation:** Test with 8 kHz decimation first

---

## Code Changes Required

### Immediate Fix (5x speedup):

```python
# File: src/signal_recorder/wwvh_discrimination.py
# Line 687-688: Change default parameters

def detect_bcd_discrimination(
    self,
    iq_samples: np.ndarray,
    sample_rate: int,
    minute_timestamp: float,
    window_seconds: int = 15,
    step_seconds: int = 3,  # Changed from 1 to 3
) -> Tuple[...]:

# Line 754: Add method='fft'
correlation = scipy_signal.correlate(
    signal_window, 
    template_window, 
    mode='full',
    method='fft'  # Add this parameter
)
```

**That's it!** Two simple changes for 5x speedup.
