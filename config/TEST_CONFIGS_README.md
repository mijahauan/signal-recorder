# Test Configuration Files

This directory contains several test configurations for verifying dynamic channel creation.

## Test Configurations

### `test-new-channel.toml` - 14.5 MHz Test

Creates a new channel at **14.5 MHz** (SSRC 14500000).

This frequency was chosen because:
- It's between your existing 14.074 MHz and 14.080 MHz channels
- It doesn't overlap with any current channels
- It's in the 20m amateur radio band

**Usage:**
```bash
signal-recorder create-channels --config config/test-new-channel.toml
```

**Verification:**
```bash
control -v 239.251.200.193 | grep 14500000
```

### `test-new-channel-21mhz.toml` - 21.5 MHz Test

Creates a new channel at **21.5 MHz** (SSRC 21500000).

This frequency was chosen because:
- It's between your existing 21.074 MHz and 21.140 MHz channels
- It's in the 15m amateur radio band
- Alternative test frequency if 14.5 MHz doesn't work

**Usage:**
```bash
signal-recorder create-channels --config config/test-new-channel-21mhz.toml
```

**Verification:**
```bash
control -v 239.251.200.193 | grep 21500000
```

### `test-channel-creation.toml` - Original Test (30 MHz)

The original test configuration for 30 MHz (SSRC 30000000).

**Note:** This channel already exists in your system (shows as 3 MHz in the channel list).

## Automated Test Script

Use the provided test script for automated testing:

```bash
./test-channel-creation.sh
```

This script will:
1. List current channels
2. Create a new channel at 14.5 MHz
3. Verify the channel was created successfully
4. Display the new channel details

## Configuration Parameters

All test configs use these settings to match your existing channels:

- **preset**: `usb` (matches your existing channels)
- **sample_rate**: `12000` Hz (matches your existing channels)
- **status_address**: `239.251.200.193` (your radiod status address)

## SSRC Selection

The SSRC (Synchronization Source) is set to match the frequency in Hz:
- 14.5 MHz → SSRC 14500000
- 21.5 MHz → SSRC 21500000

This follows the convention used in your existing channels.

## Troubleshooting

### Channel creation appears successful but verification fails

Check if the `control` utility is installed:
```bash
which control
```

If not available, manually verify with:
```bash
# Monitor radiod status packets
sudo tcpdump -i lo -n 'host 239.251.200.193' | grep -A5 "14500000"
```

### Channel created with wrong frequency

Check the radiod logs:
```bash
sudo journalctl -u radiod@* -f
```

Look for messages about the new SSRC and frequency settings.

### Packets sent but channel not created

Verify radiod configuration has `data=` parameter:
```bash
grep "data" /etc/radio/radiod@*.conf
```

Should show something like:
```
data = 239.251.200.0/24
```

## Next Steps After Successful Creation

Once channel creation is verified:

1. **Test recording from the new channel**
2. **Test the GRAPE processing pipeline**
3. **Set up automated channel creation in daemon mode**
4. **Configure channels for actual GRAPE frequencies**

## Cleanup

To remove test channels, you can either:

1. **Restart radiod** (channels will be lost unless saved to config)
2. **Manually remove from radiod config** if you saved them
3. **Use control utility** to delete the channel (if supported)

```bash
# Restart radiod to clear dynamic channels
sudo systemctl restart radiod@ac0g-bee1-rx888
```

