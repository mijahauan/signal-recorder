# Float32 IQ Normalization for ka9q-radio

## Overview

When receiving IQ data from `radiod` in float32 encoding (PT 11 or dynamic), a **32x normalization factor** must be applied to achieve amplitude levels consistent with int16 encoding.

This document explains the empirical derivation, technical investigation, and current understanding of this calibration constant.

## The Problem

After switching from int16 to float32 encoding (December 2024), carrier power measurements dropped by ~30 dB:

| Encoding | Observed Power | Expected Power |
|----------|----------------|----------------|
| int16 (normalized /32768) | -24 to -40 dB | ✓ Correct |
| float32 (raw) | -54 to -70 dB | ✗ 30 dB too low |
| float32 (×32) | -24 to -40 dB | ✓ Correct |

## Empirical Derivation

Direct measurement of RTP packet amplitudes:

```
Float32 max amplitude: 0.002
Expected int16 normalized: 0.063 (for -24 dB signal)
Ratio: 0.063 / 0.002 = 31.5x ≈ 32x
dB difference: 20 × log10(31.5) = 30 dB
```

The factor 32 = 2^5 suggests a bit-shift or accumulation of ~6 dB factors.

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

## Implementation

In `pipeline_recorder.py`, the normalization is applied:

```python
elif payload_type == 11:
    # float32 IQ format
    samples = np.frombuffer(payload, dtype=np.float32)
    # Normalize float32 to match int16/32768 levels
    # radiod float32 output is ~32x smaller than int16 normalized
    samples = samples * 32.0

elif 96 <= payload_type <= 127:
    # Dynamic payload type - auto-detect
    if 1e-10 < max_float < 10.0:
        # Normalize float32 to match int16/32768 levels
        samples = samples_float * 32.0
```

## Caveats and Limitations

The 32x factor is **empirically derived** and may change with:

- **Different radiod versions** - Internal scaling may change
- **Different ADCs/receivers** - RX-888 vs other SDRs
- **Different gain settings** - rf_gain, rf_atten values
- **Different presets** - IQ vs USB vs other modes

## Recommendations

1. **Monitor for drift**: If power levels shift unexpectedly, the normalization factor may need adjustment.

2. **Consider auto-calibration**: A brief int16/float32 comparison during startup could derive the factor dynamically.

3. **Configuration option**: The factor could be made configurable in `grape-config.toml`:
   ```toml
   [recorder.channel_defaults]
   float32_normalization = 32.0
   ```

4. **Upstream clarification**: The ka9q-radio project could document the expected float32 output scaling.

## References

- ka9q-radio source: `/home/wsprdaemon/ka9q-radio/src/`
  - `audio.c`: Output encoding (scaleclip vs memcpy)
  - `radio.c`: Frontend scaling (scale_AD function)
  - `misc.h`: scaleclip definition
  - `linear.c`: Demodulator gain handling

- Date of investigation: December 9, 2024
- Receiver: RX-888 via radiod (bee1-hf-status.local)
- Configuration: IQ mode, 20 kHz sample rate, AGC off, gain=0
