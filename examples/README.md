# ka9q-radio Control Examples

Diverse examples showing how the radiod control API can be used for completely different applications beyond signal recording.

## Philosophy

**Zero assumptions.** Each example is self-contained and shows a different use case. The API doesn't assume you're:
- Recording data
- Using GRAPE format
- Monitoring WWV
- Storing anything
- Using specific sample rates

You specify **exactly** what you need for your application.

---

## Examples

### 1. Simple AM Radio (`simple_am_radio.py`)
**Use case:** Just listen to an AM broadcast  
**Demonstrates:** Minimal code to create a channel  
**Complexity:** Beginner  

```bash
python examples/simple_am_radio.py
```

Creates single AM channel on 10 MHz WWV. Shows you can start from scratch in ~20 lines.

---

### 2. SuperDARN Radar Recorder (`superdarn_recorder.py`)
**Use case:** Monitor coherent scatter radar for ionospheric research  
**Demonstrates:** 
- High bandwidth I/Q (50 kHz)
- Multiple frequencies
- Fixed gain for radar
**Complexity:** Intermediate

```bash
python examples/superdarn_recorder.py
```

Sets up 7 channels across HF band for SuperDARN monitoring. Completely different requirements than GRAPE - needs wide bandwidth, no AGC, I/Q for Doppler analysis.

---

### 3. CODAR Oceanography (`codar_oceanography.py`)
**Use case:** Monitor coastal ocean current radars  
**Demonstrates:**
- Site-specific configurations
- FMCW radar requirements
- Medium bandwidth (20 kHz)
**Complexity:** Intermediate

```bash
python examples/codar_oceanography.py
```

Creates channels for multiple CODAR sites. Shows how to configure for oceanographic radar - very different from either GRAPE or SuperDARN.

---

### 4. HF Band Scanner (`hf_band_scanner.py`)
**Use case:** Scan HF bands for activity  
**Demonstrates:**
- Dynamic frequency hopping
- Channel reuse
- No recording/storage
- User-controlled scan patterns
**Complexity:** Advanced

```bash
python examples/hf_band_scanner.py
```

Scans amateur and maritime bands. Shows the API works for completely dynamic applications where you're constantly changing frequencies, not recording anything.

---

## Common Patterns

### Create Channel (Any Application)
```python
from signal_recorder.radiod_control import RadiodControl

control = RadiodControl("your-radiod.local")

control.create_and_configure_channel(
    ssrc=12345678,           # Your choice
    frequency_hz=14.074e6,   # Any frequency
    preset="usb",            # Any mode: iq, am, fm, usb, lsb, cw
    sample_rate=48000,       # Any rate radiod supports
    agc_enable=1,            # 0=off, 1=on
    gain=0.0                 # dB (if AGC off)
)
```

### Granular Control (Advanced)
```python
# Fine-tune individual parameters
control.set_frequency(ssrc=12345678, frequency_hz=14.095e6)
control.set_filter(ssrc=12345678, low_edge=-2400, high_edge=2400)
control.set_agc(ssrc=12345678, enable=True, hangtime=1.5, headroom=12.0)
```

### Discovery (Query Existing)
```python
from signal_recorder.control_discovery import discover_channels_via_control

channels = discover_channels_via_control("radiod.local")
for ssrc, info in channels.items():
    print(f"{ssrc}: {info.frequency/1e6:.3f} MHz, {info.preset}")
```

---

## What Makes This General-Purpose?

| Feature | GRAPE | SuperDARN | CODAR | AM Radio | Scanner |
|---------|-------|-----------|-------|----------|---------|
| **Sample Rate** | 16 kHz | 50 kHz | 20 kHz | 12 kHz | 12 kHz |
| **Mode** | IQ | IQ | IQ | AM | USB/AM |
| **AGC** | Off | Off | Off | On | On |
| **Frequencies** | 6 fixed | 7 fixed | Site-specific | 1 fixed | Dynamic |
| **Recording** | Yes | Maybe | Maybe | No | No |
| **Storage** | Digital RF | Custom | Custom | None | None |

**The API doesn't care.** You specify what you need.

---

## Next Steps

### For Your Application

1. **Identify requirements:**
   - Frequencies?
   - Sample rate?
   - I/Q or demod?
   - AGC or fixed gain?

2. **Create channels:**
   ```python
   control.create_and_configure_channel(...)
   ```

3. **Receive RTP:**
   - Join multicast group
   - Filter by SSRC
   - Process however you want

4. **Do your thing:**
   - Record
   - Process
   - Analyze
   - Display
   - Forward
   - Whatever!

### Contributing

Have another use case? Add an example:
- HF fax decoder
- DRM digital radio
- Meteor scatter
- EME (moonbounce)
- Satellite downlinks
- RTTY/PSK decoder
- Propagation beacon monitor
- ...anything!

---

## API Documentation

See main docs for complete API:
- `RadiodControl` class - Low-level TLV commands
- `ChannelManager` class - Higher-level management
- All `StatusType` parameters - Full radiod capabilities

**Key Point:** The API exposes **everything radiod can do**, not just what GRAPE needs.
