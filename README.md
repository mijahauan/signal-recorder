# Signal Recorder

A modular, extensible system for recording and uploading scientific signal data from ka9q-radio.

## Overview

Signal Recorder is designed to work with [ka9q-radio](https://github.com/ka9q/ka9q-radio) to automatically:

1. **Discover** available signal streams via Avahi/mDNS
2. **Record** time-synchronized audio/IQ data from multiple frequencies
3. **Process** recordings with signal-specific plugins (GRAPE, CODAR, etc.)
4. **Upload** processed data to remote repositories (HamSCI PSWS, etc.)

## Key Features

- **Automatic Stream Discovery**: No manual configuration of multicast addresses, ports, or SSRCs
- **Dynamic Adaptation**: Automatically handles radiod restarts and configuration changes
- **Plugin Architecture**: Easy to add new signal types without modifying core code
- **Reliable Upload**: Queue-based upload with retry logic and verification
- **Minimal Configuration**: Users specify stream names, not low-level networking parameters

## Quick Start

### Installation

```bash
# Install from source
git clone https://github.com/yourusername/signal-recorder.git
cd signal-recorder
pip install -e .
```

### Configuration

Create a configuration file `/etc/signal-recorder/config.toml`:

```toml
[station]
id = "PSWS123"
instrument_id = "1"
callsign = "AI6VN"
grid_square = "CM87"

[recorder]
archive_dir = "/var/lib/signal-recorder/archive"

[[recorder.streams]]
stream_name = "WWV-IQ"  # mDNS name from radiod config
frequencies = [2500000, 5000000, 10000000, 15000000, 20000000, 25000000]
processor = "grape"

[upload]
protocol = "ssh_rsync"
host = "pswsnetwork.eng.ua.edu"
user = "grape"
```

### Usage

```bash
# Discover available streams
signal-recorder discover --radiod hf-status.local

# Run as daemon
signal-recorder daemon --config /etc/signal-recorder/config.toml

# Process a specific date manually
signal-recorder process --date 2024-10-22 --config /etc/signal-recorder/config.toml
```

## Architecture

```
ka9q-radio (radiod)
    ↓ RTP streams + Status metadata
Stream Discovery Module
    ↓ Discovered SSRCs and parameters
Stream Recorder Module
    ↓ Time-synchronized WAV files
Storage Manager
    ↓ Organized archive
Signal Processor Plugins (GRAPE, CODAR, etc.)
    ↓ Processed datasets
Upload Manager
    ↓ SSH/rsync, HTTP, S3
Remote Repository (HamSCI PSWS, etc.)
```

## Documentation

- [Installation Guide](docs/installation.md)
- [Configuration Reference](docs/configuration.md)
- [Plugin Development](docs/plugin_development.md)
- [API Documentation](docs/api.md)

## License

MIT License - see LICENSE file for details

## Contributing

Contributions welcome! Please see CONTRIBUTING.md for guidelines.

## Acknowledgments

- [ka9q-radio](https://github.com/ka9q/ka9q-radio) by Phil Karn, KA9Q
- [wsprdaemon](https://github.com/rrobinett/wsprdaemon) by Rob Robinett, AI6VN
- [HamSCI](https://hamsci.org/) GRAPE project

