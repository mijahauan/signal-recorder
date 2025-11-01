# Migration to ka9q-python Library

This document describes how to migrate signal-recorder to use the standalone `ka9q` library.

## Overview

The radiod control functionality has been extracted into a standalone package:
- **Before**: Code in `src/signal_recorder/radiod_control.py` and `control_discovery.py`
- **After**: Separate `ka9q-python` package at `/home/mjh/git/ka9q-python`

## Benefits

✅ **Reusable** - Other projects can use the same API  
✅ **Focused** - signal-recorder focuses on GRAPE recording  
✅ **Maintainable** - Changes to ka9q don't affect GRAPE logic  
✅ **Testable** - ka9q library has its own tests  
✅ **Community** - Others can contribute to ka9q development  

## Installation

The ka9q package is already installed in editable mode:

```bash
cd /home/mjh/git/ka9q-python
pip install -e .
```

This allows development on both packages simultaneously.

## Migration Steps

### Step 1: Update requirements.txt

```diff
# Signal Recorder - Core Dependencies

# Configuration parsing
toml>=0.10.2

# Numerical computing and array operations
numpy>=1.24.0

# Signal processing and resampling (12 kHz → 10 Hz)
scipy>=1.10.0

# Audio file I/O (for compatibility with existing code)
soundfile>=0.12.0

# Digital RF format I/O (HamSCI PSWS compatible)
digital_rf>=2.6.0

# mDNS/Avahi service discovery for ka9q-radio streams
zeroconf>=0.132.0

+# ka9q-radio control library
+ka9q>=1.0.0
+
# WWV Timing Analysis & Visualization (optional, for plot_wwv_timing.py)
pandas>=2.0.0
matplotlib>=3.7.0
```

### Step 2: Update Imports

Replace all imports in signal-recorder code:

```python
# OLD
from signal_recorder.radiod_control import RadiodControl
from signal_recorder.control_discovery import discover_channels_via_control, ChannelInfo

# NEW
from ka9q import RadiodControl
from ka9q import discover_channels, ChannelInfo
```

### Step 3: Update Function Calls

Rename the discovery function:

```python
# OLD
channels = discover_channels_via_control("radiod.local")

# NEW
channels = discover_channels("radiod.local")
```

### Step 4: Update channel_manager.py

```diff
"""
Channel management for ka9q-radio
"""

import logging
import time
from typing import List, Dict, Optional
-from .control_discovery import discover_channels_via_control, ChannelInfo
-from .radiod_control import RadiodControl
+from ka9q import discover_channels, ChannelInfo, RadiodControl

logger = logging.getLogger(__name__)


class ChannelManager:
    """Manages channel creation and configuration for ka9q-radio"""
    
    def discover_existing_channels(self) -> Dict[int, ChannelInfo]:
        """Discover all existing channels from radiod"""
        logger.info(f"Discovering existing channels from {self.status_address}")
-       channels = discover_channels_via_control(self.status_address)
+       channels = discover_channels(self.status_address)
        logger.info(f"Found {len(channels)} existing channels")
        return channels
```

### Step 5: Remove Old Files

After migration is complete and tested:

```bash
cd /home/mjh/git/signal-recorder
rm src/signal_recorder/radiod_control.py
rm src/signal_recorder/control_discovery.py
```

### Step 6: Create GRAPE Helper Module (Optional)

For GRAPE-specific defaults, create `src/signal_recorder/grape_helpers.py`:

```python
"""
GRAPE-specific helpers for ka9q channel management
Adds GRAPE defaults on top of ka9q library
"""

from ka9q import RadiodControl

def create_grape_iq_channel(control: RadiodControl, frequency_mhz: float):
    """
    Create GRAPE-standard IQ channel
    
    GRAPE defaults:
    - 16 kHz sample rate
    - IQ mode (linear)
    - No AGC (fixed gain)
    - SSRC = frequency in Hz
    """
    ssrc = int(frequency_mhz * 1e6)
    control.create_channel(
        ssrc=ssrc,
        frequency_hz=frequency_mhz * 1e6,
        preset="iq",
        sample_rate=16000,
        agc_enable=0,
        gain=0.0
    )
    return ssrc

def create_grape_am_channel(control: RadiodControl, frequency_mhz: float):
    """
    Create GRAPE-standard AM audio channel
    
    GRAPE defaults:
    - 12 kHz sample rate
    - AM mode
    - AGC enabled
    - SSRC = frequency in Hz + 1
    """
    ssrc = int(frequency_mhz * 1e6) + 1
    control.create_channel(
        ssrc=ssrc,
        frequency_hz=frequency_mhz * 1e6,
        preset="am",
        sample_rate=12000,
        agc_enable=1,
        gain=0.0
    )
    return ssrc
```

## Testing

### Test ka9q Installation

```python
python3 -c "from ka9q import RadiodControl; print('✓ ka9q installed')"
```

### Test Channel Creation

```python
from ka9q import RadiodControl

control = RadiodControl("bee1-hf-status.local")
control.create_channel(
    ssrc=10000000,
    frequency_hz=10.0e6,
    preset="am",
    sample_rate=12000
)
print("✓ Channel created successfully")
```

### Test Discovery

```python
from ka9q import discover_channels

channels = discover_channels("bee1-hf-status.local")
print(f"✓ Found {len(channels)} channels")
for ssrc, info in channels.items():
    print(f"  {ssrc}: {info.frequency/1e6:.3f} MHz")
```

## File Changes Summary

### Files to Modify
- `requirements.txt` - Add ka9q>=1.0.0
- `src/signal_recorder/channel_manager.py` - Update imports
- `src/signal_recorder/grape_recorder.py` - Update imports (if used)
- Any other files importing radiod_control or control_discovery

### Files to Remove (After Migration)
- `src/signal_recorder/radiod_control.py`
- `src/signal_recorder/control_discovery.py`

### Files to Add (Optional)
- `src/signal_recorder/grape_helpers.py` - GRAPE-specific convenience functions

## Rollback Plan

If issues arise, rollback is simple since ka9q is installed in editable mode:

1. Keep old files temporarily
2. Revert imports
3. Old functionality still available

## Timeline

**Phase 1: Install and Test** (Already done)
- ✅ Created ka9q-python package
- ✅ Installed in editable mode
- ⏭️ Test basic functionality

**Phase 2: Migrate Imports** (Next)
- Update requirements.txt
- Update imports in channel_manager.py
- Update imports in other files
- Test GRAPE recording still works

**Phase 3: Cleanup** (After testing)
- Remove old files
- Update documentation
- Create GRAPE helpers if needed

**Phase 4: Publish** (Optional, future)
- Publish ka9q to PyPI
- Update signal-recorder to use PyPI version
- Share ka9q with community

## Current Status

✅ ka9q-python package created at `/home/mjh/git/ka9q-python`  
✅ Installed in signal-recorder venv  
✅ Examples working independently  
⏭️ Ready to migrate signal-recorder  

## Next Steps

1. Update `requirements.txt`
2. Update imports in `channel_manager.py`
3. Test daemon starts successfully
4. Test channel creation works
5. Test WWV tone detection works
6. Remove old files
7. Commit changes

---

## Questions?

- Check `/home/mjh/git/ka9q-python/README.md` for ka9q documentation
- Check `/home/mjh/git/ka9q-python/examples/` for usage examples
- Old code still available in git history if needed
