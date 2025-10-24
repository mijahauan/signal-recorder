# Configuration Reference

Signal Recorder is configured using a TOML file. The default location is `/etc/signal-recorder/config.toml`.

## `[station]`

This section contains information about your station.

- `id` (string, required): Unique identifier for your station (e.g., "PSWS001").
- `instrument_id` (string, required): Instrument ID (usually "1").
- `callsign` (string, required): Your amateur radio callsign.
- `grid_square` (string, required): Your 6-character Maidenhead grid square.
- `latitude` (float, required): Station latitude in decimal degrees.
- `longitude` (float, required): Station longitude in decimal degrees.

**Example:**
```toml
[station]
id = "PSWS001"
instrument_id = "1"
callsign = "AI6VN"
grid_square = "CM87aa"
latitude = 37.7749
longitude = -122.4194
```

## `[recorder]`

This section configures the recording process.

- `archive_dir` (string, required): Path to the directory where recorded and processed files will be stored.
- `file_length` (integer, optional, default: 60): Length of each recording file in seconds.
- `compress` (boolean, optional, default: true): Whether to compress recordings with wavpack.
- `compression_format` (string, optional, default: "wavpack"): Compression format to use.
- `pcmrecord_path` (string, optional, default: "pcmrecord"): Path to the `pcmrecord` executable.

### `[[recorder.streams]]`

This is a list of tables, where each table defines a stream to record.

- `stream_name` (string, required): The mDNS service name from your radiod configuration (e.g., "WWV-IQ").
- `frequencies` (list of integers, required): A list of frequencies (in Hz) to record from this stream.
- `processor` (string, required): The name of the signal processor to use for this stream (e.g., "grape").
- `band_mapping` (table, required): A mapping of frequencies to band names, which are used for directory structure.

**Example:**
```toml
[[recorder.streams]]
stream_name = "WWV-IQ"
frequencies = [2500000, 5000000, 10000000]
processor = "grape"
band_mapping = {
    2500000 = "WWV_2_5",
    5000000 = "WWV_5",
    10000000 = "WWV_10"
}
```

## `[processors]`

This section contains configuration for each signal processor.

### `[processors.grape]`

- `enabled` (boolean, optional, default: true): Whether the GRAPE processor is enabled.
- `target_sample_rate` (integer, optional, default: 10): The target sample rate (in Hz) for the final 24-hour WAV file.
- `output_format` (string, optional, default: "digital_rf"): The output format for the processed data.

**Example:**
```toml
[processors.grape]
enabled = true
target_sample_rate = 10
```

## `[upload]`

This section configures the upload process.

- `protocol` (string, required): The upload protocol to use. Currently supports `ssh_rsync` and `none`.
- `host` (string, required): The hostname or IP address of the upload server.
- `user` (string, required): The username for the upload server.
- `base_path` (string, required): The base path on the remote server where data will be uploaded.
- `max_retries` (integer, optional, default: 5): The maximum number of times to retry a failed upload.
- `retry_backoff_base` (integer, optional, default: 2): The base for the exponential backoff calculation for retries (in minutes).
- `timeout` (integer, optional, default: 3600): The upload timeout in seconds.
- `queue_file` (string, optional, default: "/var/lib/signal-recorder/upload_queue.json"): Path to the upload queue file.

### `[upload.ssh]`

This section contains SSH-specific configuration.

- `key_file` (string, required): Path to the SSH private key for passwordless login.

**Example:**
```toml
[upload]
protocol = "ssh_rsync"
host = "pswsnetwork.eng.ua.edu"
user = "grape"
base_path = "/data/uploads"
max_retries = 5

[upload.ssh]
key_file = "/home/user/.ssh/id_rsa_grape"
```

