# Installation Guide

This guide provides instructions for installing Signal Recorder and its dependencies.

## 1. Prerequisites

### 1.1 ka9q-radio

Signal Recorder requires a running instance of [ka9q-radio](https://github.com/ka9q/ka9q-radio) to provide the RTP signal streams. Please ensure radiod is installed, configured, and running.

### 1.2 System Dependencies

- **Python**: 3.10 or higher
- **Avahi**: For mDNS service discovery
- **pcmrecord**: From ka9q-radio (must be in system PATH)
- **sox**: For audio processing (concatenation and resampling)
- **wavpack**: For compressing and decompressing recordings

#### Installation on Debian/Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv sox wavpack avahi-daemon avahi-utils
```

## 2. Installation

### 2.1 From Source

It is recommended to install Signal Recorder in a Python virtual environment.

```bash
# Clone the repository
git clone https://github.com/yourusername/signal-recorder.git
cd signal-recorder

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install the package in editable mode
pip install -e .
```

### 2.2 From PyPI (Future)

Once published, you will be able to install from PyPI:

```bash
pip install signal-recorder
```

## 3. Configuration

### 3.1 Initialize Configuration

Run the `init` command to create an example configuration file:

```bash
signal-recorder init --config /etc/signal-recorder/config.toml
```

This will create `/etc/signal-recorder/config.toml` with default settings.

### 3.2 Edit Configuration

Open the configuration file and edit it to match your setup:

```bash
sudo nano /etc/signal-recorder/config.toml
```

**Key sections to edit:**

- **`[station]`**: Set your station ID, callsign, grid square, and coordinates.
- **`[recorder.streams]`**: 
  - Set `stream_name` to match the mDNS service name from your radiod configuration (e.g., `WWV-IQ`).
  - Update `frequencies` to the list of frequencies you want to record.
  - Update `band_mapping` to match your desired directory structure.
- **`[upload]`**: 
  - Set `host`, `user`, and `base_path` for your upload server.
  - Set `key_file` to the path of your SSH private key for passwordless login.

### 3.3 Create Directories

Create the archive directory specified in the configuration:

```bash
sudo mkdir -p /var/lib/signal-recorder/archive
sudo chown -R youruser:yourgroup /var/lib/signal-recorder
```

## 4. Testing

### 4.1 Discover Streams

Test if Signal Recorder can discover streams from your running radiod instance:

```bash
signal-recorder discover --radiod wwv-iq.local
```

This should list all available streams and their parameters.

### 4.2 Run in Foreground

Run the daemon in the foreground to test recording:

```bash
signal-recorder daemon --config /etc/signal-recorder/config.toml --verbose
```

Check the output for any errors. You should see recorders being started and files being created in your archive directory.

## 5. Running as a Service

### 5.1 Create systemd Service File

Create a systemd service file `/etc/systemd/system/signal-recorder.service`:

```ini
[Unit]
Description=Signal Recorder Daemon
After=network-online.target

[Service]
User=youruser
Group=yourgroup
ExecStart=/path/to/your/venv/bin/signal-recorder daemon --config /etc/signal-recorder/config.toml
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Important:**
- Replace `youruser` and `yourgroup` with the user you want to run the service as.
- Replace `/path/to/your/venv/bin/` with the correct path to your virtual environment.

### 5.2 Enable and Start Service

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable signal-recorder.service

# Start the service
sudo systemctl start signal-recorder.service

# Check status
sudo systemctl status signal-recorder.service
```

You can view logs using `journalctl`:

```bash
journalctl -u signal-recorder -f
```

