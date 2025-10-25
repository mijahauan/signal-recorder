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
    // Check if daemon is running by looking for process
    const { exec } = await import('child_process');

    // Try multiple ways to find the daemon process
    const checkCommands = [
      'pgrep -f "signal-recorder daemon"',
      'pgrep -f "python.*signal-recorder.*daemon"',
      'ps aux | grep -i "signal-recorder daemon" | grep -v grep',
      'ps aux | grep -i "python.*signal-recorder.*daemon" | grep -v grep'
    ];

    let runningInfo = { running: false, pid: null, pids: [], details: '' };

    for (const cmd of checkCommands) {
      try {
        const result = await new Promise((resolve) => {
          exec(cmd, (error, stdout, stderr) => {
            if (!error && stdout.trim()) {
              const pids = stdout.trim().split('\n').filter(pid => pid.trim());
              resolve({ running: true, pids: pids, details: `Found via: ${cmd}` });
            } else {
              resolve({ running: false, details: `Not found via: ${cmd}` });
            }
          });
        });

        if (result.running) {
          runningInfo = {
            running: true,
            pid: result.pids[0],
            pids: result.pids,
            details: result.details
          };
          break;
        }
      } catch (e) {
        // Continue to next check method
      }
    }

    res.json({
      running: runningInfo.running,
      timestamp: new Date().toISOString(),
      pid: runningInfo.pid,
      pids: runningInfo.pids,
      details: runningInfo.details
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
      // Check if already running first
      const { exec } = await import('child_process');

      try {
        const statusResult = await new Promise((resolve) => {
          exec('pgrep -f "signal-recorder daemon"', (error, stdout, stderr) => {
            resolve({ error, stdout: stdout ? stdout.trim() : '' });
          });
        });

        if (!statusResult.error && statusResult.stdout) {
          res.status(400).json({ error: 'Daemon is already running', pid: statusResult.stdout.split('\n')[0] });
          return;
        }
      } catch (e) {
        // Continue with start attempt
      }

      // Try to start daemon using possible command paths
      const configPath = 'config/grape-S000171.toml';
      const possibleCommands = [
        'signal-recorder daemon --config ' + configPath,
        '/usr/local/bin/signal-recorder daemon --config ' + configPath,
        process.env.HOME + '/.local/bin/signal-recorder daemon --config ' + configPath,
        process.env.HOME + '/.cargo/bin/signal-recorder daemon --config ' + configPath,
        process.env.HOME + '/git/signal-recorder/target/debug/signal-recorder daemon --config ' + configPath,
        process.env.HOME + '/git/signal-recorder/target/release/signal-recorder daemon --config ' + configPath
      ];

      let startResult = { success: false, error: null, commandUsed: '', stdout: '', stderr: '' };

      for (const cmd of possibleCommands) {
        try {
          startResult = await new Promise((resolve) => {
            exec(cmd, { detached: true, timeout: 10000 }, (error, stdout, stderr) => {
              resolve({
                success: !error,
                error: error,
                commandUsed: cmd,
                stdout: stdout || '',
                stderr: stderr || ''
              });
            });
          });

          if (startResult.success) {
            break;
          }
        } catch (e) {
          startResult = { success: false, error: e, commandUsed: cmd, stdout: '', stderr: '' };
        }
      }

      if (startResult.success) {
        res.json({
          success: true,
          message: 'Daemon start command sent',
          commandUsed: startResult.commandUsed,
          stdout: startResult.stdout,
          stderr: startResult.stderr
        });
      } else {
        res.status(500).json({
          error: `Failed to start daemon: ${startResult.error ? startResult.error.message : 'Unknown error'}`,
          commandUsed: startResult.commandUsed,
          stdout: startResult.stdout,
          stderr: startResult.stderr
        });
      }

    } else if (action === 'stop') {
      // Stop daemon using multiple methods
      const { exec } = await import('child_process');

      const stopMethods = [
        'pkill -f "signal-recorder daemon"',
        'pkill -f "python.*signal-recorder.*daemon"',
        'killall signal-recorder',
        'killall -9 signal-recorder'
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
              }
              resolve();
            });
          });

          if (stopped) break;
        } catch (e) {
          // Continue to next method
        }
      }

      res.json({
        success: stopped,
        message: stopped ? 'Daemon stop command sent' : 'Failed to stop daemon - may not be running',
        methodUsed: methodUsed || 'none'
      });

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
    // Check data directory for recent files
    const { exec } = await import('child_process');
    const dataDir = '/home/mjh/grape-data';

    // Run all checks in parallel using Promise.allSettled to avoid race conditions
    const [dirCheck, recentFilesCheck, sizeCheck, dataFilesCheck] = await Promise.allSettled([
      // Check if directory exists
      new Promise((resolve) => {
        exec(`ls -la ${dataDir} 2>/dev/null || echo "Directory does not exist"`, (error, stdout, stderr) => {
          const dirExists = !error && !stdout.includes('Directory does not exist');
          resolve({ dirExists, error: error ? error.message : null });
        });
      }),

      // Get recent files (last hour)
      new Promise((resolve) => {
        exec(`find ${dataDir} -type f -newermt "1 hour ago" 2>/dev/null | wc -l`, (error, stdout, stderr) => {
          const recentFiles = parseInt(stdout ? stdout.trim() : '0') || 0;
          resolve({ recentFiles, error: error ? error.message : null });
        });
      }),

      // Check total data size
      new Promise((resolve) => {
        exec(`du -sh ${dataDir} 2>/dev/null | cut -f1 || echo "0"`, (error, stdout, stderr) => {
          const totalSize = stdout ? stdout.trim() : '0';
          resolve({ totalSize, error: error ? error.message : null });
        });
      }),

      // Get file counts by type
      new Promise((resolve) => {
        exec(`find ${dataDir} -name "*.drf" -o -name "*.h5" -o -name "*.log" 2>/dev/null | wc -l || echo "0"`, (error, stdout, stderr) => {
          const dataFiles = parseInt(stdout ? stdout.trim() : '0') || 0;
          resolve({ dataFiles, error: error ? error.message : null });
        });
      })
    ]);

    const dirInfo = dirCheck.status === 'fulfilled' ? dirCheck.value : { dirExists: false, error: 'Check failed' };
    const recentInfo = recentFilesCheck.status === 'fulfilled' ? recentFilesCheck.value : { recentFiles: 0, error: 'Check failed' };
    const sizeInfo = sizeCheck.status === 'fulfilled' ? sizeCheck.value : { totalSize: '0', error: 'Check failed' };
    const filesInfo = dataFilesCheck.status === 'fulfilled' ? dataFilesCheck.value : { dataFiles: 0, error: 'Check failed' };

    res.json({
      recentFiles: recentInfo.recentFiles,
      totalSize: sizeInfo.totalSize,
      dataFiles: filesInfo.dataFiles,
      dataDir: dataDir,
      directoryExists: dirInfo.dirExists,
      timestamp: new Date().toISOString(),
      errors: [
        dirInfo.error,
        recentInfo.error,
        sizeInfo.error,
        filesInfo.error
      ].filter(e => e && e !== 'Check failed')
    });

  } catch (error) {
    console.error('Failed to get data status:', error);
    if (!res.headersSent) {
      res.status(500).json({ error: 'Failed to get data status' });
    }
  }
});

app.get('/api/monitoring/channels', requireAuth, async (req, res) => {
  try {
    // Discover current channel status from radiod
    const { exec } = await import('child_process');

    // Try to find signal-recorder in PATH first, then fallback to common locations
    const statusAddr = 'bee1-hf-status.local';
    const possibleCommands = [
      'signal-recorder discover --radiod ' + statusAddr,
      '/usr/local/bin/signal-recorder discover --radiod ' + statusAddr,
      '/home/mjh/.local/bin/signal-recorder discover --radiod ' + statusAddr,
      process.env.HOME + '/.cargo/bin/signal-recorder discover --radiod ' + statusAddr,
      process.env.HOME + '/git/signal-recorder/target/debug/signal-recorder discover --radiod ' + statusAddr,
      process.env.HOME + '/git/signal-recorder/target/release/signal-recorder discover --radiod ' + statusAddr
    ];

    let commandUsed = '';
    let stdout = '';
    let stderr = '';
    let commandError = null;

    // Try each command until one works
    for (const cmd of possibleCommands) {
      try {
        const result = await new Promise((resolve, reject) => {
          exec(cmd, { timeout: 10000 }, (error, stdout, stderr) => {
            if (error) {
              reject(error);
            } else {
              resolve({ stdout, stderr });
            }
          });
        });
        stdout = result.stdout;
        stderr = result.stderr;
        commandUsed = cmd;
        break;
      } catch (e) {
        commandError = e;
        continue;
      }
    }

    console.log('Channel discovery stdout:', stdout);
    console.log('Channel discovery stderr:', stderr);
    console.log('Channel discovery error:', commandError);
    console.log('Command used:', commandUsed);

    if (!stdout || stdout.trim() === '') {
      res.status(500).json({
        error: 'No channels discovered or command failed',
        commandUsed: commandUsed,
        stdout: stdout,
        stderr: stderr,
        errorDetails: commandError ? commandError.message : 'Empty output'
      });
      return;
    }

    // Parse the discovery output
    const lines = stdout.trim().split('\n');
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

    console.log('Parsed channels:', channels);

    res.json({
      channels,
      timestamp: new Date().toISOString(),
      total: channels.length,
      rawOutput: stdout,
      commandUsed: commandUsed
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
    // Get recent log entries from multiple possible locations
    const { exec } = await import('child_process');

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
