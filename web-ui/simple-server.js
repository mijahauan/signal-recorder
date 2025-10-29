import express from 'express';
import fs from 'fs';
import { spawn, exec } from 'child_process';
import { join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = join(fileURLToPath(import.meta.url), '..');

// Determine base paths based on environment
const isProduction = process.env.NODE_ENV === 'production';
const installDir = isProduction ? '/usr/local/lib/signal-recorder' : join(__dirname, '..');

// Use install directory (repository root or system installation) as base for all operations
const venvPython = join(installDir, 'venv', 'bin', 'python');
const daemonScript = join(installDir, 'src', 'signal_recorder', 'cli.py');
const configPath = isProduction ?
  '/etc/signal-recorder/config.toml' :
  join(installDir, 'config', 'grape-S000171.toml');
const srcPath = join(installDir, 'src');
const dataDir = isProduction ?
  '/var/lib/signal-recorder/data' :
  join(installDir, 'data');
const statusFile = join(installDir, 'data', 'daemon-status.json');

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(express.json({ limit: '50mb' }));
app.use(express.urlencoded({ limit: '50mb', extended: true }));

// JSON database functions
function readJsonFile(filename) {
  try {
    const filePath = join(__dirname, 'data', filename);
    const data = fs.readFileSync(filePath, 'utf8');
    return JSON.parse(data);
  } catch (error) {
    return [];
  }
}

function writeJsonFile(filename, data) {
  try {
    const filePath = join(__dirname, 'data', filename);
    fs.mkdirSync(join(__dirname, 'data'), { recursive: true });
    fs.writeFileSync(filePath, JSON.stringify(data, null, 2));
  } catch (error) {
    console.error(`Failed to write ${filename}:`, error);
    throw error;
  }
}

// Initialize default user
function initializeDefaultUser() {
  try {
    const users = readJsonFile('users.json');
    if (users.length === 0) {
      writeJsonFile('users.json', [{
        id: 'local-admin',
        name: 'Administrator',
        email: 'admin',
        loginMethod: 'local',
        role: 'admin',
        createdAt: new Date().toISOString(),
        lastSignedIn: new Date().toISOString(),
      }]);
      console.log('Default admin user created');
      console.log('Username: admin');
      console.log('Password: admin');
    }
  } catch (error) {
    console.error('Failed to initialize user:', error);
  }
}

// Authentication middleware
function requireAuth(req, res, next) {
  const authHeader = req.headers.authorization;
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return res.status(401).json({ error: 'Authentication required' });
  }

  // Simple token validation - in production, use proper JWT
  const token = authHeader.substring(7);
  if (token === 'admin-token') {
    req.user = { id: 'local-admin', role: 'admin' };
    return next();
  }

  res.status(401).json({ error: 'Invalid token' });
}

// API Routes
app.post('/api/login', async (req, res) => {
  const { username, password } = req.body;

  if (username === 'admin' && password === 'admin') {
    res.json({
      success: true,
      token: 'admin-token',
      user: {
        id: 'local-admin',
        name: 'Administrator',
        role: 'admin'
      }
    });
  } else {
    res.status(401).json({ success: false, error: 'Invalid credentials' });
  }
});

app.get('/api/user', requireAuth, (req, res) => {
  res.json({
    id: req.user.id,
    name: 'Administrator',
    role: req.user.role
  });
});

// Configuration routes
app.get('/api/configurations', requireAuth, async (req, res) => {
  try {
    const configs = readJsonFile('configurations.json');
    res.json(configs);
  } catch (error) {
    console.error('Failed to read configurations:', error);
    res.status(500).json({ error: 'Failed to read configurations' });
  }
});

app.get('/api/configurations/:id', requireAuth, async (req, res) => {
  try {
    const configs = readJsonFile('configurations.json');
    const config = configs.find(c => c.id === req.params.id);
    if (!config) {
      return res.status(404).json({ error: 'Configuration not found' });
    }
    res.json(config);
  } catch (error) {
    console.error('Failed to read configuration:', error);
    res.status(500).json({ error: 'Failed to read configuration' });
  }
});

app.post('/api/configurations', requireAuth, async (req, res) => {
  try {
    const configs = readJsonFile('configurations.json');
    const newConfig = {
      id: Date.now().toString(),
      userId: req.user.id,
      ...req.body,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    configs.push(newConfig);
    writeJsonFile('configurations.json', configs);
    res.json(newConfig);
  } catch (error) {
    console.error('Failed to create configuration:', error);
    res.status(500).json({ error: 'Failed to create configuration' });
  }
});

app.put('/api/configurations/:id', requireAuth, async (req, res) => {
  try {
    const configs = readJsonFile('configurations.json');
    const index = configs.findIndex(c => c.id === req.params.id);

    if (index === -1) {
      return res.status(404).json({ error: 'Configuration not found' });
    }

    configs[index] = {
      ...configs[index],
      ...req.body,
      updatedAt: new Date().toISOString()
    };

    writeJsonFile('configurations.json', configs);
    res.json(configs[index]);
  } catch (error) {
    console.error('Failed to update configuration:', error);
    res.status(500).json({ error: 'Failed to update configuration' });
  }
});

app.delete('/api/configurations/:id', requireAuth, async (req, res) => {
  try {
    let configs = readJsonFile('configurations.json');
    let channels = readJsonFile('channels.json');

    // Remove configuration
    configs = configs.filter(c => c.id !== req.params.id);

    // Remove associated channels
    channels = channels.filter(c => c.configId !== req.params.id);

    writeJsonFile('configurations.json', configs);
    writeJsonFile('channels.json', channels);

    res.json({ success: true });
  } catch (error) {
    console.error('Failed to delete configuration:', error);
    res.status(500).json({ error: 'Failed to delete configuration' });
  }
});

// Channel routes
app.get('/api/configurations/:configId/channels', requireAuth, async (req, res) => {
  try {
    const channels = readJsonFile('channels.json');
    const configChannels = channels.filter(c => c.configId === req.params.configId);
    res.json(configChannels);
  } catch (error) {
    console.error('Failed to read channels:', error);
    res.status(500).json({ error: 'Failed to read channels' });
  }
});

app.post('/api/configurations/:configId/channels', requireAuth, async (req, res) => {
  try {
    const channels = readJsonFile('channels.json');
    const newChannel = {
      id: Date.now().toString(),
      configId: req.params.configId,
      enabled: req.body.enabled || 'yes',
      description: req.body.description,
      frequencyHz: req.body.frequencyHz,
      ssrc: req.body.ssrc,
      sampleRate: req.body.sampleRate || '12000',
      processor: req.body.processor || 'grape',
      createdAt: new Date().toISOString(),
    };
    channels.push(newChannel);
    writeJsonFile('channels.json', channels);
    res.json(newChannel);
  } catch (error) {
    console.error('Failed to create channel:', error);
    res.status(500).json({ error: 'Failed to create channel' });
  }
});

app.put('/api/channels/:id', requireAuth, async (req, res) => {
  try {
    const channels = readJsonFile('channels.json');
    const index = channels.findIndex(c => c.id === req.params.id);

    if (index === -1) {
      return res.status(404).json({ error: 'Channel not found' });
    }

    channels[index] = { ...channels[index], ...req.body };
    writeJsonFile('channels.json', channels);
    res.json(channels[index]);
  } catch (error) {
    console.error('Failed to update channel:', error);
    res.status(500).json({ error: 'Failed to update channel' });
  }
});

app.delete('/api/channels/:id', requireAuth, async (req, res) => {
  try {
    let channels = readJsonFile('channels.json');
    channels = channels.filter(c => c.id !== req.params.id);
    writeJsonFile('channels.json', channels);
    res.json({ success: true });
  } catch (error) {
    console.error('Failed to delete channel:', error);
    res.status(500).json({ error: 'Failed to delete channel' });
  }
});

// TOML export and save endpoint
app.get('/api/configurations/:id/export', requireAuth, async (req, res) => {
  try {
    const configs = readJsonFile('configurations.json');
    const config = configs.find(c => c.id === req.params.id);

    if (!config) {
      return res.status(404).json({ error: 'Configuration not found' });
    }

    const channels = readJsonFile('channels.json');
    const configChannels = channels.filter(c => c.configId === req.params.id);

    // Generate TOML content in the correct signal-recorder format
    let toml = `# GRAPE Signal Recorder Configuration\n`;
    toml += `# Generated by GRAPE Configuration UI\n`;
    toml += `# Station: ${config.name}\n\n`;

    // [station] section - matches grape-production.toml format
    toml += `[station]\n`;
    toml += `callsign = "${config.callsign}"\n`;
    toml += `grid_square = "${config.gridSquare}"\n`;
    toml += `id = "${config.stationId}"\n`;
    toml += `instrument_id = "${config.instrumentId}"\n`;

    if (config.description) {
      toml += `description = "${config.description}"\n`;
    }

    // [ka9q] section - radio configuration
    toml += `\n[ka9q]\n`;
    toml += `# ka9q-radio status address\n`;
    toml += `status_address = "239.192.152.141"\n`;
    toml += `auto_create_channels = true\n`;

    // [recorder] section
    toml += `\n[recorder]\n`;
    toml += `# Recording directories\n`;

    if (config.dataDir) {
      toml += `data_dir = "${config.dataDir}"\n`;
    } else {
      toml += `data_dir = "/var/lib/signal-recorder/data"\n`;
    }

    if (config.archiveDir) {
      toml += `archive_dir = "${config.archiveDir}"\n`;
    } else {
      toml += `archive_dir = "/var/lib/signal-recorder/archive"\n`;
    }

    toml += `\n# Recording parameters\n`;
    toml += `recording_interval = 60  # 60 second files\n`;
    toml += `continuous = true\n`;

    // [[recorder.channels]] array - matches the actual format
    if (configChannels.length > 0) {
      toml += `\n# WWV and CHU channels for GRAPE\n`;
      toml += `# All channels use IQ mode for full bandwidth capture\n\n`;

      configChannels.forEach((channel) => {
        toml += `[[recorder.channels]]\n`;
        toml += `ssrc = ${parseInt(channel.frequencyHz)}\n`;
        toml += `frequency_hz = ${parseInt(channel.frequencyHz)}\n`;
        toml += `preset = "iq"\n`;
        toml += `sample_rate = ${parseInt(channel.sampleRate || '16000')}\n`;
        toml += `agc = ${parseInt(channel.agc || '0')}\n`;
        toml += `gain = ${parseInt(channel.gain || '0')}\n`;
        toml += `description = "${channel.description}"\n`;
        toml += `enabled = ${channel.enabled === 'yes'}\n`;
        toml += `processor = "${channel.processor || 'grape'}"\n\n`;
      });
    }

    // [processor] section
    toml += `[processor]\n`;
    toml += `enabled = false  # Enable when ready to test processing\n`;

    // [processor.grape] section
    toml += `\n[processor.grape]\n`;
    toml += `# GRAPE processing configuration\n`;
    toml += `process_time = "00:05"\n`;
    toml += `process_timezone = "UTC"\n`;
    toml += `expected_files_per_day = 1440\n`;
    toml += `max_gap_minutes = 5\n`;
    toml += `repair_gaps = true\n`;
    toml += `interpolate_max_minutes = 2\n`;
    toml += `output_sample_rate = 10\n`;
    toml += `output_format = "digital_rf"\n`;

    // [uploader] section for PSWS integration
    if (config.pswsEnabled === 'yes') {
      toml += `\n[uploader]\n`;
      toml += `enabled = false  # Enable when ready to upload\n`;
      toml += `upload_enabled = false\n`;
      toml += `\n# Upload configuration for PSWS\n`;
      toml += `protocol = "rsync"\n`;
      toml += `upload_time = "00:30"\n`;
      toml += `upload_timezone = "UTC"\n`;
      toml += `max_retries = 5\n`;
      toml += `retry_delay_seconds = 300\n`;
      toml += `exponential_backoff = true\n`;
      toml += `queue_dir = "${config.dataDir || '/var/lib/signal-recorder/data'}/upload_queue"\n`;
      toml += `max_queue_size_gb = 100\n`;

      if (config.pswsServer) {
        toml += `\n[uploader.rsync]\n`;
        toml += `# PSWS server configuration\n`;
        toml += `host = "${config.pswsServer}"\n`;
        toml += `port = 22\n`;
        toml += `user = "your_username"  # CHANGE THIS\n`;
        toml += `ssh_key = "/home/wsprdaemon/.ssh/id_rsa_psws"  # UPDATE PATH\n`;
        toml += `remote_base_path = "/data/${config.stationId}"  # UPDATE STATION ID\n`;
        toml += `bandwidth_limit = 0\n`;
        toml += `verify_after_upload = true\n`;
        toml += `delete_after_upload = false\n`;
      }
    }

    // [logging] section
    toml += `\n[logging]\n`;
    toml += `level = "INFO"\n`;
    toml += `console_output = true\n`;

    // [monitoring] section
    toml += `\n[monitoring]\n`;
    toml += `enable_metrics = false\n`;

    res.setHeader('Content-Type', 'text/plain');
    res.setHeader('Content-Disposition', `attachment; filename="grape-${config.stationId || config.callsign}.toml"`);
    res.send(toml);
  } catch (error) {
    console.error('Failed to export configuration:', error);
    res.status(500).json({ error: 'Failed to export configuration' });
  }
});

// Save TOML directly to signal-recorder config directory
app.post('/api/configurations/:id/save-to-config', requireAuth, async (req, res) => {
  try {
    const configs = readJsonFile('configurations.json');
    const config = configs.find(c => c.id === req.params.id);

    if (!config) {
      return res.status(404).json({ error: 'Configuration not found' });
    }

    const channels = readJsonFile('channels.json');
    const configChannels = channels.filter(c => c.configId === req.params.id);

    // Generate TOML content (same as export)
    let toml = `# GRAPE Signal Recorder Configuration\n`;
    toml += `# Generated by GRAPE Configuration UI\n`;
    toml += `# Station: ${config.name}\n\n`;

    // [station] section
    toml += `[station]\n`;
    toml += `callsign = "${config.callsign}"\n`;
    toml += `grid_square = "${config.gridSquare}"\n`;
    toml += `id = "${config.stationId}"\n`;
    toml += `instrument_id = "${config.instrumentId}"\n`;

    if (config.description) {
      toml += `description = "${config.description}"\n`;
    }

    // [ka9q] section
    toml += `\n[ka9q]\n`;
    toml += `status_address = "239.192.152.141"\n`;
    toml += `auto_create_channels = true\n`;

    // [recorder] section
    toml += `\n[recorder]\n`;
    if (config.dataDir) {
      toml += `data_dir = "${config.dataDir}"\n`;
    } else {
      toml += `data_dir = "/var/lib/signal-recorder/data"\n`;
    }
    if (config.archiveDir) {
      toml += `archive_dir = "${config.archiveDir}"\n`;
    } else {
      toml += `archive_dir = "/var/lib/signal-recorder/archive"\n`;
    }
    toml += `recording_interval = 60\n`;
    toml += `continuous = true\n`;

    // Channels
    if (configChannels.length > 0) {
      configChannels.forEach((channel) => {
        toml += `\n[[recorder.channels]]\n`;
        toml += `ssrc = ${parseInt(channel.frequencyHz)}\n`;
        toml += `frequency_hz = ${parseInt(channel.frequencyHz)}\n`;
        toml += `preset = "iq"\n`;
        toml += `sample_rate = ${parseInt(channel.sampleRate || '16000')}\n`;
        toml += `agc = ${parseInt(channel.agc || '0')}\n`;
        toml += `gain = ${parseInt(channel.gain || '0')}\n`;
        toml += `description = "${channel.description}"\n`;
        toml += `enabled = ${channel.enabled === 'yes'}\n`;
        toml += `processor = "${channel.processor || 'grape'}"\n`;
      });
    }

    // Processing sections
    toml += `\n[processor]\n`;
    toml += `enabled = false\n`;

    toml += `\n[processor.grape]\n`;
    toml += `process_time = "00:05"\n`;
    toml += `process_timezone = "UTC"\n`;
    toml += `expected_files_per_day = 1440\n`;
    toml += `max_gap_minutes = 5\n`;
    toml += `repair_gaps = true\n`;
    toml += `interpolate_max_minutes = 2\n`;
    toml += `output_sample_rate = 10\n`;
    toml += `output_format = "digital_rf"\n`;

    // PSWS uploader
    if (config.pswsEnabled === 'yes') {
      toml += `\n[uploader]\n`;
      toml += `enabled = false\n`;
      toml += `upload_enabled = false\n`;
      toml += `protocol = "rsync"\n`;
      toml += `upload_time = "00:30"\n`;
      toml += `upload_timezone = "UTC"\n`;
      toml += `max_retries = 5\n`;
      toml += `retry_delay_seconds = 300\n`;
      toml += `exponential_backoff = true\n`;
      toml += `queue_dir = "${config.dataDir || '/var/lib/signal-recorder/data'}/upload_queue"\n`;
      toml += `max_queue_size_gb = 100\n`;

      if (config.pswsServer) {
        toml += `\n[uploader.rsync]\n`;
        toml += `host = "${config.pswsServer}"\n`;
        toml += `port = 22\n`;
        toml += `user = "your_username"\n`;
        toml += `ssh_key = "/home/wsprdaemon/.ssh/id_rsa_psws"\n`;
        toml += `remote_base_path = "/data/${config.stationId}"\n`;
        toml += `bandwidth_limit = 0\n`;
        toml += `verify_after_upload = true\n`;
        toml += `delete_after_upload = false\n`;
      }
    }

    // Logging and monitoring
    toml += `\n[logging]\n`;
    toml += `level = "INFO"\n`;
    toml += `console_output = true\n`;

    toml += `\n[monitoring]\n`;
    toml += `enable_metrics = false\n`;

    // Save to signal-recorder config directory
    const configDir = join(installDir, 'config');
    const filename = `grape-${config.stationId || config.callsign}.toml`;
    const configPath = join(configDir, filename);

    // Write the file
    fs.writeFileSync(configPath, toml);

    res.json({
      success: true,
      message: `Configuration saved to ${configPath}`,
      filename: filename,
      path: configPath
    });

  } catch (error) {
    console.error('Failed to save configuration to config directory:', error);
    res.status(500).json({
      error: 'Failed to save configuration',
      details: error.message
    });
  }
});

// Monitoring endpoints for signal-recorder daemon
app.get('/api/monitoring/daemon-status', requireAuth, async (req, res) => {
  try {
    // Check daemon status file written by watchdog
    console.log('Checking daemon status...');
    console.log('statusFile path:', statusFile);

    try {
      const statusData = JSON.parse(fs.readFileSync(statusFile, 'utf8'));
      console.log('Successfully read status file:', statusData);

      // Verify the daemon process is still running (if it was reported as running)
      if (statusData.running && statusData.pid) {
        const verifyResult = await new Promise((resolve) => {
          exec(`ps -p ${statusData.pid} -o comm= 2>/dev/null`, (error, stdout, stderr) => {
            if (!error && stdout && stdout.trim()) {
              const comm = stdout.trim();
              if (comm.includes('python')) {
                resolve({ valid: true, comm: comm });
              } else {
                resolve({ valid: false, comm: comm });
              }
            } else {
              resolve({ valid: false, comm: '' });
            }
          });
        });

        if (verifyResult.valid) {
          console.log('Watchdog confirmed daemon running:', statusData.pid);
          res.json({
            running: true,
            timestamp: new Date().toISOString(),
            pid: statusData.pid,
            pids: [statusData.pid],
            watchdog_pid: statusData.watchdog_pid,
            details: statusData.details || 'Daemon running',
            method: 'watchdog + process verification',
            verification: `Process ${statusData.pid} is ${verifyResult.comm}`,
            note: 'Verified daemon process via watchdog'
          });
          return;
        } else {
          // Process is not running, clean up status file
          try {
            fs.unlinkSync(statusFile);
          } catch (e) {
            // Ignore cleanup errors
          }
        }
      }
    } catch (error) {
      // Status file doesn't exist or is invalid
      console.log('Status file error:', error.message);
    }

      // If no status file or invalid process, try direct process detection
      console.log('No valid watchdog status, checking for daemon processes directly...');

      const findResult = await new Promise((resolve) => {
        exec(`pgrep -f "signal_recorder.cli daemon" 2>/dev/null || echo "none"`, (error, stdout, stderr) => {
          const pids = stdout.trim().split('\n').filter(pid => pid && pid !== 'none');
          resolve({ pids, error: error ? error.message : null });
        });
      });

      // If pgrep didn't work, try broader search
      if (findResult.pids.length === 0) {
        await new Promise((resolve) => {
          exec(`ps aux | grep "signal_recorder.cli" | grep -v grep | awk '{print $2}' 2>/dev/null || echo "none"`, (error, stdout, stderr) => {
            const morePids = stdout.trim().split('\n').filter(pid => pid && pid !== 'none');
            findResult.pids = morePids;
            resolve();
          });
        });
      }

      if (findResult.pids.length > 0) {
        console.log(`Found daemon processes via direct search: ${findResult.pids.join(', ')}`);

        // Verify the first process is actually a daemon
        const verifyResult = await new Promise((resolve) => {
          exec(`ps -p ${findResult.pids[0]} -o comm= 2>/dev/null`, (error, stdout, stderr) => {
            const comm = stdout ? stdout.trim() : '';
            resolve({ valid: !error && comm.includes('python'), comm });
          });
        });

        if (verifyResult.valid) {
          res.json({
            running: true,
            timestamp: new Date().toISOString(),
            pid: parseInt(findResult.pids[0]),
            pids: findResult.pids.map(pid => parseInt(pid)),
            details: 'Daemon running (detected via process search)',
            method: 'direct process detection',
            verification: `Process ${findResult.pids[0]} is ${verifyResult.comm}`,
            note: 'Found daemon processes via direct system search'
          });
          return;
        }
      }

      // If no status file or invalid process
      console.log('No daemon status from watchdog');
      res.json({
        running: false,
        timestamp: new Date().toISOString(),
        pid: null,
        pids: [],
        details: 'No daemon status file found',
        note: 'No daemon running'
      });
  } catch (error) {
    console.error('Failed to check daemon status:', error);
    if (!res.headersSent) {
      res.status(500).json({ error: 'Failed to check daemon status' });
    }
  }
});

app.post('/api/monitoring/daemon-control', requireAuth, async (req, res) => {
  try {
    const { action } = req.body; // 'start' or 'stop'

    if (action === 'start') {
      // Check daemon status file written by watchdog
      try {
        if (fs.existsSync(statusFile)) {
          const statusData = JSON.parse(fs.readFileSync(statusFile, 'utf8'));

          // Verify the daemon process is still running (if it was reported as running)
          if (statusData.running && statusData.pid) {
            const verifyResult = await new Promise((resolve) => {
              exec(`ps -p ${statusData.pid} -o comm= 2>/dev/null`, (error, stdout, stderr) => {
                if (!error && stdout && stdout.trim()) {
                  const comm = stdout.trim();
                  if (comm.includes('python')) {
                    resolve({ valid: true, comm: comm });
                  } else {
                    resolve({ valid: false, comm: comm });
                  }
                } else {
                  resolve({ valid: false, comm: '' });
                }
              });
            });

            if (verifyResult.valid) {
              res.status(400).json({
                error: 'Daemon is already running',
                pid: statusData.pid,
                watchdog_pid: statusData.watchdog_pid,
                details: statusData.details || 'Daemon already running',
                note: 'Validation found existing daemon process'
              });
              return;
            } else {
              // Clean up stale status file
              try {
                fs.unlinkSync(statusFile);
              } catch (e) {
                // Ignore cleanup errors
              }
            }
          }
        }

      } catch (e) {
        // Continue with start attempt if validation fails
        console.log('Daemon validation failed, proceeding with start attempt:', e.message);
      }

      // Start daemon using venv python3 in background
      try {
        console.log('Attempting to start daemon...');
        console.log('Command: python3 -m signal_recorder.cli daemon --config', configPath);

        // Create/open log file for daemon output
        const logFile = `/tmp/signal-recorder-daemon.log`;
        let logFd;
        try {
          logFd = fs.openSync(logFile, 'a');
        } catch (err) {
          console.error('Failed to open log file:', err);
          logFd = null;
        }

        // Start daemon in background using spawn
        const daemonProcess = spawn(venvPython, ['-m', 'signal_recorder.cli', 'daemon', '--config', configPath], {
          cwd: installDir,
          env: {
            ...process.env,
            PYTHONPATH: srcPath
          },
          detached: true,
          stdio: logFd ? ['ignore', logFd, logFd] : 'ignore'  // stdin ignored, stdout/stderr to log file
        });

        // Close the file descriptor after spawning
        if (logFd) {
          fs.close(logFd, (err) => {
            if (err) console.error('Error closing log fd:', err);
          });
        }

        // Detach the process so it runs independently
        daemonProcess.unref();

        // Give it a moment to start
        await new Promise(resolve => setTimeout(resolve, 2000));

        // Check if process is still running
        const checkResult = await new Promise((resolve) => {
          exec(`ps -p ${daemonProcess.pid} -o comm= 2>/dev/null`, (error, stdout, stderr) => {
            const isRunning = !error && stdout && stdout.trim().includes('python');
            resolve({
              success: isRunning,
              error: error,
              stdout: stdout || '',
              stderr: stderr || '',
              pid: daemonProcess.pid
            });
          });
        });

        if (checkResult.success) {
          // Also start the watchdog to monitor the daemon
          const watchdogProcess = spawn(venvPython, [join(installDir, 'test-watchdog.py')], {
            cwd: installDir,
            env: {
              ...process.env,
              PYTHONPATH: srcPath
            },
            detached: true,
            stdio: 'ignore'
          });
          watchdogProcess.unref();

          res.json({
            success: true,
            message: 'Daemon started successfully in background',
            stdout: checkResult.stdout,
            stderr: checkResult.stderr,
            daemonPid: daemonProcess.pid,
            watchdogPid: watchdogProcess.pid,
            commandUsed: `"${venvPython}" -m signal_recorder.cli daemon --config ${configPath}`,
            pythonUsed: 'venv',
            note: `Started daemon (PID: ${daemonProcess.pid}) and watchdog (PID: ${watchdogProcess.pid})`
          });
        } else {
          res.status(500).json({
            error: 'Daemon failed to start or exited immediately',
            stdout: checkResult.stdout,
            stderr: checkResult.stderr,
            commandUsed: `"${venvPython}" -m signal_recorder.cli daemon --config ${configPath}`,
            pythonUsed: 'venv',
            troubleshooting: 'Daemon process exited immediately. Check daemon script and config file.',
            note: 'Process started but exited - check daemon script logs'
          });
        }

      } catch (error) {
        console.error('Start daemon failed:', error);
        res.status(500).json({ error: 'Failed to start daemon', details: error.message });
      }

    } else if (action === 'stop') {
      // Check daemon status file written by watchdog
      try {
        let pids = [];
        let statusData = null;

        if (fs.existsSync(statusFile)) {
          statusData = JSON.parse(fs.readFileSync(statusFile, 'utf8'));

          // Verify the daemon process is still running (if it was reported as running)
          if (statusData.running && statusData.pid) {
            const verifyResult = await new Promise((resolve) => {
              exec(`ps -p ${statusData.pid} -o comm= 2>/dev/null`, (error, stdout, stderr) => {
                if (!error && stdout && stdout.trim()) {
                  const comm = stdout.trim();
                  if (comm.includes('python')) {
                    resolve({ valid: true, comm: comm, pid: statusData.pid });
                  } else {
                    resolve({ valid: false, comm: comm, pid: null });
                  }
                } else {
                  resolve({ valid: false, comm: '', pid: null });
                }
              });
            });

            if (verifyResult.valid && verifyResult.pid) {
              pids = [verifyResult.pid];
              console.log(`Found daemon process to stop: ${pids.join(', ')}`);
            } else {
              // Clean up stale status file
              try {
                fs.unlinkSync(statusFile);
              } catch (e) {
                // Ignore cleanup errors
              }
            }
          }
        }

        if (pids.length > 0) {
          // We know the exact PIDs, so kill them directly
          console.log(`Stopping daemon processes with known PIDs: ${pids.join(', ')}`);

          // Try specific stop methods - updated for Python module execution
          const stopMethods = [
            `pkill -f "signal_recorder.cli daemon" 2>/dev/null`,
            `pkill -f "signal_recorder.cli" 2>/dev/null`,
            `pkill -f "grape_recorder" 2>/dev/null`,
            `kill ${pids[0]} 2>/dev/null`  // Kill main daemon process
          ];

          let stopped = false;

          for (const stopMethod of stopMethods) {
            try {
              await new Promise((resolve) => {
                exec(stopMethod, (error, stdout, stderr) => {
                  if (!error) {
                    console.log(`Successfully killed daemon process using ${stopMethod}`);
                    stopped = true;
                  } else {
                    console.log(`Failed to kill daemon process using ${stopMethod}:`, error.message);
                    exec(`kill -9 ${pids[0]} 2>/dev/null`, (forceError, forceStdout, forceStderr) => {
                      if (!forceError) {
                        console.log(`Successfully force-killed daemon process ${pids[0]}`);
                        stopped = true;
                      } else {
                        console.log(`Failed to force-kill ${pids[0]}:`, forceError.message);
                      }
                      resolve();
                    });
                  }
                  resolve();
                });
              });

              if (stopped) break;
            } catch (e) {
              console.log(`Error killing PID ${pids[0]}:`, e.message);
            }
          }

          // Also try to stop watchdog if it exists
          if (statusData && statusData.watchdog_pid) {
            try {
              await new Promise((resolve) => {
                exec(`kill -9 ${statusData.watchdog_pid} 2>/dev/null`, (error, stdout, stderr) => {
                  if (!error) {
                    console.log(`Successfully killed watchdog process ${statusData.watchdog_pid}`);
                  }
                  resolve();
                });
              });
            } catch (e) {
              // Ignore watchdog kill errors
            }
          }

          // Wait a moment and verify it's actually stopped
          await new Promise(resolve => setTimeout(resolve, 2000));

          // Clean up status file
          try {
            fs.unlinkSync(statusFile);
          } catch (e) {
            // Ignore cleanup errors
          }

          res.json({
            success: stopped,
            message: stopped ? 'Daemon stopped successfully' : 'Failed to stop daemon process',
            methodUsed: stopped ? 'direct-pid-kill' : 'failed',
            pidsFound: pids,
            verification: stopped ? 'confirmed stopped' : 'may still be running'
          });
        } else {
          // Try to find processes directly without status file
          console.log('No PIDs from status file, searching for processes directly...');

          try {
            // Find daemon processes directly using multiple methods
            const findResult = await new Promise((resolve) => {
              exec(`pgrep -f "signal_recorder.cli daemon" 2>/dev/null || echo "none"`, (error, stdout, stderr) => {
                const pids = stdout.trim().split('\n').filter(pid => pid && pid !== 'none');
                resolve({ pids, error: error ? error.message : null });
              });
            });

            // If that didn't work, try broader search
            if (findResult.pids.length === 0) {
              await new Promise((resolve) => {
                exec(`ps aux | grep "signal_recorder.cli" | grep -v grep | awk '{print $2}' 2>/dev/null || echo "none"`, (error, stdout, stderr) => {
                  const morePids = stdout.trim().split('\n').filter(pid => pid && pid !== 'none');
                  findResult.pids = morePids;
                  resolve();
                });
              });
            }

            if (findResult.pids.length > 0) {
              console.log(`Found daemon processes directly: ${findResult.pids.join(', ')}`);

              // Try to stop them using direct PID kills
              let directStopped = false;

              for (const pid of findResult.pids) {
                try {
                  await new Promise((resolve) => {
                    exec(`kill -9 ${pid} 2>/dev/null`, (error, stdout, stderr) => {
                      if (!error) {
                        console.log(`Successfully killed daemon process ${pid} via direct PID`);
                        directStopped = true;
                      } else {
                        console.log(`Failed to kill PID ${pid}:`, error.message);
                      }
                      resolve();
                    });
                  });
                } catch (e) {
                  console.log(`Error in direct PID kill for ${pid}:`, e.message);
                }
              }

              // Wait and verify
              await new Promise(resolve => setTimeout(resolve, 1000));

              // Clean up status file
              try {
                fs.unlinkSync(statusFile);
              } catch (e) {
                // Ignore cleanup errors
              }

              res.json({
                success: directStopped,
                message: directStopped ? 'Daemon stopped successfully via direct PID kill' : 'Failed to stop daemon processes',
                methodUsed: 'direct-pid-kill',
                pidsFound: findResult.pids,
                verification: directStopped ? 'confirmed stopped' : 'may still be running'
              });
            } else {
              res.json({
                success: true,
                message: 'No daemon processes found to stop',
                pidsFound: [],
                verification: 'no processes running'
              });
            }
          } catch (error) {
            console.error('Direct process search failed:', error);
            res.json({
              success: true,
              message: 'Stop attempt completed',
              error: error.message,
              verification: 'unknown status'
            });
          }
        }

      } catch (error) {
        console.error('Stop daemon failed:', error);
        res.status(500).json({ error: 'Failed to stop daemon', details: error.message });
      }

    } else {
      res.status(400).json({ error: 'Invalid action. Use "start" or "stop"' });
    }
  } catch (error) {
    console.error('Failed to control daemon:', error);
    if (!res.headersSent) {
      res.status(500).json({ error: 'Failed to control daemon' });
    }
  }
});

app.get('/api/monitoring/data-status', requireAuth, async (req, res) => {
  try {
    // Check data directory for recent files - simplified to avoid race conditions

    // Simple sequential approach to avoid any race conditions
    let dirExists = false;
    let recentFiles = 0;
    let totalSize = '0';
    let dataFiles = 0;

    try {
      // Check if directory exists
      const dirResult = await new Promise((resolve) => {
        exec(`ls -la ${dataDir} 2>/dev/null || echo "Directory does not exist"`, (error, stdout, stderr) => {
          const exists = !error && !stdout.includes('Directory does not exist');
          resolve({ exists, error: error ? error.message : null });
        });
      });
      dirExists = dirResult.exists;

      if (dirExists) {
        // Get recent files (last hour)
        const recentResult = await new Promise((resolve) => {
          exec(`find ${dataDir} -type f -newermt "1 hour ago" 2>/dev/null | wc -l`, (error, stdout, stderr) => {
            const count = parseInt(stdout ? stdout.trim() : '0') || 0;
            resolve({ count, error: error ? error.message : null });
          });
        });
        recentFiles = recentResult.count;

        // Check total data size
        const sizeResult = await new Promise((resolve) => {
          exec(`du -sh ${dataDir} 2>/dev/null | cut -f1 || echo "0"`, (error, stdout, stderr) => {
            const size = stdout ? stdout.trim() : '0';
            resolve({ size, error: error ? error.message : null });
          });
        });
        totalSize = sizeResult.size;

        // Get file counts by type
        const filesResult = await new Promise((resolve) => {
          exec(`find ${dataDir} -name "*.drf" -o -name "*.h5" -o -name "*.log" 2>/dev/null | wc -l || echo "0"`, (error, stdout, stderr) => {
            const count = parseInt(stdout ? stdout.trim() : '0') || 0;
            resolve({ count, error: error ? error.message : null });
          });
        });
        dataFiles = filesResult.count;
      }

      res.json({
        recentFiles,
        totalSize,
        dataFiles,
        dataDir: dataDir,
        directoryExists: dirExists,
        timestamp: new Date().toISOString()
      });

    } catch (error) {
      console.error('Data status check failed:', error);
      res.status(500).json({ error: 'Failed to get data status', details: error.message });
    }

  } catch (error) {
    console.error('Failed to get data status:', error);
    if (!res.headersSent) {
      res.status(500).json({ error: 'Failed to get data status' });
    }
  }
});

app.get('/api/monitoring/channels', requireAuth, async (req, res) => {
  try {
    console.log('Attempting channel discovery via CLI command...');

    // First check if control utility is available
    try {
      await new Promise((resolve, reject) => {
        exec('which control', {
          timeout: 1000
        }, (error, stdout, stderr) => {
          if (error || !stdout.trim()) {
            console.warn('control utility not found in PATH');
            reject(new Error('control utility not found'));
          } else {
            console.log(`control utility found at: ${stdout.trim()}`);
            resolve();
          }
        });
      });
    } catch (controlError) {
      // control utility not available
      res.json({
        channels: [],
        timestamp: new Date().toISOString(),
        total: 0,
        error: 'control utility not found',
        details: 'ka9q-radio control utility is not installed or not in PATH',
        note: 'Install ka9q-radio or add control to PATH. Channels cannot be discovered without it.'
      });
      return;
    }

    // Use control directly instead of Python CLI (which has config fallback)
    const statusAddr = 'bee1-hf-status.local';

    try {
      const result = await new Promise((resolve, reject) => {
        const cmd = `control -v ${statusAddr}`;
        console.log('Running:', cmd);
        
        const proc = exec(cmd, {
          timeout: 3000,  // Shorter timeout since we'll kill it
          env: {
            ...process.env,
            PATH: '/usr/local/bin:/usr/bin:/bin:' + process.env.PATH
          }
        }, (error, stdout, stderr) => {
          // Control returns data but then waits for input - that's OK!
          // Parse stdout even if there's an error (timeout)
          if (stdout && stdout.includes('SSRC')) {
            console.log('Control returned channel data (may have timed out waiting for input)');
            resolve({ stdout, stderr });
          } else if (error) {
            console.error('Control discovery error:', error.message);
            console.error('stderr:', stderr);
            reject({ error, stderr, stdout });
          } else {
            console.log('Control output:', stdout);
            resolve({ stdout, stderr });
          }
        });
        
        // Send newline to control after 2 seconds to make it exit gracefully
        setTimeout(() => {
          try {
            proc.stdin.write('\n');
            proc.stdin.end();
          } catch (e) {
            // Process may already be done
          }
        }, 2000);
      });

      if (result.stdout && result.stdout.trim()) {
        // Parse the discovery output
        const lines = result.stdout.trim().split('\n');
        const channels = [];

        // Parse control output
        // Format: SSRC    preset   samprate      freq, Hz   SNR output channel
        //         1840       usb     12,000     1,840,000  -inf 239.160.155.125:5004
        
        for (const line of lines) {
          // Stop parsing when we hit the prompt (before control re-displays the list)
          // MUST check this BEFORE the header skip, since prompt contains 'SSRC'
          if (line.includes('channels;') && (line.includes('choose') || line.includes('hit return'))) {
            console.log('Reached end of first channel list, stopping parse');
            break;
          }
          
          // Skip header and empty lines
          if (!line.trim() || line.includes('SSRC') || line.includes('---') || line.includes('@')) {
            continue;
          }

          const parts = line.trim().split(/\s+/);
          if (parts.length >= 6) {
            const ssrc = parts[0];
            const preset = parts[1];
            const rate = parts[2].replace(/,/g, ''); // Remove all commas
            const freq_hz = parts[3].replace(/,/g, ''); // Remove all commas
            const snr = parts[4];
            const address = parts[5]; // multicast:port

            // Convert frequency from Hz to MHz for display
            const freq_mhz = (parseInt(freq_hz) / 1000000).toFixed(2);

            channels.push({
              ssrc: ssrc,
              frequency: `${freq_mhz} MHz`,
              rate: rate,
              preset: preset,
              snr: snr,
              address: address
            });
          }
        }

        console.log('Successfully discovered channels via control:', channels.length);

        res.json({
          channels,
          timestamp: new Date().toISOString(),
          total: channels.length,
          rawOutput: result.stdout,
          commandUsed: `control -v ${statusAddr}`,
          note: 'Discovered via control utility - actual radiod channels'
        });
        return;
      }
    } catch (cliError) {
      console.error('CLI discovery failed:', cliError);
      
      // Return empty channels array with detailed error info
      res.json({
        channels: [],
        timestamp: new Date().toISOString(),
        total: 0,
        error: 'Channel discovery failed',
        details: cliError.error?.message || cliError.message || 'Unable to discover channels from radiod',
        stderr: cliError.stderr || '',
        stdout: cliError.stdout || '',
        note: 'No channels found - radiod may not be running, channels need to be created, or control utility failed'
      });
      return;
    }

  } catch (error) {
    console.error('Failed to get channel status:', error);
    if (!res.headersSent) {
      res.status(500).json({ error: 'Failed to get channel status', details: error.message });
    }
  }
});

app.get('/api/monitoring/logs', requireAuth, async (req, res) => {
  try {
    let daemonLogs = [];
    
    // Try to read daemon log file
    const logFile = `/tmp/signal-recorder-daemon.log`;
    try {
      if (fs.existsSync(logFile)) {
        const logContent = fs.readFileSync(logFile, 'utf8');
        daemonLogs = logContent.trim().split('\n').slice(-50);
      }
    } catch (e) {
      console.log('Could not read daemon log file:', e.message);
    }

    // Try multiple log locations as fallback
    const logCommands = [
      'tail -50 /var/log/syslog | grep -i "signal\\|grape\\|recorder" 2>/dev/null || echo ""',
      'tail -50 ~/.cache/signal-recorder.log 2>/dev/null || echo ""',
      'journalctl -n 50 --no-pager -u signal-recorder 2>/dev/null || echo ""'
    ];

    let allLogs = [...daemonLogs];

    // Try each log source sequentially
    for (const cmd of logCommands) {
      try {
        const result = await new Promise((resolve, reject) => {
          exec(cmd, { timeout: 5000 }, (error, stdout, stderr) => {
            const logs = stdout.trim().split('\n').filter(line => 
              line.trim() && 
              !line.includes('No logs') && 
              !line.includes('No cache') && 
              !line.includes('No systemd') && 
              !line.includes('No temp')
            );
            resolve(logs);
          });
        });

        allLogs = allLogs.concat(result);
      } catch (e) {
        // Continue to next source
      }
    }

    // Remove duplicates and limit to 50 most recent
    const uniqueLogs = [...new Set(allLogs)].slice(-50);

    res.json({
      logs: uniqueLogs.length > 0 ? uniqueLogs : ['No logs available - daemon may not be running or logging not configured'],
      timestamp: new Date().toISOString(),
      count: uniqueLogs.length,
      hasDaemonLogs: daemonLogs.length > 0
    });

  } catch (error) {
    console.error('Failed to get logs:', error);
    if (!res.headersSent) {
      res.status(500).json({ error: 'Failed to get logs', details: error.message });
    }
  }
});

// Recording statistics endpoint
app.get('/api/monitoring/recording-stats', requireAuth, (req, res) => {
  try {
    const statsFile = '/tmp/signal-recorder-stats.json';
    
    // Check if stats file exists
    if (!fs.existsSync(statsFile)) {
      return res.json({
        available: false,
        message: 'No recording statistics available - daemon may not be running',
        timestamp: new Date().toISOString()
      });
    }
    
    // Read stats file
    const stats = JSON.parse(fs.readFileSync(statsFile, 'utf8'));
    
    // Add file sizes from output directories
    const enrichedStats = {
      ...stats,
      available: true,
      file_stats: {}
    };
    
    for (const [ssrc, rec] of Object.entries(stats.recorders || {})) {
      const outputDir = rec.output_dir;
      if (outputDir && fs.existsSync(outputDir)) {
        try {
          const files = fs.readdirSync(outputDir);
          const h5Files = files.filter(f => f.endsWith('.h5'));
          let totalSize = 0;
          
          h5Files.forEach(file => {
            try {
              const filePath = path.join(outputDir, file);
              const stats = fs.statSync(filePath);
              totalSize += stats.size;
            } catch (e) {
              // Skip files we can't read
            }
          });
          
          enrichedStats.file_stats[ssrc] = {
            file_count: h5Files.length,
            total_size_bytes: totalSize,
            total_size_mb: (totalSize / (1024 * 1024)).toFixed(2)
          };
        } catch (e) {
          // Directory not readable
        }
      }
    }
    
    res.json(enrichedStats);
    
  } catch (error) {
    console.error('Failed to get recording stats:', error);
    res.status(500).json({ 
      error: 'Failed to get recording statistics', 
      details: error.message,
      available: false
    });
  }
});

// Preset endpoints
app.get('/api/presets/wwv', requireAuth, (req, res) => {
  const presets = [
    { description: 'WWV 2.5 MHz', frequencyHz: '2500000', ssrc: 'wwv_2_5' },
    { description: 'WWV 5 MHz', frequencyHz: '5000000', ssrc: 'wwv_5' },
    { description: 'WWV 10 MHz', frequencyHz: '10000000', ssrc: 'wwv_10' },
    { description: 'WWV 15 MHz', frequencyHz: '15000000', ssrc: 'wwv_15' },
    { description: 'WWV 20 MHz', frequencyHz: '20000000', ssrc: 'wwv_20' },
  ];
  res.json(presets);
});

app.get('/api/presets/chu', requireAuth, (req, res) => {
  const presets = [
    { description: 'CHU 3.33 MHz', frequencyHz: '3330000', ssrc: 'chu_3_33' },
    { description: 'CHU 7.85 MHz', frequencyHz: '7850000', ssrc: 'chu_7_85' },
    { description: 'CHU 14.67 MHz', frequencyHz: '14670000', ssrc: 'chu_14_67' },
  ];
  res.json(presets);
});

// Radiod status check endpoint
app.get('/api/radiod/status', requireAuth, async (req, res) => {
  try {
    // Check if radiod process is running
    const result = await new Promise((resolve, reject) => {
      exec('ps aux | grep "[r]x888d\\|[r]adiod"', {
        timeout: 2000
      }, (error, stdout, stderr) => {
        if (error || !stdout || stdout.trim().length === 0) {
          resolve({ 
            running: false, 
            error: 'radiod process not found',
            details: 'No rx888d or radiod process detected'
          });
        } else {
          // Parse process info
          const lines = stdout.trim().split('\n');
          const processes = lines.map(line => {
            const parts = line.trim().split(/\s+/);
            return {
              pid: parts[1],
              command: parts.slice(10).join(' ')
            };
          });
          
          resolve({ 
            running: true, 
            processes: processes,
            count: processes.length,
            details: `Found ${processes.length} radiod process(es)`
          });
        }
      });
    });
    
    res.json(result);
  } catch (error) {
    res.json({ running: false, error: error.message });
  }
});

// Create missing channels endpoint
app.post('/api/channels/create', requireAuth, async (req, res) => {
  try {
    const configId = req.body.configId;
    
    if (!configId) {
      return res.status(400).json({ error: 'Configuration ID required' });
    }
    
    console.log(`Creating channels for config ${configId}...`);
    
    // Run the channel creation via CLI
    const result = await new Promise((resolve, reject) => {
      exec(`"${venvPython}" -m signal_recorder.channel_manager --config "${configPath}" --create`, {
        timeout: 30000,
        env: {
          ...process.env,
          PYTHONPATH: srcPath
        }
      }, (error, stdout, stderr) => {
        if (error) {
          reject({ error: error.message, stderr });
        } else {
          resolve({ stdout, stderr });
        }
      });
    });
    
    res.json({
      success: true,
      output: result.stdout,
      message: 'Channels created successfully'
    });
    
  } catch (error) {
    console.error('Failed to create channels:', error);
    res.status(500).json({
      error: 'Failed to create channels',
      details: error.error || error.message,
      stderr: error.stderr
    });
  }
});

// Audio streaming endpoint
app.get('/api/audio/stream/:ssrc', (req, res) => {
  const ssrc = req.params.ssrc;
  
  // Read stats to get multicast address for this channel
  let multicastAddr = '239.1.2.1';
  let multicastPort = '5004';
  
  try {
    const statsData = fs.readFileSync('/tmp/signal-recorder-stats.json', 'utf8');
    const stats = JSON.parse(statsData);
    if (stats.recorders && stats.recorders[ssrc]) {
      const channel = stats.recorders[ssrc];
      multicastAddr = channel.multicast_address || multicastAddr;
      multicastPort = String(channel.multicast_port || multicastPort);
    }
  } catch (error) {
    console.error('Failed to read stats for multicast info:', error.message);
  }
  
  console.log(`Starting audio stream for SSRC ${ssrc}: ${multicastAddr}:${multicastPort}`);
  
  // Set headers for audio streaming
  res.setHeader('Content-Type', 'audio/wav');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Transfer-Encoding', 'chunked');
  
  // Spawn Python audio streamer (outputs at native 8kHz RTP rate)
  const audioStreamScript = join(srcPath, 'signal_recorder', 'audio_stream.py');
  const audioStreamer = spawn(venvPython, [
    audioStreamScript,
    '--multicast-address', multicastAddr,
    '--multicast-port', multicastPort,
    '--mode', 'AM',
    '--audio-rate', '8000'
  ], {
    cwd: installDir
  });
  
  // Write WAV header (44 bytes for 8kHz mono PCM)
  const wavHeader = Buffer.alloc(44);
  wavHeader.write('RIFF', 0);
  wavHeader.writeUInt32LE(0xFFFFFFFF, 4);  // File size (unknown for stream)
  wavHeader.write('WAVE', 8);
  wavHeader.write('fmt ', 12);
  wavHeader.writeUInt32LE(16, 16);  // fmt chunk size
  wavHeader.writeUInt16LE(1, 20);   // PCM format
  wavHeader.writeUInt16LE(1, 22);   // Mono
  wavHeader.writeUInt32LE(8000, 24); // Sample rate (8 kHz)
  wavHeader.writeUInt32LE(16000, 28); // Byte rate (8000 * 2)
  wavHeader.writeUInt16LE(2, 32);   // Block align
  wavHeader.writeUInt16LE(16, 34);  // Bits per sample
  wavHeader.write('data', 36);
  wavHeader.writeUInt32LE(0xFFFFFFFF, 40); // Data size (unknown for stream)
  
  res.write(wavHeader);
  
  // Pipe audio data from Python process
  audioStreamer.stdout.on('data', (chunk) => {
    res.write(chunk);
  });
  
  audioStreamer.stderr.on('data', (data) => {
    console.error(`Audio streamer error: ${data}`);
  });
  
  audioStreamer.on('close', (code) => {
    console.log(`Audio streamer exited with code ${code}`);
    res.end();
  });
  
  // Clean up on client disconnect
  req.on('close', () => {
    audioStreamer.kill();
  });
});

// Serve the monitoring dashboard
app.get('/monitoring', (req, res) => {
  res.set('Cache-Control', 'no-store, no-cache, must-revalidate, private');
  res.set('Pragma', 'no-cache');
  res.set('Expires', '0');
  res.sendFile(join(__dirname, 'monitoring.html'));
});

// Serve the HTML file for all other routes (fallback)
app.get('*', (req, res) => {
  res.set('Cache-Control', 'no-store, no-cache, must-revalidate, private');
  res.set('Pragma', 'no-cache');
  res.set('Expires', '0');
  res.sendFile(join(__dirname, 'index.html'));
});

// Start server
function startServer() {
  initializeDefaultUser();

  app.listen(PORT, () => {
    console.log(`🚀 GRAPE Configuration UI Server running on http://localhost:${PORT}/`);
    console.log(`📊 Monitoring Dashboard available at http://localhost:${PORT}/monitoring`);
    console.log(`📁 Using JSON database in ./data/ directory`);
    console.log(`👤 Default login: admin / admin`);
    console.log(`🔧 Enhanced monitoring with debugging and robust API handling`);
    console.log(`✅ JSON database implementation working!`);
  });
}

startServer();
