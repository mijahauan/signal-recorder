# Refactoring Plan: Extract ka9q-radio Python Library

## Problem
Current radiod control API is buried inside `signal_recorder` package with:
- GRAPE-specific defaults (16kHz IQ, etc.)
- Tight coupling to recording workflow
- Not reusable for other projects (AM listening, SuperDARN, CODAR, etc.)

## Solution: Standalone `ka9q` Python Package

### New Structure
```
ka9q-python/                    # Standalone repository/package
├── setup.py                    # Installable package
├── README.md                   # General-purpose docs
├── LICENSE                     # MIT or appropriate
├── ka9q/
│   ├── __init__.py            # Clean imports
│   ├── control.py             # RadiodControl (no defaults)
│   ├── discovery.py           # Channel/service discovery
│   ├── protocol.py            # TLV encoding (pure)
│   ├── types.py               # StatusType enum
│   └── exceptions.py          # Custom exceptions
├── examples/
│   ├── simple_am_radio.py     # Listen to AM broadcast
│   ├── create_channel.py      # Basic channel creation
│   ├── wspr_scanner.py        # WSPR band scanner
│   ├── superdarn_recorder.py  # SuperDARN example
│   └── codar_processor.py     # CODAR example
└── tests/
    └── test_*.py
```

### Signal Recorder Integration
```
signal-recorder/
├── requirements.txt           # Add: ka9q>=1.0.0
├── src/signal_recorder/
│   ├── grape_rtp_recorder.py  # Uses ka9q library
│   └── (remove radiod_control.py, control_discovery.py)
└── ...
```

---

## API Design: Zero Application-Specific Assumptions

### 1. Pure Control Interface (No Defaults)

```python
# ka9q/control.py
from ka9q import RadiodControl

# Minimalist - every parameter explicit
control = RadiodControl("radiod-status.local")

# Create channel (NO defaults - user must specify everything)
control.create_channel(
    ssrc=123456,
    frequency_hz=10.0e6,
    preset="am",
    sample_rate=12000
)

# Or use granular setters
control.set_frequency(ssrc=123456, frequency_hz=14.074e6)
control.set_preset(ssrc=123456, preset="usb")
```

### 2. Discovery (Pure Query)

```python
from ka9q import discover_radiod_services, query_channels

# Find all radiod instances on network
services = discover_radiod_services()
# Returns: [{'name': 'radiod@hf', 'address': '239.1.2.3:5006'}, ...]

# Query existing channels
channels = query_channels("radiod-status.local")
# Returns: {ssrc: ChannelInfo(...), ...}
```

### 3. Application-Specific Helpers (Separate)

```python
# ka9q/helpers.py (optional convenience functions)
from ka9q.helpers import create_am_broadcast_channel, create_iq_channel

# Helper for common patterns, but not in core
create_am_broadcast_channel(
    control,
    frequency_mhz=10.0,
    ssrc=10000000  # User still picks SSRC
)
```

---

## Example Use Cases

### Simple AM Radio Listener
```python
#!/usr/bin/env python3
"""Listen to AM broadcast on 10 MHz WWV"""
from ka9q import RadiodControl

control = RadiodControl("radiod.local")

# Create AM channel
control.create_channel(
    ssrc=10000000,
    frequency_hz=10.0e6,
    preset="am",
    sample_rate=12000
)

# Now stream is available at multicast address with SSRC 10000000
# User handles RTP reception however they want (play, record, process)
```

### SuperDARN Radar Recorder
```python
#!/usr/bin/env python3
"""Record SuperDARN radar pulses"""
from ka9q import RadiodControl
import signal_processor  # User's own processing

control = RadiodControl("radiod.local")

# SuperDARN frequencies (8-20 MHz)
superdarn_freqs = [8.0e6, 10.0e6, 12.0e6, 14.0e6, 16.0e6, 18.0e6, 20.0e6]

for freq in superdarn_freqs:
    ssrc = int(freq)  # Use frequency as SSRC
    control.create_channel(
        ssrc=ssrc,
        frequency_hz=freq,
        preset="iq",           # Need I/Q for Doppler analysis
        sample_rate=50000      # 50 kHz for radar pulses
    )

# Now process RTP streams with user's custom SuperDARN decoder
signal_processor.record_superdarn_data(ssrc_list=superdarn_freqs)
```

### WSPR Band Scanner
```python
#!/usr/bin/env python3
"""Scan WSPR bands"""
from ka9q import RadiodControl
import time

control = RadiodControl("radiod.local")

wspr_bands = [
    (1.8366e6, "160m"),
    (3.5686e6, "80m"),
    (7.0386e6, "40m"),
    (10.1387e6, "30m"),
    (14.0956e6, "20m"),
]

for freq, band in wspr_bands:
    print(f"Creating {band} WSPR channel...")
    control.create_channel(
        ssrc=int(freq),
        frequency_hz=freq,
        preset="usb",
        sample_rate=12000
    )
    time.sleep(0.5)

print("All WSPR channels active!")
```

---

## Migration Path

### Phase 1: Extract to Separate Package (Week 1)
1. Create `ka9q-python/` repository
2. Move code with NO functional changes
3. Remove GRAPE-specific defaults
4. Add examples for diverse use cases
5. Publish to PyPI as `ka9q`

### Phase 2: Update signal-recorder (Week 2)
1. Add `ka9q>=1.0.0` to requirements.txt
2. Replace imports:
   ```python
   # OLD
   from signal_recorder.radiod_control import RadiodControl
   
   # NEW
   from ka9q import RadiodControl
   ```
3. Create `signal_recorder/grape_helpers.py` for GRAPE-specific defaults
4. Remove duplicate code

### Phase 3: Community (Ongoing)
1. Document on GitHub
2. Add to ka9q-radio wiki/ecosystem
3. Accept contributions for other applications
4. Build helper library for common patterns

---

## Benefits

✅ **Reusable** - Any Python project can use it  
✅ **Focused** - Does one thing well (radiod control)  
✅ **No assumptions** - User specifies everything  
✅ **Testable** - Pure functions, no GRAPE coupling  
✅ **Community** - Others can contribute SuperDARN/CODAR/HF fax/etc helpers  
✅ **Maintainable** - Changes to GRAPE don't affect library  

---

## Immediate Action Items

1. **Create `ka9q-python` repository**
2. **Extract 4 core modules**:
   - `ka9q/protocol.py` (TLV encoding - pure)
   - `ka9q/types.py` (StatusType enum)
   - `ka9q/control.py` (RadiodControl class)
   - `ka9q/discovery.py` (channel discovery)
3. **Write 5 examples** (AM, IQ, WSPR, SuperDARN, CODAR)
4. **Remove all GRAPE defaults**
5. **Publish to PyPI**

---

## Questions for User

1. Should I start the refactoring now?
2. Preferred package name: `ka9q`, `ka9q-python`, `pyradio`, other?
3. License preference (MIT, GPL, BSD)?
4. Keep in same repo or create separate `ka9q-python` repo?
