# Float32 IQ Data from ka9q-radio

## Overview

This document explains the amplitude difference between int16 and float32 IQ encoding from `radiod`, and the design decision to use **raw float32 data without normalization**.

## Design Decision (December 2024)

We use raw float32 data as-is, without applying any normalization factor. This is the scientifically correct approach for signal processing applications.

## The Observed Difference

Float32 data from radiod has ~30 dB lower amplitude than int16:

| Encoding | Typical Amplitude | Power (dBFS) |
|----------|-------------------|--------------|
| int16 /32768 | ~0.063 | -24 dB |
| float32 raw | ~0.002 | -54 dB |

Direct measurement:
```
Float32 max amplitude: 0.002
Int16 normalized amplitude: 0.063 (for same signal)
Ratio: 31.5x ≈ 30 dB
```

## Technical Investigation of ka9q-radio

### Output Encoding Paths (audio.c)

**int16 output (lines 305, 315):**
```c
*pcm_buf++ = scaleclip(buf[i]);
```

**float32 output (line 323):**
```c
memcpy(dp, buf, chunk * chan->output.channels * sizeof(float));
```

The `scaleclip` function (misc.h:203-205):
```c
inline static int16_t scaleclip(float const x){
  return (x >= 1.0) ? INT16_MAX : (x <= -1.0) ? -INT16_MAX : (int16_t)(INT16_MAX * x);
}
```

**Key insight**: int16 multiplies the internal float by 32767, while float32 copies the raw float directly.

### Expected Behavior

If the internal `buf[]` contains floats in the ±1.0 range:
- int16: outputs ±32767
- float32: outputs ±1.0
- After int16/32768 normalization: both should be ±1.0

**But we observe 32x difference**, indicating the internal `buf[]` values are NOT in ±1.0 range.

### Frontend Scaling (radio.c)

The `scale_AD()` function (lines 1596-1608) converts ADC samples to floats:

```c
float scale_AD(struct frontend const *frontend){
  float scale = (1 << (frontend->bitspersample - 1));  // 32768 for 16-bit
  float analog_gain = frontend->rf_gain - frontend->rf_atten + frontend->rf_level_cal;
  return dB2voltage(-analog_gain) / scale;
}
```

For an RX-888 with 16-bit ADC and rf_gain ≈ 10-15 dB:
- `scale = 32768`
- `dB2voltage(-15) ≈ 0.178`
- Result: `0.178 / 32768 ≈ 5.4e-6`

This extremely small scaling factor means the internal floats are much smaller than ±1.0.

### Channel Status (observed via ka9q-python)

```python
ctrl.tune(ssrc) returns:
  encoding: 4 (F32)
  gain: 0.0
  rf_gain: 15.4 dB (auto-adjusted by RF AGC)
  rf_atten: 0.0
  baseband_power: -54 dBFS  # Matches our raw float32 observations!
  agc_enable: False
```

The `baseband_power` of -54 dBFS directly corresponds to the observed float32 amplitude of ~0.002:
```
20 × log10(0.002) = -54 dB ✓
```

## Why 32x Works

The 30 dB (32x) correction appears to compensate for:

1. **Frontend gain calibration** (~15 dB from rf_gain)
2. **ADC scaling factors** 
3. **Filter/FFT normalization**
4. **Possibly other internal scaling**

The exact breakdown is not fully understood from the source code, but the empirical result matches historical int16 data.

## Why Raw Float32 is Better

### The "Volume Knob" Analogy

The **int16 stream** is "mastered for audio" - radiod applies a gain stage (~30 dB) to ensure the signal uses a healthy portion of the 16-bit dynamic range. This is necessary for audio playback or feeding to a sound card.

The **float32 stream** is "raw data" - the internal mathematical representation before the "make it loud enough for humans" stage.

### Benefits of Raw Data

1. **Headroom (Clipping Safety)**
   - int16: 1.0 (32767) is a hard ceiling. A 35 dB spike clips, creating harmonics
   - float32: Signal at 0.002 can spike 35 dB to ~0.11, still far below 1.0
   
2. **Linearity**
   - The int16 gain stage may include non-linear elements (limiters, compressors)
   - Raw float32 bypasses these, giving linear representation of the RF environment

3. **SNR is preserved**
   - Multiplying signal and noise by the same factor doesn't change their ratio
   - Physics-based measurements (Doppler, propagation) are unaffected

## Implementation

In `pipeline_recorder.py`, float32 data is used as-is:

```python
elif payload_type == 11:
    # float32 IQ format (known)
    # Raw float32 from radiod - no normalization applied
    # Typical amplitude ~0.002 (-54 dBFS) for WWV signals
    samples = np.frombuffer(payload, dtype=np.float32)
```

### Adjusted Thresholds

Power detection thresholds were shifted by -30 dB:
- Signal detection: -30 dB → -60 dB
- Reliability assessment: adjusted accordingly

### Visualization

Spectrograms use relative power (normalized to peak), so they are unaffected by the absolute amplitude change.

## References

- ka9q-radio source: `/home/wsprdaemon/ka9q-radio/src/`
  - `audio.c`: Output encoding (scaleclip vs memcpy)
  - `radio.c`: Frontend scaling (scale_AD function)
  - `misc.h`: scaleclip definition
  - `linear.c`: Demodulator gain handling

- Date of investigation: December 9, 2024
- Receiver: RX-888 via radiod (bee1-hf-status.local)
- Configuration: IQ mode, 20 kHz sample rate, AGC off, gain=0
