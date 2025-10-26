import express from 'express';
import { promises as fs } from 'fs';
import { join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = join(fileURLToPath(import.meta.url), '..');

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(express.json({ limit: '50mb' }));
app.use(express.urlencoded({ limit: '50mb', extended: true }));

// JSON database functions
async function readJsonFile(filename) {
  try {
    const filePath = join(__dirname, 'data', filename);
    const data = await fs.readFile(filePath, 'utf8');
    return JSON.parse(data);
  } catch (error) {
    return [];
  }
}

async function writeJsonFile(filename, data) {
  try {
    const filePath = join(__dirname, 'data', filename);
    await fs.mkdir(join(__dirname, 'data'), { recursive: true });
    await fs.writeFile(filePath, JSON.stringify(data, null, 2));
  } catch (error) {
    console.error(`Failed to write ${filename}:`, error);
    throw error;
  }
}

// Initialize default user
async function initializeDefaultUser() {
  try {
    const users = await readJsonFile('users.json');
    if (users.length === 0) {
      await writeJsonFile('users.json', [{
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
    const configs = await readJsonFile('configurations.json');
    res.json(configs);
  } catch (error) {
    console.error('Failed to read configurations:', error);
    res.status(500).json({ error: 'Failed to read configurations' });
  }
});

app.get('/api/configurations/:id', requireAuth, async (req, res) => {
  try {
    const configs = await readJsonFile('configurations.json');
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
    const configs = await readJsonFile('configurations.json');
    const newConfig = {
      id: Date.now().toString(),
      userId: req.user.id,
      ...req.body,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    configs.push(newConfig);
    await writeJsonFile('configurations.json', configs);
    res.json(newConfig);
  } catch (error) {
    console.error('Failed to create configuration:', error);
    res.status(500).json({ error: 'Failed to create configuration' });
  }
});

app.put('/api/configurations/:id', requireAuth, async (req, res) => {
  try {
    const configs = await readJsonFile('configurations.json');
    const index = configs.findIndex(c => c.id === req.params.id);

    if (index === -1) {
      return res.status(404).json({ error: 'Configuration not found' });
    }

    configs[index] = {
      ...configs[index],
      ...req.body,
      updatedAt: new Date().toISOString()
    };

    await writeJsonFile('configurations.json', configs);
    res.json(configs[index]);
  } catch (error) {
    console.error('Failed to update configuration:', error);
    res.status(500).json({ error: 'Failed to update configuration' });
  }
});

app.delete('/api/configurations/:id', requireAuth, async (req, res) => {
  try {
    let configs = await readJsonFile('configurations.json');
    let channels = await readJsonFile('channels.json');

    // Remove configuration
    configs = configs.filter(c => c.id !== req.params.id);

    // Remove associated channels
    channels = channels.filter(c => c.configId !== req.params.id);

    await writeJsonFile('configurations.json', configs);
    await writeJsonFile('channels.json', channels);

    res.json({ success: true });
  } catch (error) {
    console.error('Failed to delete configuration:', error);
    res.status(500).json({ error: 'Failed to delete configuration' });
  }
});

// Channel routes
app.get('/api/configurations/:configId/channels', requireAuth, async (req, res) => {
  try {
    const channels = await readJsonFile('channels.json');
    const configChannels = channels.filter(c => c.configId === req.params.configId);
    res.json(configChannels);
  } catch (error) {
    console.error('Failed to read channels:', error);
    res.status(500).json({ error: 'Failed to read channels' });
  }
});

app.post('/api/configurations/:configId/channels', requireAuth, async (req, res) => {
  try {
    const channels = await readJsonFile('channels.json');
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
    await writeJsonFile('channels.json', channels);
    res.json(newChannel);
  } catch (error) {
    console.error('Failed to create channel:', error);
    res.status(500).json({ error: 'Failed to create channel' });
  }
});

app.put('/api/channels/:id', requireAuth, async (req, res) => {
  try {
    const channels = await readJsonFile('channels.json');
    const index = channels.findIndex(c => c.id === req.params.id);

    if (index === -1) {
      return res.status(404).json({ error: 'Channel not found' });
    }

    channels[index] = { ...channels[index], ...req.body };
    await writeJsonFile('channels.json', channels);
    res.json(channels[index]);
  } catch (error) {
    console.error('Failed to update channel:', error);
    res.status(500).json({ error: 'Failed to update channel' });
  }
});

app.delete('/api/channels/:id', requireAuth, async (req, res) => {
  try {
    let channels = await readJsonFile('channels.json');
    channels = channels.filter(c => c.id !== req.params.id);
    await writeJsonFile('channels.json', channels);
    res.json({ success: true });
  } catch (error) {
    console.error('Failed to delete channel:', error);
    res.status(500).json({ error: 'Failed to delete channel' });
  }
});

// TOML export and save endpoint
app.get('/api/configurations/:id/export', requireAuth, async (req, res) => {
  try {
    const configs = await readJsonFile('configurations.json');
    const config = configs.find(c => c.id === req.params.id);

    if (!config) {
      return res.status(404).json({ error: 'Configuration not found' });
    }

    const channels = await readJsonFile('channels.json');
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
    toml += `status_address = "239.251.200.193"\n`;
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
        toml += `sample_rate = ${parseInt(channel.sampleRate || '12000')}\n`;
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
    const configs = await readJsonFile('configurations.json');
    const config = configs.find(c => c.id === req.params.id);

    if (!config) {
      return res.status(404).json({ error: 'Configuration not found' });
    }

    const channels = await readJsonFile('channels.json');
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
    toml += `status_address = "239.251.200.193"\n`;
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
        toml += `sample_rate = ${parseInt(channel.sampleRate || '12000')}\n`;
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
    const configDir = join(__dirname, '..', 'config');
    const filename = `grape-${config.stationId || config.callsign}.toml`;
    const configPath = join(configDir, filename);

    // Write the file
    await fs.writeFile(configPath, toml);

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
    // Check if daemon is running - ultra-specific approach to avoid false positives
    const { exec } = await import('child_process');
    const path = await import('path');
    const venvPath = path.default.join(__dirname, '..', 'venv', 'bin', 'signal-recorder');

    try {
      // Very specific detection patterns that ONLY match actual signal-recorder daemon processes
      const checkCommands = [
        // 1. Look for signal-recorder daemon process (exclude our own server)
        `pgrep -f "signal-recorder daemon" 2>/dev/null | grep -v "^${process.pid}$"`,
        // 2. Look for python processes running signal-recorder daemon (exclude our server)
        `pgrep -f "python.*signal-recorder.*daemon" 2>/dev/null | grep -v "^${process.pid}$"`,
        // 3. Check venv path specifically
        `pgrep -f "${venvPath}.*daemon" 2>/dev/null | grep -v "^${process.pid}$"`,
        // 4. Check module execution
        `pgrep -f "python.*-m signal_recorder.cli.*daemon" 2>/dev/null | grep -v "^${process.pid}$"`,
        // 5. Check test daemon script
        `pgrep -f "python.*test-daemon.py" 2>/dev/null | grep -v "^${process.pid}$"`,
        // 6. Check ps output with very specific patterns (exclude node processes)
        'ps aux | grep -E "[s]ignal-recorder daemon|[p]ython.*[s]ignal-recorder.*daemon" | grep -v "node.*simple-server" | grep -v grep 2>/dev/null',
        // 7. Check detailed process info (exclude our server PID)
        'ps -o pid,comm,args | grep -E "[s]ignal-recorder daemon|[p]ython.*[s]ignal-recorder.*daemon" | grep -v "node.*simple-server" | grep -v grep 2>/dev/null'
      ];

      for (const cmd of checkCommands) {
        const result = await new Promise((resolve) => {
          exec(cmd, (error, stdout, stderr) => {
            if (!error && stdout && stdout.trim()) {
              const lines = stdout.trim().split('\n');
              const validPids = [];

              for (const line of lines) {
                const parts = line.trim().split(/\s+/);
                if (parts.length > 0) {
                  const pid = parts[0];
                  if (pid && /^\d+$/.test(pid) && pid !== process.pid.toString()) {
                    // Additional verification: check if this PID is actually a signal-recorder process
                    try {
                      const verifyCmd = `ps -p ${pid} -o comm=`;
                      exec(verifyCmd, (err, verifyStdout) => {
                        if (!err && verifyStdout) {
                          const comm = verifyStdout.trim();
                          // Only accept if it's actually a signal-recorder related process
                          if (comm.includes('signal-recorder') || comm.includes('python') || comm.includes('signal_recorder')) {
                            validPids.push(pid);
                          }
                        }
                      });
                    } catch (e) {
                      // Continue checking
                    }
                  }
                }
              }

              if (validPids.length > 0) {
                resolve({
                  running: true,
                  pid: validPids[0],
                  pids: validPids,
                  details: `Found via: ${cmd}`,
                  method: cmd,
                  stdout: stdout.trim()
                });
              } else {
                resolve({
                  running: false,
                  details: `No valid signal-recorder processes found via: ${cmd}`,
                  method: cmd
                });
              }
            } else {
              resolve({
                running: false,
                details: `No matches via: ${cmd}`,
                method: cmd
              });
            }
          });
        });

        if (result.running) {
          console.log('Daemon detection found VALID process:', result);
          res.json({
            running: true,
            timestamp: new Date().toISOString(),
            pid: result.pid,
            pids: result.pids,
            details: result.details,
            method: result.method,
            verification: result.stdout,
            note: 'Verified signal-recorder daemon process'
          });
          return;
        }
      }

      // If no methods found the daemon
      console.log('No VALID daemon processes found via any detection method');
      res.json({
        running: false,
        timestamp: new Date().toISOString(),
        pid: null,
        pids: [],
        details: 'No valid signal-recorder daemon processes found',
        note: 'Excluded web server and IDE processes'
      });

    } catch (error) {
      console.error('Daemon status check failed:', error);
      res.status(500).json({ error: 'Failed to check daemon status', details: error.message });
    }

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
      // Check if already running using comprehensive detection (same as status API)
      const { exec } = await import('child_process');

      try {
        // Very specific detection patterns that ONLY match actual signal-recorder daemon processes
        const checkCommands = [
          // 1. Look for signal-recorder daemon process (exclude our own server)
          `pgrep -f "signal-recorder daemon" 2>/dev/null | grep -v "^${process.pid}$"`,
          // 2. Look for python processes running signal-recorder daemon (exclude our server)
          `pgrep -f "python.*signal-recorder.*daemon" 2>/dev/null | grep -v "^${process.pid}$"`,
          // 3. Check venv path specifically
          `pgrep -f "${venvPath}.*daemon" 2>/dev/null | grep -v "^${process.pid}$"`,
          // 4. Check module execution
          `pgrep -f "python.*-m signal_recorder.cli.*daemon" 2>/dev/null | grep -v "^${process.pid}$"`,
          // 5. Check test daemon script
          `pgrep -f "python.*test-daemon.py" 2>/dev/null | grep -v "^${process.pid}$"`,
          // 6. Check ps output with very specific patterns (exclude node processes)
          'ps aux | grep -E "[s]ignal-recorder daemon|[p]ython.*[s]ignal-recorder.*daemon" | grep -v "node.*simple-server" | grep -v grep 2>/dev/null',
          // 7. Check detailed process info (exclude our server PID)
          'ps -o pid,comm,args | grep -E "[s]ignal-recorder daemon|[p]ython.*[s]ignal-recorder.*daemon" | grep -v "node.*simple-server" | grep -v grep 2>/dev/null'
        ];

        for (const cmd of checkCommands) {
          const result = await new Promise((resolve) => {
            exec(cmd, (error, stdout, stderr) => {
              if (!error && stdout && stdout.trim()) {
                const lines = stdout.trim().split('\n');
                const validPids = [];

                for (const line of lines) {
                  const parts = line.trim().split(/\s+/);
                  if (parts.length > 0) {
                    const pid = parts[0];
                    if (pid && /^\d+$/.test(pid) && pid !== process.pid.toString()) {
                      validPids.push(pid);
                    }
                  }
                }

                if (validPids.length > 0) {
                  resolve({
                    running: true,
                    pid: validPids[0],
                    pids: validPids,
                    details: `Found via: ${cmd}`,
                    method: cmd,
                    stdout: stdout.trim()
                  });
                } else {
                  resolve({
                    running: false,
                    details: `No matches via: ${cmd}`,
                    method: cmd
                  });
                }
              } else {
                resolve({
                  running: false,
                  details: `No matches via: ${cmd}`,
                  method: cmd
                });
              }
            });
          });

          if (result.running) {
            console.log('Start validation found existing daemon:', result);
            res.status(400).json({
              error: 'Daemon is already running',
              pid: result.pid,
              pids: result.pids,
              details: result.details,
              method: result.method,
              verification: result.stdout,
              note: 'Validation found existing daemon process'
            });
            return;
          }
        }

        // If no methods found the daemon, proceed with start
        console.log('No existing daemon found via any detection method');

      } catch (e) {
        // Continue with start attempt if validation fails
        console.log('Daemon validation failed, proceeding with start attempt:', e.message);
      }

      // Try to start daemon using dynamic path resolution
      const path = await import('path');
      const venvPython = path.default.join(__dirname, '..', 'venv', 'bin', 'python');
      const daemonScript = path.default.join(__dirname, '..', 'test-daemon.py');
      const configPath = path.default.join(__dirname, '..', 'config', 'grape-S000171.toml');

      try {
        console.log('Attempting to start daemon...');
        const startResult = await new Promise((resolve) => {
          exec(`${venvPython} ${daemonScript} --config ${configPath}`, {
            timeout: 10000,
            env: {
              ...process.env,
              PYTHONPATH: path.default.join(__dirname, '..', 'src')
            }
          }, (error, stdout, stderr) => {
            console.log('Daemon exec result:', {
              error: error ? error.message : null,
              stdout: stdout || '',
              stderr: stderr || '',
              success: !error
            });
            resolve({
              success: !error,
              error: error,
              stdout: stdout || '',
              stderr: stderr || ''
            });
          });
        });

        if (startResult.success) {
          res.json({
            success: true,
            message: 'Daemon start command sent',
            stdout: startResult.stdout,
            stderr: startResult.stderr,
            commandUsed: `${venvPython} ${daemonScript} --config ${configPath}`
          });
        } else {
          res.status(500).json({
            error: `Failed to start daemon: ${startResult.error ? startResult.error.message : 'Unknown error'}`,
            stdout: startResult.stdout,
            stderr: startResult.stderr,
            commandUsed: `${venvPython} ${daemonScript} --config ${configPath}`,
            note: 'Using simple test daemon for web UI testing'
          });
        }

      } catch (error) {
        console.error('Start daemon failed:', error);
        res.status(500).json({ error: 'Failed to start daemon', details: error.message });
      }

    } else if (action === 'stop') {
      // Stop daemon using multiple specific methods
      const { exec } = await import('child_process');
      const path = await import('path');
      const venvPath = path.default.join(__dirname, '..', 'venv', 'bin', 'signal-recorder');

      try {
        // First verify there's actually a daemon running (excluding our server)
        const statusResult = await new Promise((resolve) => {
          exec(`pgrep -f "signal-recorder daemon" 2>/dev/null | grep -v "^${process.pid}$"`, (error, stdout, stderr) => {
            resolve({ error, stdout: stdout ? stdout.trim() : '' });
          });
        });

        if (!statusResult.error && statusResult.stdout) {
          const pids = statusResult.stdout.split('\n').filter(pid => pid.trim());

          if (pids.length > 0) {
            console.log(`Found daemon processes to stop: ${pids.join(', ')}`);

            // Try specific stop methods
            const stopMethods = [
              `pkill -f "signal-recorder daemon" 2>/dev/null`,
              `pkill -f "${venvPath}.*daemon" 2>/dev/null`,
              `pkill -f "python.*-m signal_recorder.cli.*daemon" 2>/dev/null`,
              `pkill -f "python.*test-daemon.py" 2>/dev/null`,
              `kill ${pids[0]} 2>/dev/null`,
              `pkill -f "python.*signal-recorder.*daemon" 2>/dev/null`
            ];

            let stopped = false;
            let methodUsed = '';

            for (const cmd of stopMethods) {
              try {
                await new Promise((resolve) => {
                  exec(cmd, (error, stdout, stderr) => {
                    if (!error) {
                      stopped = true;
                      methodUsed = cmd;
                      console.log(`Successfully stopped daemon via: ${cmd}`);
                    }
                    resolve();
                  });
                });

                if (stopped) break;
              } catch (e) {
                // Continue to next method
              }
            }

            // Wait a moment and verify it's actually stopped
            await new Promise(resolve => setTimeout(resolve, 1000));

            const verifyResult = await new Promise((resolve) => {
              exec(`pgrep -f "signal-recorder daemon" 2>/dev/null | grep -v "^${process.pid}$"`, (error, stdout, stderr) => {
                resolve({ error, stdout: stdout ? stdout.trim() : '' });
              });
            });

            const actuallyStopped = !verifyResult.stdout || verifyResult.stdout.trim() === '';

            res.json({
              success: stopped,
              message: actuallyStopped ? 'Daemon stopped successfully' : 'Stop command sent but daemon may still be running',
              methodUsed: methodUsed || 'none',
              pidsFound: pids,
              verification: actuallyStopped ? 'confirmed stopped' : 'may still be running'
            });
          } else {
            res.json({
              success: true,
              message: 'No daemon processes found to stop',
              pidsFound: [],
              verification: 'no processes running'
            });
          }
        } else {
          res.json({
            success: true,
            message: 'No daemon processes found to stop',
            verification: 'already stopped'
          });
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
    const { exec } = await import('child_process');
    const path = await import('path');
    const dataDir = path.default.join(__dirname, '..', 'test-data', 'raw');

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
    console.log('Attempting channel discovery via configuration file...');

    try {
      const fs = await import('fs');
      const path = await import('path');
      const { parse: parseToml } = await import('toml');

      const configPath = path.default.join(__dirname, '..', 'config', 'grape-S000171.toml');
      const configContent = await fs.default.promises.readFile(configPath, 'utf8');
      const config = parseToml(configContent);

      if (config.recorder && config.recorder.channels) {
        const channels = config.recorder.channels.map(channel => ({
          ssrc: channel.ssrc.toString(),
          frequency: `${(channel.frequency_hz / 1000000).toFixed(2)} MHz`,
          rate: channel.sample_rate.toString(),
          preset: channel.preset,
          snr: 'N/A (config)',
          address: config.ka9q?.status_address || '239.251.200.193'
        }));

        console.log('Successfully loaded channels from config:', channels.length);

        res.json({
          channels,
          timestamp: new Date().toISOString(),
          total: channels.length,
          rawOutput: 'Using configuration file fallback',
          commandUsed: 'config-fallback',
          note: 'Loaded from configuration file - CLI discovery not available'
        });
        return;
      }
    } catch (configError) {
      console.error('Config fallback failed:', configError);
    }

    // If config fallback fails, try CLI discovery as last resort
    console.log('Config fallback failed, trying CLI discovery...');

    const { exec } = await import('child_process');
    const statusAddr = 'bee1-hf-status.local';
    const venvPython = path.default.join(__dirname, '..', 'venv', 'bin', 'python');
    const discoverScript = path.default.join(__dirname, '..', 'test-discover.py');

    try {
      const result = await new Promise((resolve, reject) => {
        exec(`${venvPython} ${discoverScript} --radiod ${statusAddr}`, {
          timeout: 10000,
          env: {
            ...process.env,
            PYTHONPATH: path.default.join(__dirname, '..', 'src')
          }
        }, (error, stdout, stderr) => {
          if (error) {
            reject(error);
          } else {
            resolve({ stdout, stderr });
          }
        });
      });

      if (result.stdout && result.stdout.trim()) {
        // Parse the discovery output
        const lines = result.stdout.trim().split('\n');
        const channels = [];

        // Skip header lines and parse data lines
        for (let i = 2; i < lines.length; i++) {
          const line = lines[i];
          if (!line.trim()) continue;

          const parts = line.trim().split(/\s+/);
          if (parts.length >= 6) {
            channels.push({
              ssrc: parts[0],
              frequency: parts[1] + ' ' + parts[2],
              rate: parts[3],
              preset: parts[4],
              snr: parts[5],
              address: parts.slice(6).join(' ')
            });
          }
        }

        console.log('Successfully discovered channels via CLI:', channels.length);

        res.json({
          channels,
          timestamp: new Date().toISOString(),
          total: channels.length,
          rawOutput: result.stdout,
          commandUsed: `${venvPython} ${discoverScript} --radiod ${statusAddr}`,
          note: 'Discovered via CLI command'
        });
        return;
      }
    } catch (cliError) {
      console.error('CLI discovery also failed:', cliError);
    }

    // If both methods fail, return error
    res.status(500).json({
      error: 'No channels discovered',
      note: 'Both CLI discovery and configuration fallback failed',
      configError: 'Configuration file fallback failed',
      cliError: 'CLI discovery failed - signal-recorder command not found'
    });

  } catch (error) {
    console.error('Failed to get channel status:', error);
    if (!res.headersSent) {
      res.status(500).json({ error: 'Failed to get channel status', details: error.message });
    }
  }
});

app.get('/api/monitoring/logs', requireAuth, async (req, res) => {
  try {

    // Try multiple log locations and search patterns
    const logCommands = [
      'tail -50 /var/log/syslog | grep -i "signal\\|grape\\|recorder" 2>/dev/null || echo "No logs in syslog"',
      'tail -50 ~/.cache/signal-recorder.log 2>/dev/null || echo "No cache logs"',
      'journalctl -n 50 --no-pager -u signal-recorder 2>/dev/null || echo "No systemd logs"',
      'tail -50 /tmp/signal-recorder*.log 2>/dev/null || echo "No temp logs"'
    ];

    let allLogs = [];
    let completedCommands = 0;

    // Try each log source sequentially to avoid race conditions
    for (const cmd of logCommands) {
      try {
        const result = await new Promise((resolve, reject) => {
          exec(cmd, { timeout: 5000 }, (error, stdout, stderr) => {
            const logs = stdout.trim().split('\n').filter(line => line.trim() && !line.includes('No logs') && !line.includes('No cache') && !line.includes('No systemd') && !line.includes('No temp'));
            resolve(logs);
          });
        });

        allLogs = allLogs.concat(result);
        completedCommands++;

        // If we have logs, we can stop here
        if (allLogs.length > 0) {
          break;
        }
      } catch (e) {
        completedCommands++;
      }
    }

    // Wait a bit for all commands to complete, then respond
    await new Promise(resolve => setTimeout(resolve, 1000));

    // Remove duplicates and limit to 50 most recent
    const uniqueLogs = [...new Set(allLogs)].slice(-50);

    res.json({
      logs: uniqueLogs.length > 0 ? uniqueLogs : ['No recent logs found in any location'],
      timestamp: new Date().toISOString(),
      count: uniqueLogs.length,
      sources: logCommands.length
    });

  } catch (error) {
    console.error('Failed to get logs:', error);
    if (!res.headersSent) {
      res.status(500).json({ error: 'Failed to get logs', details: error.message });
    }
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

// Serve the monitoring dashboard
app.get('/monitoring', (req, res) => {
  res.sendFile(join(__dirname, 'monitoring.html'));
});

// Serve the HTML file for all other routes (fallback)
app.get('*', (req, res) => {
  res.sendFile(join(__dirname, 'index.html'));
});

// Start server
async function startServer() {
  await initializeDefaultUser();

  app.listen(PORT, () => {
    console.log(`🚀 GRAPE Configuration UI Server running on http://localhost:${PORT}/`);
    console.log(`📊 Monitoring Dashboard available at http://localhost:${PORT}/monitoring`);
    console.log(`📁 Using JSON database in ./data/ directory`);
    console.log(`👤 Default login: admin / admin`);
    console.log(`🔧 Enhanced monitoring with debugging and robust API handling`);
    console.log(`✅ JSON database implementation working!`);
  });
}

startServer().catch(console.error);
