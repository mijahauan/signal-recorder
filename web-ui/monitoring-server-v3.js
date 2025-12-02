#!/usr/bin/env node
/**
 * GRAPE Signal Recorder - Monitoring Server V3
 * 
 * 3-Screen Monitoring Interface:
 * 1. Summary - System status, channel status, station info
 * 2. Carrier - 10 Hz decimated analysis (9 channels, all 16 kHz → 10 Hz)
 * 3. Discrimination - WWV/WWVH propagation analysis (shared frequency channels)
 * 
 * Architecture:
 * - Uses centralized GRAPEPaths API for all file access
 * - RESTful API with individual + aggregated endpoints
 * - All channels now 16 kHz wide channels with WWV/CHU tone detection
 * - No authentication (monitoring only)
 * - No configuration editing (use TOML files directly)
 */

import express from 'express';
import cors from 'cors';
import fs from 'fs';
import { join, basename, dirname } from 'path';
import { parse as csvParse } from 'csv-parse/sync';
import { fileURLToPath } from 'url';
import toml from 'toml';
import { exec, execSync } from 'child_process';
import { promisify } from 'util';
import dgram from 'dgram';
import { EventEmitter } from 'events';
import { WebSocketServer } from 'ws';
import { GRAPEPaths, channelNameToKey } from './grape-paths.js';
import {
  getPrimaryTimeReference,
  getTimingHealthSummary,
  getTimingMetrics,
  getTimingTransitions,
  getTimingTimeline
} from './utils/timing-analysis-helpers.js';

const execAsync = promisify(exec);
const __dirname = dirname(fileURLToPath(import.meta.url));

// ============================================================================
// INITIALIZATION
// ============================================================================

const app = express();
const PORT = 3000;
const serverStartTime = Date.now();

// Determine install directory
const installDir = process.env.GRAPE_INSTALL_DIR || join(__dirname, '..');
const configPath = process.env.GRAPE_CONFIG || join(installDir, 'config/grape-config.toml');

// Load configuration
let config = {};
let dataRoot = join(process.env.HOME, 'grape-data'); // Fallback
let mode = 'test';
let paths = null;

try {
  const configContent = fs.readFileSync(configPath, 'utf8');
  config = toml.parse(configContent);
  
  // Determine data_root based on mode
  mode = config.recorder?.mode || 'test';
  if (mode === 'production') {
    dataRoot = config.recorder?.production_data_root || '/var/lib/signal-recorder';
  } else {
    dataRoot = config.recorder?.test_data_root || '/tmp/grape-test';
  }
  
  // Initialize paths API
  paths = new GRAPEPaths(dataRoot);
  
  console.log('📊 GRAPE Monitoring Server V3');
  console.log('📁 Config file:', configPath);
  console.log(mode === 'production' ? '🚀 Mode: PRODUCTION' : '🧪 Mode: TEST');
  console.log('📁 Data root:', dataRoot);
  console.log('📡 Station:', config.station?.callsign, config.station?.grid_square);
  console.log('🔧 Instrument ID:', config.station?.instrument_id || 'not configured');
} catch (err) {
  console.error('⚠️  Failed to load config, using defaults:', err.message);
  console.log('📊 GRAPE Monitoring Server V3 (fallback mode)');
  console.log('📁 Data root:', dataRoot);
  paths = new GRAPEPaths(dataRoot);
}

// ============================================================================
// AUDIO STREAMING CONFIGURATION
// ============================================================================

// Get radiod hostname from config (ka9q section)
const RADIOD_HOSTNAME = config.ka9q?.status_address || process.env.RADIOD_HOSTNAME || 'localhost';
const KA9Q_AUDIO_PORT = 5004;
const MULTICAST_INTERFACE = process.env.KA9Q_MULTICAST_INTERFACE || null;
const RADIOD_AUDIO_MULTICAST = config.ka9q?.data_address || process.env.RADIOD_AUDIO_MULTICAST || null;

// Python configuration - use venv if available
const VENV_PYTHON = join(__dirname, '..', 'venv', 'bin', 'python3');
const PYTHON_CMD = fs.existsSync(VENV_PYTHON) ? VENV_PYTHON : 'python3';
const AUDIO_CLIENT_SCRIPT = join(__dirname, 'radiod_audio_client.py');

// Audio SSRC offset - added to IQ SSRC to create audio channel SSRC
const AUDIO_SSRC_OFFSET = 999;

/**
 * Calculate audio SSRC from frequency
 * Audio SSRC = frequency_hz + 999 (e.g., 10 MHz -> 10000999)
 */
function getAudioSSRC(frequencyHz) {
  return Math.floor(frequencyHz) + AUDIO_SSRC_OFFSET;
}

/**
 * Get frequency from channel name
 * Examples: "WWV 10 MHz" -> 10000000, "CHU 3.33 MHz" -> 3330000
 */
function channelNameToFrequency(channelName) {
  const match = channelName.match(/(\d+\.?\d*)\s*MHz/i);
  if (match) {
    return parseFloat(match[1]) * 1000000;
  }
  return null;
}

/**
 * Ka9q-Radio Audio Proxy
 * Handles RTP stream reception and WebSocket forwarding for audio playback
 */
class Ka9qRadioProxy extends EventEmitter {
  constructor() {
    super();
    this.audioSocket = null;
    this.activeStreams = new Map();
    this.joinedMulticastGroups = new Set();
    this.loggedRtp = new Set();
    this.loggedOrphanRtp = new Set();
    
    this.init();
  }

  init() {
    console.log(`🔊 Audio Proxy initialized`);
    console.log(`   Radiod: ${RADIOD_HOSTNAME}`);
    console.log(`   Interface: ${MULTICAST_INTERFACE || 'default'}`);
    this.setupAudioSocket();
  }
  
  setupAudioSocket() {
    // Create audio socket for RTP reception with large buffer
    this.audioSocket = dgram.createSocket({ type: 'udp4', reuseAddr: true });
    
    this.audioSocket.on('listening', () => {
      this.audioSocket.setMulticastLoopback(true);
      
      if (MULTICAST_INTERFACE) {
        try {
          this.audioSocket.setMulticastInterface(MULTICAST_INTERFACE);
        } catch (err) {
          console.warn(`⚠️  Could not set multicast interface ${MULTICAST_INTERFACE}: ${err.message}`);
        }
      }
      
      // Increase socket buffer
      try {
        const requestedSize = 4 * 1024 * 1024; // 4MB
        this.audioSocket.setRecvBufferSize(requestedSize);
        const actualSize = this.audioSocket.getRecvBufferSize();
        console.log(`✅ Audio socket buffer: ${actualSize} bytes`);
      } catch (err) {
        console.warn(`⚠️  Could not set socket buffer size: ${err.message}`);
      }
      
      this.setupAudioReception();
    });
    
    this.audioSocket.on('error', (err) => {
      console.error('❌ Audio socket error:', err);
    });
    
    // Bind to receive multicast traffic
    this.audioSocket.bind(KA9Q_AUDIO_PORT, '0.0.0.0');
  }

  setupAudioReception() {
    this.audioSocket.on('message', (msg, rinfo) => {
      if (msg.length < 12) return; // Minimum RTP header size

      // Extract SSRC from RTP header
      const ssrc = msg.readUInt32BE(8);
      
      // Check if we care about this SSRC
      const session = global.audioSessions ? global.audioSessions.get(ssrc) : null;
      if (!session) {
        // Log first packet from unknown SSRC, then ignore
        if (!this.loggedOrphanRtp.has(ssrc)) {
          // Only log if it looks like an audio SSRC (ends in 999)
          if (ssrc % 1000 === AUDIO_SSRC_OFFSET) {
            console.log(`📭 Audio RTP for SSRC ${ssrc} but no WebSocket session active`);
          }
          this.loggedOrphanRtp.add(ssrc);
        }
        return;
      }
      
      // Log first packet for active SSRCs
      if (!this.loggedRtp.has(ssrc)) {
        console.log(`🔊 RTP packet for SSRC ${ssrc} from ${rinfo.address}:${rinfo.port}`);
        this.loggedRtp.add(ssrc);
      }

      // Forward to WebSocket client
      if (session && session.audio_active && session.ws.readyState === 1) {
        try {
          // Parse RTP header
          const byte0 = msg.readUInt8(0);
          const csrcCount = byte0 & 0x0F;
          const extension = (byte0 >> 4) & 0x01;
          
          // Calculate payload offset
          let payloadOffset = 12 + (csrcCount * 4);
          
          // Skip extension header if present
          if (extension && msg.length >= payloadOffset + 4) {
            const extLengthWords = msg.readUInt16BE(payloadOffset + 2);
            payloadOffset += 4 + (extLengthWords * 4);
          }
          
          if (payloadOffset >= msg.length) return;
          
          // Extract PCM payload and byte-swap for browser
          const pcmPayload = Buffer.from(msg.slice(payloadOffset));
          for (let i = 0; i < pcmPayload.length; i += 2) {
            const tmp = pcmPayload[i];
            pcmPayload[i] = pcmPayload[i + 1];
            pcmPayload[i + 1] = tmp;
          }
          
          // Send to browser
          session.ws.send(pcmPayload);
        } catch (err) {
          console.error(`❌ Error processing RTP for SSRC ${ssrc}:`, err.message);
        }
      }
    });
  }

  async startAudioStream(frequencyHz) {
    const ssrc = getAudioSSRC(frequencyHz);
    const freqMHz = frequencyHz / 1000000;
    
    console.log(`🎵 Starting audio stream: ${freqMHz} MHz (SSRC ${ssrc})`);
    
    // Use Python client to create/get audio channel
    const interfaceArg = MULTICAST_INTERFACE ? `--interface ${MULTICAST_INTERFACE}` : '';
    const fallbackArg = RADIOD_AUDIO_MULTICAST ? `--fallback-multicast ${RADIOD_AUDIO_MULTICAST}` : '';
    const cmd = `${PYTHON_CMD} -u ${AUDIO_CLIENT_SCRIPT} --radiod-host ${RADIOD_HOSTNAME} ${interfaceArg} ${fallbackArg} get-or-create --frequency ${frequencyHz}`;
    
    try {
      const { stdout, stderr } = await execAsync(cmd, { timeout: 30000 });
      
      if (stderr) {
        console.log(`   [Python]: ${stderr}`);
      }
      
      const result = JSON.parse(stdout.trim());
      
      if (!result.success) {
        console.error(`❌ Audio stream request failed: ${result.error}`);
        throw new Error(result.error);
      }
      
      console.log(`✅ Audio channel ready: SSRC ${result.ssrc} (${result.mode})`);
      
      const stream = {
        ssrc: result.ssrc,
        active: true,
        frequency: result.frequency_hz,
        multicastAddress: result.multicast_address,
        multicastPort: result.port,
        sampleRate: result.sample_rate
      };
      
      this.activeStreams.set(ssrc, stream);
      
      // Join multicast group
      if (result.multicast_address && !this.joinedMulticastGroups.has(result.multicast_address)) {
        try {
          this.audioSocket.addMembership(result.multicast_address, MULTICAST_INTERFACE || '0.0.0.0');
          this.joinedMulticastGroups.add(result.multicast_address);
          console.log(`✅ Joined audio multicast: ${result.multicast_address}:${result.port}`);
        } catch (err) {
          console.warn(`⚠️  Could not join audio group: ${err.message}`);
        }
      }
      
      return stream;
    } catch (error) {
      console.error(`❌ Failed to start audio stream:`, error.message);
      throw error;
    }
  }
  
  async stopAudioStream(ssrc) {
    const stream = this.activeStreams.get(ssrc);
    if (stream) {
      stream.active = false;
      this.activeStreams.delete(ssrc);
      
      // Calculate frequency from SSRC
      const frequencyHz = ssrc - AUDIO_SSRC_OFFSET;
      
      // Use Python client to stop channel
      const cmd = `${PYTHON_CMD} -u ${AUDIO_CLIENT_SCRIPT} --radiod-host ${RADIOD_HOSTNAME} stop --frequency ${frequencyHz}`;
      
      try {
        await execAsync(cmd, { timeout: 5000 });
        console.log(`✅ Audio channel ${ssrc} stopped`);
      } catch (err) {
        console.error(`❌ Error stopping audio channel ${ssrc}:`, err.message);
      }
    }
  }

  shutdown() {
    console.log('🛑 Shutting down audio proxy...');
    
    for (const [ssrc] of this.activeStreams) {
      this.stopAudioStream(ssrc);
    }
    
    if (this.audioSocket) {
      this.audioSocket.close();
    }
  }
}

// Create audio proxy instance
const audioProxy = new Ka9qRadioProxy();

// Audio session management (global for access from RTP handler)
global.audioSessions = new Map();

// Middleware
app.use(express.json());
app.use(express.static(__dirname)); // Serve static files

// CORS for local development
app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Headers', 'Content-Type');
  next();
});

// ============================================================================
// HELPER FUNCTIONS - DATA ACCESS
// ============================================================================

/**
 * Convert seconds to human-readable uptime
 */
function formatUptime(seconds) {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  
  const parts = [];
  if (days > 0) parts.push(`${days}d`);
  if (hours > 0) parts.push(`${hours}h`);
  if (minutes > 0) parts.push(`${minutes}m`);
  
  return parts.join(' ') || '0m';
}

/**
 * Get station info from configuration
 */
function getStationInfo() {
  return {
    id: config.station?.id || 'not configured',  // PSWS Station ID
    callsign: config.station?.callsign || 'UNKNOWN',
    grid_square: config.station?.grid_square || 'UNKNOWN',
    receiver: config.station?.receiver_name || 'GRAPE',
    instrument_id: config.station?.instrument_id || 'not configured',
    mode: mode,
    data_root: dataRoot
  };
}

/**
 * Get radiod status from dedicated health monitor
 */
async function getRadiodStatus(paths) {
  try {
    const radiodStatusFile = join(paths.getStateDir(), 'radiod-status.json');
    
    if (!fs.existsSync(radiodStatusFile)) {
      // Fallback: try to detect radiod process directly
      try {
        const result = execSync('pgrep -x radiod', { encoding: 'utf8' }).trim();
        const running = result.length > 0;
        return {
          running,
          method: 'pgrep_fallback',
          uptime_seconds: 0,
          health: running ? 'unknown' : 'critical'
        };
      } catch (e) {
        return {
          running: false,
          method: 'pgrep_fallback_failed',
          health: 'critical'
        };
      }
    }
    
    const content = fs.readFileSync(radiodStatusFile, 'utf8');
    const status = JSON.parse(content);
    
    // Check status age
    const statusTimestamp = new Date(status.timestamp).getTime() / 1000;
    const age = Date.now() / 1000 - statusTimestamp;
    
    return {
      running: status.process?.running || false,
      connected: status.connectivity || false,
      uptime_seconds: status.uptime_seconds || 0,
      health: status.health || 'unknown',
      alerts: status.alerts || [],
      status_age_seconds: Math.round(age),
      method: 'health_monitor'
    };
    
  } catch (err) {
    console.error('Error getting radiod status:', err);
    return {
      running: false,
      error: err.message,
      method: 'error',
      health: 'critical'
    };
  }
}

/**
 * Get core recorder status
 */
async function getCoreRecorderStatus(paths) {
  try {
    const statusFile = paths.getCoreStatusFile();
    
    if (!fs.existsSync(statusFile)) {
      return { 
        running: false, 
        error: 'Status file not found'
      };
    }
    
    const content = fs.readFileSync(statusFile, 'utf8');
    const status = JSON.parse(content);
    
    // Parse ISO 8601 timestamp
    const statusTimestamp = new Date(status.timestamp).getTime() / 1000;
    const age = Date.now() / 1000 - statusTimestamp;
    const running = age < 30;
    
    // Get channel info - handle both old and new status formats
    let channelsActive = 0;
    let channelsTotal = 0;
    let totalPackets = 0;
    let uptime = 0;
    
    if (status.recorders && typeof status.recorders === 'object') {
      // New format: status.recorders = {frequency: {...}}
      const recorders = Object.values(status.recorders);
      channelsActive = recorders.filter(r => r.packets_received > 0).length;
      channelsTotal = status.channels || recorders.length;
      totalPackets = recorders.reduce((sum, r) => sum + (r.packets_received || 0), 0);
      uptime = status.recording_duration_sec || 0;
    } else if (status.channels && typeof status.channels === 'object') {
      // Old format: status.channels = {ssrc: {...}}
      const channels = Object.values(status.channels);
      channelsActive = channels.length;
      channelsTotal = channels.length;
      totalPackets = channels.reduce((sum, ch) => sum + (ch.packets_received || 0), 0);
      uptime = status.uptime_seconds || 0;
    }
    
    return {
      running,
      uptime_seconds: uptime,
      channels_active: channelsActive,
      channels_total: channelsTotal,
      packets_received: totalPackets,
      last_update: status.timestamp,
      age_seconds: age
    };
  } catch (err) {
    return { 
      running: false, 
      error: err.message,
      radiod_running: false
    };
  }
}

/**
 * Get analytics service status (aggregated across all channels)
 */
async function getAnalyticsServiceStatus(paths) {
  try {
    const channels = paths.discoverChannels();
    
    if (channels.length === 0) {
      return { 
        running: false, 
        error: 'No channels found' 
      };
    }
    
    let channelsProcessing = 0;
    let newestTimestamp = 0;
    let oldestUptime = Infinity;
    
    for (const channelName of channels) {
      const statusDir = paths.getAnalyticsStatusDir(channelName);
      const statusFile = join(statusDir, 'analytics-service-status.json');
      
      if (fs.existsSync(statusFile)) {
        try {
          const content = fs.readFileSync(statusFile, 'utf8');
          const status = JSON.parse(content);
          
          // Parse ISO 8601 timestamp
          const statusTimestamp = new Date(status.timestamp).getTime() / 1000;
          const age = Date.now() / 1000 - statusTimestamp;
          
          if (age < 120) { // Consider active if updated within 2 minutes
            channelsProcessing++;
            
            if (statusTimestamp > newestTimestamp) {
              newestTimestamp = statusTimestamp;
            }
            
            // Get uptime from status file
            const uptime = status.uptime_seconds || status.uptime || 0;
            if (uptime > 0 && uptime < oldestUptime) {
              oldestUptime = uptime;
            }
          }
        } catch (err) {
          // Skip channel with invalid status file
        }
      }
    }
    
    const age = newestTimestamp > 0 ? (Date.now() / 1000 - newestTimestamp) : Infinity;
    const running = channelsProcessing > 0 && age < 120;
    
    return {
      running,
      uptime_seconds: oldestUptime < Infinity ? oldestUptime : 0,
      channels_processing: channelsProcessing,
      channels_total: channels.length,
      last_update: newestTimestamp,
      age_seconds: age
    };
  } catch (err) {
    return { 
      running: false, 
      error: err.message 
    };
  }
}

/**
 * Get process statuses
 */
async function getProcessStatuses(paths) {
  const radiodStatus = await getRadiodStatus(paths);
  const coreStatus = await getCoreRecorderStatus(paths);
  const analyticsStatus = await getAnalyticsServiceStatus(paths);
  
  return {
    radiod: radiodStatus,
    core_recorder: {
      running: coreStatus.running,
      uptime_seconds: coreStatus.uptime_seconds,
      channels_active: coreStatus.channels_active,
      channels_total: coreStatus.channels_total,
      packets_received: coreStatus.packets_received,
      last_update: coreStatus.last_update
    },
    analytics_service: {
      running: analyticsStatus.running,
      uptime_seconds: analyticsStatus.uptime_seconds,
      channels_processing: analyticsStatus.channels_processing,
      channels_total: analyticsStatus.channels_total,
      last_update: analyticsStatus.last_update
    }
  };
}

/**
 * Get data continuity info (span and gaps)
 */
async function getDataContinuity(paths) {
  try {
    const channels = paths.discoverChannels();
    
    if (channels.length === 0) {
      const now = Date.now() / 1000;
      const nowISO = new Date(now * 1000).toISOString();
      return {
        data_span: {
          start: nowISO,
          end: nowISO,
          duration_seconds: 0
        },
        available_data: {
          oldest_npz: nowISO,
          newest_npz: nowISO,
          total_duration_seconds: 0
        },
        continuity: {
          uptime_pct: 100,
          capture_seconds: 0,
          downtime_seconds: 0,
          gap_count: 0
        },
        gaps: [],
        gap_events: [], // Alias for compatibility
        total_downtime_seconds: 0,
        downtime_percentage: 0
      };
    }
    
    // Collect all timestamps across all channels
    const channelTimestamps = new Map();
    let globalOldest = Infinity;
    let globalNewest = 0;
    
    for (const channelName of channels) {
      const archiveDir = paths.getArchiveDir(channelName);
      
      if (!fs.existsSync(archiveDir)) continue;
      
      const timestamps = [];
      
      const files = fs.readdirSync(archiveDir)
        .filter(f => f.endsWith('_iq.npz'))
        .sort();
      
      for (const file of files) {
        // Parse timestamp from filename: 20241115T120000Z_freq_iq.npz
        const match = file.match(/^(\d{8})T(\d{6})Z/);
        if (match) {
          const dateStr = match[1]; // YYYYMMDD
          const timeStr = match[2]; // HHMMSS
          
          const year = parseInt(dateStr.substr(0, 4));
          const month = parseInt(dateStr.substr(4, 2)) - 1;
          const day = parseInt(dateStr.substr(6, 2));
          const hour = parseInt(timeStr.substr(0, 2));
          const minute = parseInt(timeStr.substr(2, 2));
          const second = parseInt(timeStr.substr(4, 2));
          
          const date = new Date(Date.UTC(year, month, day, hour, minute, second));
          const unixTime = date.getTime() / 1000;
          
          timestamps.push(unixTime);
          
          if (unixTime < globalOldest) globalOldest = unixTime;
          if (unixTime > globalNewest) globalNewest = unixTime;
        }
      }
      
      channelTimestamps.set(channelName, timestamps.sort((a, b) => a - b));
    }
    
    // Detect system-wide gaps (gaps in ALL channels simultaneously)
    const systemGaps = [];
    
    if (globalOldest < Infinity && globalNewest > 0) {
      // Create union of all timestamps
      const allTimestamps = new Set();
      for (const timestamps of channelTimestamps.values()) {
        timestamps.forEach(ts => allTimestamps.add(ts));
      }
      
      const sortedTimes = Array.from(allTimestamps).sort((a, b) => a - b);
      
      // Find gaps where timestamp jump > 120 seconds (2 minutes)
      for (let i = 1; i < sortedTimes.length; i++) {
        const gap = sortedTimes[i] - sortedTimes[i - 1];
        
        if (gap > 120) {
          // Verify this is a system-wide gap (all channels affected)
          const gapStart = sortedTimes[i - 1] + 60; // End of previous minute
          const gapEnd = sortedTimes[i];
          
          let isSystemGap = true;
          for (const [channelName, timestamps] of channelTimestamps) {
            // Check if this channel has data in the gap period
            const hasDataInGap = timestamps.some(ts => ts > gapStart && ts < gapEnd);
            if (hasDataInGap) {
              isSystemGap = false;
              break;
            }
          }
          
          if (isSystemGap) {
            const gapDuration = gapEnd - gapStart;
            const severity = gapDuration > 3600 ? 'critical' : gapDuration > 300 ? 'warning' : 'info';
            const cause = gapDuration > 3600 ? 'extended_outage' : gapDuration > 300 ? 'service_restart' : 'brief_interruption';
            
            systemGaps.push({
              start: new Date(gapStart * 1000).toISOString(),
              end: new Date(gapEnd * 1000).toISOString(),
              duration_seconds: gapDuration,
              cause: cause,
              severity: severity,
              channels_affected: channels.length // All channels affected in system-wide gap
            });
          }
        }
      }
    }
    
    // Calculate totals
    const totalDowntime = systemGaps.reduce((sum, gap) => sum + gap.duration_seconds, 0);
    const spanDuration = globalNewest - globalOldest;
    const downtimePercentage = spanDuration > 0 ? (totalDowntime / spanDuration) * 100 : 0;
    
    const recentGaps = systemGaps.slice(-5); // Return only 5 most recent gaps
    const uptimeSeconds = spanDuration - totalDowntime;
    const uptimePercentage = spanDuration > 0 ? (uptimeSeconds / spanDuration) * 100 : 100;
    
    return {
      data_span: {
        start: new Date(globalOldest * 1000).toISOString(),
        end: new Date(globalNewest * 1000).toISOString(),
        duration_seconds: spanDuration
      },
      available_data: {
        oldest_npz: new Date(globalOldest * 1000).toISOString(),
        newest_npz: new Date(globalNewest * 1000).toISOString(),
        total_duration_seconds: spanDuration
      },
      continuity: {
        uptime_pct: uptimePercentage,
        capture_seconds: uptimeSeconds,
        downtime_seconds: totalDowntime,
        gap_count: systemGaps.length
      },
      gaps: recentGaps,
      gap_events: recentGaps, // Alias for compatibility
      total_downtime_seconds: totalDowntime,
      downtime_percentage: downtimePercentage
    };
  } catch (err) {
    console.error('Error calculating continuity:', err);
    const now = Date.now() / 1000;
    const nowISO = new Date(now * 1000).toISOString();
    return {
      data_span: {
        start: nowISO,
        end: nowISO,
        duration_seconds: 0
      },
      available_data: {
        oldest_npz: nowISO,
        newest_npz: nowISO,
        total_duration_seconds: 0
      },
      continuity: {
        uptime_pct: 100,
        capture_seconds: 0,
        downtime_seconds: 0,
        gap_count: 0
      },
      gaps: [],
      gap_events: [], // Alias for compatibility
      total_downtime_seconds: 0,
      downtime_percentage: 0,
      error: err.message
    };
  }
}

/**
 * Get storage information
 */
async function getStorageInfo(paths) {
  try {
    // Use df command to get disk usage
    const { stdout } = await execAsync(`df -B1 ${dataRoot} | tail -1`);
    const parts = stdout.trim().split(/\s+/);
    
    const totalBytes = parseInt(parts[1]);
    const usedBytes = parseInt(parts[2]);
    const availableBytes = parseInt(parts[3]);
    const usedPercent = (usedBytes / totalBytes) * 100;
    
    // Estimate write rate (very rough - based on current usage)
    // This would be better calculated from actual archive sizes over time
    const archiveSize = usedBytes; // Simplified - actual would be archive dir only
    const writeRatePerDay = archiveSize / 7; // Assume ~1 week of data (very rough)
    
    const daysUntilFull = availableBytes / writeRatePerDay;
    
    return {
      location: dataRoot,
      used_bytes: usedBytes,
      total_bytes: totalBytes,
      available_bytes: availableBytes,
      used_percent: usedPercent,
      write_rate_bytes_per_day: writeRatePerDay,
      estimated_days_until_full: Math.floor(daysUntilFull)
    };
  } catch (err) {
    return {
      location: dataRoot,
      error: err.message
    };
  }
}

/**
 * Get gap analysis data from 10Hz decimated NPZ files
 * Calculates coverage based on which minutes have files vs missing
 * This matches what the spectrogram shows (black bars = missing files)
 */
async function getGapAnalysis(paths, date, channelFilter = 'all') {
  const analyticsRoot = join(paths.dataRoot, 'analytics');
  
  if (!fs.existsSync(analyticsRoot)) {
    return {
      date, channel_filter: channelFilter, total_gaps: 0,
      total_gap_minutes: 0, completeness_pct: 0, longest_gap_minutes: 0,
      minutes_analyzed: 0, gaps: []
    };
  }
  
  // Build Python script to analyze file coverage from decimated 10Hz files
  const pythonScript = `
import os
import json
from datetime import datetime, timedelta
from collections import defaultdict

analytics_root = '${analyticsRoot}'
date_prefix = '${date}'
channel_filter = '${channelFilter}'.replace('_', ' ')

# Parse target date
year = int(date_prefix[:4])
month = int(date_prefix[4:6])
day = int(date_prefix[6:8])
target_date = datetime(year, month, day)

# Determine how many minutes to analyze (full day or partial if today)
now = datetime.utcnow()
if target_date.date() == now.date():
    # Today - only analyze up to current minute
    total_expected_minutes = now.hour * 60 + now.minute
else:
    # Past day - full 24 hours
    total_expected_minutes = 1440

if total_expected_minutes == 0:
    total_expected_minutes = 1  # Avoid division by zero

# Find all channel decimated directories
channels_to_check = []
for channel_dir in os.listdir(analytics_root):
    channel_path = os.path.join(analytics_root, channel_dir, 'decimated')
    if not os.path.isdir(channel_path):
        continue
    
    channel_name = channel_dir.replace('_', ' ')
    if channel_filter != 'all' and channel_filter != channel_name:
        continue
    
    channels_to_check.append((channel_name, channel_path))

all_gaps = []
total_files_found = 0
total_gap_minutes = 0
longest_gap = 0

for channel_name, decimated_path in channels_to_check:
    # Find all 10Hz NPZ files for this date
    # Filename format: YYYYMMDDTHHMMSSZ_freq_iq_10hz.npz
    minutes_with_data = set()
    
    for fname in os.listdir(decimated_path):
        if not fname.endswith('_iq_10hz.npz') or not fname.startswith(date_prefix):
            continue
        
        # Extract minute from filename: 20251201T153000Z -> minute 930 (15*60 + 30)
        try:
            ts_part = fname.split('_')[0]  # 20251201T153000Z
            if 'T' in ts_part:
                time_str = ts_part.split('T')[1].rstrip('Z')
                hour = int(time_str[0:2])
                minute = int(time_str[2:4])
                minute_of_day = hour * 60 + minute
                minutes_with_data.add(minute_of_day)
                total_files_found += 1
        except:
            pass
    
    # Find gaps (missing minutes)
    missing_minutes = []
    for m in range(total_expected_minutes):
        if m not in minutes_with_data:
            missing_minutes.append(m)
    
    # Consolidate consecutive missing minutes into gap ranges
    if missing_minutes:
        gap_start = missing_minutes[0]
        gap_length = 1
        
        for i in range(1, len(missing_minutes)):
            if missing_minutes[i] == missing_minutes[i-1] + 1:
                gap_length += 1
            else:
                # End current gap, start new one
                if gap_length >= 1:  # Only report gaps >= 1 minute
                    gap_hour = gap_start // 60
                    gap_min = gap_start % 60
                    start_time = f"{date_prefix[:4]}-{date_prefix[4:6]}-{date_prefix[6:8]}T{gap_hour:02d}:{gap_min:02d}:00Z"
                    severity = 'high' if gap_length >= 30 else ('medium' if gap_length >= 5 else 'low')
                    all_gaps.append({
                        'channel': channel_name,
                        'start_time': start_time,
                        'start_minute': gap_start,
                        'duration_minutes': gap_length,
                        'duration_seconds': gap_length * 60,
                        'severity': severity
                    })
                    if gap_length > longest_gap:
                        longest_gap = gap_length
                gap_start = missing_minutes[i]
                gap_length = 1
        
        # Don't forget the last gap
        if gap_length >= 1:
            gap_hour = gap_start // 60
            gap_min = gap_start % 60
            start_time = f"{date_prefix[:4]}-{date_prefix[4:6]}-{date_prefix[6:8]}T{gap_hour:02d}:{gap_min:02d}:00Z"
            severity = 'high' if gap_length >= 30 else ('medium' if gap_length >= 5 else 'low')
            all_gaps.append({
                'channel': channel_name,
                'start_time': start_time,
                'start_minute': gap_start,
                'duration_minutes': gap_length,
                'duration_seconds': gap_length * 60,
                'severity': severity
            })
            if gap_length > longest_gap:
                longest_gap = gap_length
        
        total_gap_minutes += len(missing_minutes)

# Calculate coverage
if channel_filter != 'all':
    completeness = (total_files_found / total_expected_minutes * 100) if total_expected_minutes > 0 else 0
    gap_minutes = total_expected_minutes - total_files_found
else:
    # For 'all', average across channels
    num_channels = len(channels_to_check) if channels_to_check else 1
    completeness = (total_files_found / (total_expected_minutes * num_channels) * 100) if total_expected_minutes > 0 else 0
    gap_minutes = total_gap_minutes / num_channels if num_channels > 0 else 0

result = {
    'date': date_prefix,
    'channel_filter': channel_filter if channel_filter != 'all' else 'all',
    'total_gaps': len(all_gaps),
    'total_gap_minutes': round(gap_minutes, 1),
    'completeness_pct': round(min(completeness, 100), 1),
    'longest_gap_minutes': longest_gap,
    'minutes_analyzed': total_expected_minutes,
    'files_found': total_files_found,
    'gaps': sorted(all_gaps, key=lambda x: x['start_minute'])[:50]  # Chronological, limit to 50
}

print(json.dumps(result))
`;

  try {
    const { stdout } = await execAsync(`python3 -c "${pythonScript.replace(/"/g, '\\"')}"`, { timeout: 30000 });
    return JSON.parse(stdout);
  } catch (err) {
    console.error('Gap analysis error:', err.message);
    return {
      date, channel_filter: channelFilter, total_gaps: 0,
      total_gap_minutes: 0, completeness_pct: 0, longest_gap_minutes: 0,
      minutes_analyzed: 0, gaps: [], error: err.message
    };
  }
}

/**
 * Get RTP-level gap analysis from archive NPZ files
 * These are network packet loss events stored inside NPZ files (zero-filled samples)
 */
async function getRtpGapAnalysis(paths, date, channelFilter = 'all') {
  const archivesRoot = join(paths.dataRoot, 'archives');
  
  if (!fs.existsSync(archivesRoot)) {
    return {
      date, channel_filter: channelFilter, 
      total_files: 0, files_with_gaps: 0, total_gap_events: 0,
      total_samples_filled: 0, total_duration_ms: 0,
      channels: [], error: 'Archives directory not found'
    };
  }
  
  // Use Python to read NPZ gap metadata - write script to temp file to avoid escaping issues
  const tmpScript = `/tmp/rtp_gap_analysis_${Date.now()}.py`;
  const pythonScript = `
import os
import json
import sys
import numpy as np
from pathlib import Path

archives_root = Path(sys.argv[1])
date_prefix = sys.argv[2]
channel_filter = sys.argv[3].replace('_', ' ')

results = {
    'date': date_prefix,
    'channel_filter': channel_filter if channel_filter != 'all' else 'all',
    'total_files': 0,
    'files_with_gaps': 0,
    'total_gap_events': 0,
    'total_samples_filled': 0,
    'total_duration_ms': 0,
    'channels': []
}

for channel_dir in archives_root.iterdir():
    if not channel_dir.is_dir():
        continue
    
    channel_name = channel_dir.name.replace('_', ' ')
    if channel_filter != 'all' and channel_filter != channel_name:
        continue
    
    stats = {
        'channel': channel_name,
        'files_checked': 0,
        'files_with_gaps': 0,
        'total_gap_events': 0,
        'total_samples_filled': 0,
        'total_duration_ms': 0,
        'avg_gap_samples': 0,
        'largest_gap_samples': 0,
        'completeness_pct': 100.0,
        'recent_gaps': []
    }
    
    sample_rate = 16000
    total_samples_expected = 0
    
    for npz_file in sorted(channel_dir.glob(f'{date_prefix}*_iq.npz')):
        try:
            data = np.load(npz_file, allow_pickle=True)
            stats['files_checked'] += 1
            results['total_files'] += 1
            
            if 'sample_rate' in data:
                sample_rate = int(data['sample_rate'])
            if 'segment_sample_count' in data:
                total_samples_expected += int(data['segment_sample_count'])
            
            gaps_count = int(data['gaps_count']) if 'gaps_count' in data else 0
            gaps_filled = int(data['gaps_filled']) if 'gaps_filled' in data else 0
            
            if gaps_count > 0:
                stats['files_with_gaps'] += 1
                results['files_with_gaps'] += 1
                stats['total_gap_events'] += gaps_count
                results['total_gap_events'] += gaps_count
                stats['total_samples_filled'] += gaps_filled
                results['total_samples_filled'] += gaps_filled
                
                duration_ms = (gaps_filled / sample_rate) * 1000
                stats['total_duration_ms'] += duration_ms
                results['total_duration_ms'] += duration_ms
                
                if 'gap_samples_filled' in data:
                    gap_samples = data['gap_samples_filled']
                    if len(gap_samples) > 0:
                        largest = max(int(g) for g in gap_samples)
                        if largest > stats['largest_gap_samples']:
                            stats['largest_gap_samples'] = largest
                        
                        ts_part = npz_file.name.split('_')[0]
                        for i, g in enumerate(gap_samples):
                            sample_idx = 0
                            if 'gap_sample_indices' in data and i < len(data['gap_sample_indices']):
                                sample_idx = int(data['gap_sample_indices'][i])
                            stats['recent_gaps'].append({
                                'file_timestamp': ts_part,
                                'sample_index': sample_idx,
                                'samples_filled': int(g),
                                'duration_ms': round((int(g) / sample_rate) * 1000, 1)
                            })
            data.close()
        except:
            pass
    
    if stats['files_checked'] > 0:
        if stats['total_gap_events'] > 0:
            stats['avg_gap_samples'] = int(stats['total_samples_filled'] / stats['total_gap_events'])
        if total_samples_expected > 0:
            actual = total_samples_expected - stats['total_samples_filled']
            stats['completeness_pct'] = round((actual / total_samples_expected) * 100, 2)
        stats['total_duration_ms'] = round(stats['total_duration_ms'], 1)
        stats['recent_gaps'] = sorted(stats['recent_gaps'], key=lambda x: x['file_timestamp'], reverse=True)[:10]
        results['channels'].append(stats)

results['total_duration_ms'] = round(results['total_duration_ms'], 1)
results['channels'].sort(key=lambda x: x['channel'])
print(json.dumps(results))
`;

  try {
    fs.writeFileSync(tmpScript, pythonScript);
    const { stdout } = await execAsync(`python3 ${tmpScript} "${archivesRoot}" "${date}" "${channelFilter}"`);
    fs.unlinkSync(tmpScript);
    return JSON.parse(stdout.trim());
  } catch (err) {
    console.error('RTP gap analysis error:', err.message);
    return {
      date, channel_filter: channelFilter,
      total_files: 0, files_with_gaps: 0, total_gap_events: 0,
      total_samples_filled: 0, total_duration_ms: 0,
      channels: [], error: err.message
    };
  }
}

/**
 * Check NTP synchronization status
 */
async function getNTPStatus() {
  try {
    const { stdout } = await execAsync('timedatectl status');
    
    const synchronized = stdout.includes('System clock synchronized: yes');
    
    // Try to extract offset (may not always be available)
    let offsetMs = null;
    try {
      const { stdout: ntpqOutput } = await execAsync('ntpq -p 2>/dev/null || chronyc tracking 2>/dev/null');
      // Parse offset from output (implementation depends on ntp vs chrony)
      // This is a simplified version
      const offsetMatch = ntpqOutput.match(/offset\s+([-\d.]+)/);
      if (offsetMatch) {
        offsetMs = parseFloat(offsetMatch[1]);
      }
    } catch (e) {
      // NTP offset not available
    }
    
    return {
      synchronized,
      offset_ms: offsetMs
    };
  } catch (err) {
    return {
      synchronized: false,
      error: err.message
    };
  }
}

/**
 * Get per-channel status
 */
async function getChannelStatuses(paths) {
  try {
    const channels = paths.discoverChannels();
    const ntpStatus = await getNTPStatus();
    const channelStatuses = [];
    
    for (const channelName of channels) {
      // Get RTP status from core recorder
      const coreStatus = await getCoreRecorderStatus(paths);
      const rtpStreaming = coreStatus.running;
      
      // Get analytics status for this channel
      const statusDir = paths.getAnalyticsStatusDir(channelName);
      const statusFile = join(statusDir, 'analytics-service-status.json');
      
      let snrDb = null;
      let timeBasis = 'WALL_CLOCK';
      let timeSnapAge = null;
      
      if (fs.existsSync(statusFile)) {
        try {
          const content = fs.readFileSync(statusFile, 'utf8');
          const status = JSON.parse(content);
          
          // Get channel-specific data
          const channelData = status.channels?.[channelName];
          
          // Get SNR (if available)
          snrDb = channelData?.quality_metrics?.last_snr_db || status.current_snr_db || null;
          
          // Determine time basis
          // Priority: TONE_LOCKED > NTP_SYNCED > WALL_CLOCK
          // Use same logic as timing dashboard for consistency
          if (channelData?.time_snap?.established) {
            const age = Date.now() / 1000 - channelData.time_snap.utc_timestamp;
            timeSnapAge = age;
            
            const source = channelData.time_snap.source || '';
            const isToneSource = source.includes('wwv') || source.includes('chu') || 
                                source === 'wwv_startup' || source === 'chu_startup' || 
                                source === 'wwvh_startup';
            
            if (isToneSource && age < 300) {
              // Fresh tone detection (< 5 minutes) = actively tone-locked
              timeBasis = 'TONE_LOCKED';
            } else if (isToneSource && age < 3600) {
              // Aged tone reference (5 min - 1 hour) = interpolated (still valid but aging)
              timeBasis = 'INTERPOLATED';
            } else if (ntpStatus.synchronized) {
              // Very aged or NTP source
              timeBasis = 'NTP_SYNCED';
            }
            // else: WALL_CLOCK (default)
          } else if (ntpStatus.synchronized) {
            timeBasis = 'NTP_SYNCED';
          }
        } catch (err) {
          // Use defaults
          console.error(`Error reading status for ${channelName}:`, err.message);
        }
      }
      
      channelStatuses.push({
        name: channelName,
        rtp_streaming: rtpStreaming,
        snr_db: snrDb,
        time_basis: timeBasis,
        time_snap_age_seconds: timeSnapAge,
        audio_available: false, // Stub for future audio proxy
        audio_url: null
      });
    }
    
    return {
      channels: channelStatuses,
      timestamp: Date.now() / 1000
    };
  } catch (err) {
    return {
      channels: [],
      timestamp: Date.now() / 1000,
      error: err.message
    };
  }
}

/**
 * Get channel quality metrics for all channels on a specific date
 * All channels are now 16 kHz wide channels with WWV/CHU tone detection
 */
async function getCarrierQuality(paths, date) {
  const channels = paths.discoverChannels();
  const channelQuality = [];
  
  // Check NTP status once for all channels
  const ntpStatus = await getNTPStatus();
  
  // Process each channel (all are 16 kHz wide channels)
  for (const channelName of channels) {
    try {
      const statusFile = paths.getAnalyticsStatusFile(channelName);
      
      // Construct spectrogram URL using unified path structure
      // Format: spectrograms/{date}/{channel}_{date}_decimated_spectrogram.png
      const safe_channel_name = channelName.replace(/ /g, '_');
      const spectrogramFilename = `${safe_channel_name}_${date}_decimated_spectrogram.png`;
      
      let quality = {
        name: channelName,
        channel_type: 'wide',
        sample_rate: '16 kHz',
        source_type: '16 kHz → 10 Hz decimated',
        completeness_pct: null,
        timing_quality: 'WALL_CLOCK',
        time_snap_age_minutes: null,
        snr_db: null,
        packet_loss_pct: null,
        upload_status: 'unknown',
        upload_lag_seconds: null,
        alerts: [],
        spectrogram_url: `/spectrograms/${date}/${spectrogramFilename}`
      };
      
      if (fs.existsSync(statusFile)) {
        const content = fs.readFileSync(statusFile, 'utf8');
        const status = JSON.parse(content);
        
        // Get channel-specific data
        const channelKey = Object.keys(status.channels || {}).find(k => 
          k === channelName || status.channels[k].channel_name === channelName
        );
        const channelData = channelKey ? status.channels[channelKey] : null;
        
        if (channelData) {
          // Completeness
          if (channelData.quality_metrics) {
            quality.completeness_pct = channelData.quality_metrics.last_completeness_pct || null;
            quality.packet_loss_pct = channelData.quality_metrics.last_packet_loss_pct || null;
          }
          
          // Timing quality (consistent with summary page logic)
          // Source values: wwv_startup, chu_startup, wwvh_startup, ntp, wall_clock, archive_time_snap
          if (channelData.time_snap && channelData.time_snap.established) {
            const ageMinutes = (Date.now() / 1000 - channelData.time_snap.utc_timestamp) / 60;
            quality.time_snap_age_minutes = Math.round(ageMinutes);
            
            const source = channelData.time_snap.source || '';
            const sourceLower = source.toLowerCase();
            const isToneSource = sourceLower.includes('wwv') || sourceLower.includes('chu');
            
            if (isToneSource && ageMinutes < 5) {
              // Fresh tone detection (< 5 minutes) = actively tone-locked
              quality.timing_quality = 'TONE_LOCKED';
            } else if (isToneSource && ageMinutes < 60) {
              // Aged tone reference (5-60 min) = interpolated
              quality.timing_quality = 'INTERPOLATED';
            } else if (ntpStatus.synchronized) {
              quality.timing_quality = 'NTP_SYNCED';
            } else {
              quality.timing_quality = 'WALL_CLOCK';
            }
          } else {
            quality.timing_quality = ntpStatus.synchronized ? 'NTP_SYNCED' : 'WALL_CLOCK';
          }
          
          // SNR (if available)
          quality.snr_db = channelData.current_snr_db || null;
          
          // Upload status
          if (channelData.digital_rf && channelData.digital_rf.last_write_time) {
            const lastWrite = new Date(channelData.digital_rf.last_write_time).getTime() / 1000;
            const now = Date.now() / 1000;
            quality.upload_lag_seconds = Math.round(now - lastWrite);
            
            if (quality.upload_lag_seconds < 600) {
              quality.upload_status = 'current';
            } else if (quality.upload_lag_seconds < 3600) {
              quality.upload_status = 'delayed';
            } else {
              quality.upload_status = 'stalled';
            }
          }
          
          // Generate alerts
          if (quality.completeness_pct !== null && quality.completeness_pct < 90) {
            quality.alerts.push({
              severity: 'critical',
              type: 'low_completeness',
              message: `Completeness ${quality.completeness_pct.toFixed(1)}% (critical threshold: 90%)`
            });
          } else if (quality.completeness_pct !== null && quality.completeness_pct < 95) {
            quality.alerts.push({
              severity: 'warning',
              type: 'low_completeness',
              message: `Completeness ${quality.completeness_pct.toFixed(1)}% (warning threshold: 95%)`
            });
          }
          
          if (quality.snr_db !== null && quality.snr_db < 10) {
            quality.alerts.push({
              severity: 'critical',
              type: 'low_snr',
              message: `SNR ${quality.snr_db.toFixed(1)} dB (critical threshold: 10 dB)`
            });
          } else if (quality.snr_db !== null && quality.snr_db < 20) {
            quality.alerts.push({
              severity: 'warning',
              type: 'low_snr',
              message: `SNR ${quality.snr_db.toFixed(1)} dB (warning threshold: 20 dB)`
            });
          }
          
          if (quality.upload_status === 'stalled') {
            quality.alerts.push({
              severity: 'critical',
              type: 'upload_stalled',
              message: `Upload stalled (${Math.round(quality.upload_lag_seconds / 60)} min lag)`
            });
          } else if (quality.upload_status === 'delayed') {
            quality.alerts.push({
              severity: 'warning',
              type: 'upload_delayed',
              message: `Upload delayed (${Math.round(quality.upload_lag_seconds / 60)} min lag)`
            });
          }
          
          if (quality.timing_quality === 'WALL_CLOCK') {
            quality.alerts.push({
              severity: 'warning',
              type: 'wall_clock_timing',
              message: 'Using wall clock timing (reprocessing recommended)'
            });
          }
        }
      }
      
      channelQuality.push(quality);
    } catch (err) {
      console.error(`Error getting quality for ${channelName}:`, err.message);
    }
  }
  
  // Calculate system summary
  const activeChannels = channelQuality.filter(q => q.completeness_pct !== null).length;
  const avgCompleteness = channelQuality.reduce((sum, q) => sum + (q.completeness_pct || 0), 0) / (activeChannels || 1);
  const criticalAlerts = channelQuality.reduce((sum, q) => sum + q.alerts.filter(a => a.severity === 'critical').length, 0);
  const warnings = channelQuality.reduce((sum, q) => sum + q.alerts.filter(a => a.severity === 'warning').length, 0);
  
  let overallStatus = 'good';
  if (criticalAlerts > 0) {
    overallStatus = 'critical';
  } else if (warnings > 2) {
    overallStatus = 'warning';
  }
  
  return {
    date,
    channels: channelQuality,
    system_summary: {
      overall_status: overallStatus,
      channels_active: activeChannels,
      channels_total: channelQuality.length,
      average_completeness: Math.round(avgCompleteness * 10) / 10,
      critical_alerts: criticalAlerts,
      warnings: warnings
    }
  };
}

// ============================================================================
// API ENDPOINTS - SUMMARY SCREEN
// ============================================================================

/**
 * GET /api/v1/station/info
 * Station configuration and metadata
 */
app.get('/api/v1/station/info', (req, res) => {
  try {
    res.json(getStationInfo());
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/v1/system/status
 * Aggregated system status (processes + basic info)
 */
app.get('/api/v1/system/status', async (req, res) => {
  try {
    const processes = await getProcessStatuses(paths);
    const storage = await getStorageInfo(paths);
    const stationInfo = getStationInfo();
    
    // Convert storage to disk format expected by simple-dashboard
    const disk = {
      total_gb: (storage.total_bytes / (1024**3)).toFixed(1),
      used_gb: (storage.used_bytes / (1024**3)).toFixed(1),
      free_gb: ((storage.total_bytes - storage.used_bytes) / (1024**3)).toFixed(1),
      percent_used: storage.used_percent.toFixed(1)
    };
    
    res.json({
      processes,
      services: processes, // Alias for compatibility with simple-dashboard.html
      radiod: processes.radiod, // Top-level alias for simple-dashboard.html
      disk: disk, // Add disk info for simple-dashboard.html
      station: stationInfo,
      data_paths: {
        archive: paths.dataRoot,
        status: paths.getStatusDir(),
        analytics: join(paths.dataRoot, 'analytics')
      },
      timestamp: new Date().toISOString(),
      uptime: process.uptime(),
      server_version: '3.0.0'
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/v1/system/processes
 * Status of radiod, core recorder, analytics service
 */
app.get('/api/v1/system/processes', async (req, res) => {
  try {
    const processes = await getProcessStatuses(paths);
    res.json(processes);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/v1/system/continuity
 * Data span and system-wide gaps
 */
app.get('/api/v1/system/continuity', async (req, res) => {
  try {
    const continuity = await getDataContinuity(paths);
    res.json(continuity);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/v1/system/storage
 * Disk usage and projections
 */
app.get('/api/v1/system/storage', async (req, res) => {
  try {
    const storage = await getStorageInfo(paths);
    res.json(storage);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/v1/gaps?date=YYYYMMDD&channel=all
 * Gap analysis data - reads from NPZ files to find data gaps
 */
app.get('/api/v1/gaps', async (req, res) => {
  try {
    const date = req.query.date || new Date().toISOString().slice(0, 10).replace(/-/g, '');
    const channelFilter = req.query.channel || 'all';
    
    const gaps = await getGapAnalysis(paths, date, channelFilter);
    res.json(gaps);
  } catch (err) {
    console.error('Gap analysis error:', err);
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/v1/rtp-gaps?date=YYYYMMDD&channel=all
 * RTP-level gap analysis - reads gap metadata from archive NPZ files
 * These are network packet loss events (zero-filled samples), not missing files
 */
app.get('/api/v1/rtp-gaps', async (req, res) => {
  try {
    const date = req.query.date || new Date().toISOString().slice(0, 10).replace(/-/g, '');
    const channelFilter = req.query.channel || 'all';
    
    const rtpGaps = await getRtpGapAnalysis(paths, date, channelFilter);
    res.json(rtpGaps);
  } catch (err) {
    console.error('RTP gap analysis error:', err);
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/v1/channels/status
 * Per-channel status (RTP, SNR, timing, audio)
 */
app.get('/api/v1/channels/status', async (req, res) => {
  try {
    const channelStatus = await getChannelStatuses(paths);
    res.json(channelStatus);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/v1/summary
 * Aggregated endpoint - all summary data in one call
 */
app.get('/api/v1/summary', async (req, res) => {
  try {
    const [stationInfo, processes, continuity, storage, channelStatus] = await Promise.all([
      Promise.resolve(getStationInfo()),
      getProcessStatuses(paths),
      getDataContinuity(paths),
      getStorageInfo(paths),
      getChannelStatuses(paths)
    ]);
    
    res.json({
      station: stationInfo,
      processes,
      continuity,
      storage,
      channels: channelStatus.channels,
      timestamp: Date.now() / 1000
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ============================================================================
// CARRIER ANALYSIS ENDPOINTS
// ============================================================================

/**
 * GET /api/v1/carrier/quality?date=YYYYMMDD
 * Quality metrics for all channels on a specific date
 */
app.get('/api/v1/carrier/quality', async (req, res) => {
  try {
    const date = req.query.date || new Date().toISOString().slice(0, 10).replace(/-/g, '');
    const quality = await getCarrierQuality(paths, date);
    res.json(quality);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/v1/carrier/available-dates
 * List dates with available 10 Hz NPZ data for spectrogram generation
 * Scans per-channel decimated directories for NPZ files
 */
app.get('/api/v1/carrier/available-dates', async (req, res) => {
  try {
    const dateMap = new Map();  // date -> {channels: Set, npzCount: number, spectrograms: count}
    
    // 1. Scan per-channel decimated directories for 10 Hz NPZ files
    const analyticsRoot = join(paths.dataRoot, 'analytics');
    if (fs.existsSync(analyticsRoot)) {
      const channelDirs = fs.readdirSync(analyticsRoot);
      
      for (const channelDir of channelDirs) {
        const decimatedPath = join(analyticsRoot, channelDir, 'decimated');
        
        if (fs.existsSync(decimatedPath)) {
          try {
            const files = fs.readdirSync(decimatedPath);
            for (const file of files) {
              // Match NPZ files: YYYYMMDDTHHMMSSZ_*_iq_10hz.npz
              if (file.endsWith('_iq_10hz.npz')) {
                const dateMatch = file.match(/^(\d{8})T/);
                if (dateMatch) {
                  const date = dateMatch[1];
                  if (!dateMap.has(date)) {
                    dateMap.set(date, { channels: new Set(), npzCount: 0, spectrograms: 0 });
                  }
                  dateMap.get(date).channels.add(channelDir);
                  dateMap.get(date).npzCount++;
                }
              }
            }
          } catch (e) {
            // Skip directories we can't read
          }
        }
      }
    }
    
    // 2. Check spectrograms directory for each discovered date
    const spectrogramsRoot = paths.getSpectrogramsRoot();
    for (const [date, info] of dateMap) {
      const spectrogramDir = join(spectrogramsRoot, date);
      if (fs.existsSync(spectrogramDir)) {
        const checkForPngs = (dir) => {
          let count = 0;
          try {
            const items = fs.readdirSync(dir);
            for (const item of items) {
              const itemPath = join(dir, item);
              const itemStat = fs.statSync(itemPath);
              if (itemStat.isDirectory()) {
                count += checkForPngs(itemPath);
              } else if (item.endsWith('.png')) {
                count++;
              }
            }
          } catch (e) {}
          return count;
        };
        info.spectrograms = checkForPngs(spectrogramDir);
      }
    }
    
    // 3. Build dates array
    const dates = [];
    for (const [date, info] of dateMap) {
      const formatted = `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)}`;
      dates.push({
        date: date,
        formatted: formatted,
        count: info.channels.size,
        npzCount: info.npzCount,
        hasSpectrograms: info.spectrograms > 0,
        spectrogramCount: info.spectrograms
      });
    }
    
    // Sort descending (most recent first)
    dates.sort((a, b) => b.date.localeCompare(a.date));
    
    res.json({ dates });
  } catch (err) {
    console.error('Error loading available dates:', err);
    res.status(500).json({ error: err.message });
  }
});

function loadDiscriminationRecords(channelName, date) {
  const fileChannelName = channelName.replace(/ /g, '_');
  const fileName = `${fileChannelName}_discrimination_${date}.csv`;
  const filePath = join(paths.getDiscriminationDir(channelName), fileName);
  
  if (!fs.existsSync(filePath)) {
    return { filePath, records: null };
  }
  
  const csvContent = fs.readFileSync(filePath, 'utf8').trim();
  if (!csvContent) {
    return { filePath, records: [] };
  }
  
  const lines = csvContent.split('\n');
  const records = [];
  
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i];
    const parts = [];
    let inQuotes = false;
    let current = '';
    
    for (let j = 0; j < line.length; j++) {
      const char = line[j];
      const nextChar = j < line.length - 1 ? line[j + 1] : null;
      
      if (char === '"' && nextChar === '"' && inQuotes) {
        current += '"';
        j++;
      } else if (char === '"') {
        inQuotes = !inQuotes;
      } else if (char === ',' && !inQuotes) {
        parts.push(current);
        current = '';
      } else {
        current += char;
      }
    }
    parts.push(current);
    
    if (parts.length >= 21) {
      let timestamp = parts[0].trim();
      if (timestamp.endsWith('+00:00')) {
        timestamp = timestamp.replace('+00:00', 'Z');
      }
      
      let tick_windows = null;
      if (parts[15] && parts[15].trim() !== '') {
        try {
          tick_windows = JSON.parse(parts[15].trim());
        } catch (e) {
          console.warn(`Failed to parse tick_windows_10sec JSON at line ${i}:`, e);
        }
      }
      
      let bcd_windows = null;
      if (parts[20] && parts[20].trim() !== '') {
        try {
          bcd_windows = JSON.parse(parts[20].trim());
        } catch (e) {
          console.warn(`Failed to parse bcd_windows JSON at line ${i}:`, e);
        }
      }
      
      // Parse inter-method validation arrays (columns 27-28)
      let inter_method_agreements = null;
      let inter_method_disagreements = null;
      if (parts[27] && parts[27].trim() !== '') {
        try {
          inter_method_agreements = JSON.parse(parts[27].trim());
        } catch (e) {}
      }
      if (parts[28] && parts[28].trim() !== '') {
        try {
          inter_method_disagreements = JSON.parse(parts[28].trim());
        } catch (e) {}
      }
      
      records.push({
        timestamp_utc: timestamp,
        minute_timestamp: parseInt(parts[1]),
        minute_number: parseInt(parts[2]),
        wwv_detected: parts[3] === '1',
        wwvh_detected: parts[4] === '1',
        wwv_power_db: parts[5] !== '' ? parseFloat(parts[5]) : null,
        wwvh_power_db: parts[6] !== '' ? parseFloat(parts[6]) : null,
        power_ratio_db: parts[7] !== '' ? parseFloat(parts[7]) : null,
        differential_delay_ms: parts[8] !== '' ? parseFloat(parts[8]) : null,
        tone_440hz_wwv_detected: parts[9] === '1',
        tone_440hz_wwv_power_db: parts[10] !== '' ? parseFloat(parts[10]) : null,
        tone_440hz_wwvh_detected: parts[11] === '1',
        tone_440hz_wwvh_power_db: parts[12] !== '' ? parseFloat(parts[12]) : null,
        dominant_station: parts[13],
        confidence: parts[14],
        tick_windows_10sec: tick_windows,
        bcd_wwv_amplitude: parts[16] !== '' ? parseFloat(parts[16]) : null,
        bcd_wwvh_amplitude: parts[17] !== '' ? parseFloat(parts[17]) : null,
        bcd_differential_delay_ms: parts[18] !== '' ? parseFloat(parts[18]) : null,
        bcd_correlation_quality: parts[19] !== '' ? parseFloat(parts[19]) : null,
        bcd_windows: bcd_windows,
        // New 500/600 Hz ground truth columns (21-24)
        tone_500_600_detected: parts[21] === '1',
        tone_500_600_power_db: parts[22] !== '' ? parseFloat(parts[22]) : null,
        tone_500_600_freq_hz: parts[23] !== '' ? parseInt(parts[23]) : null,
        tone_500_600_ground_truth_station: parts[24] || null,
        // New BCD validation columns (25-26)
        bcd_minute_validated: parts[25] === '1',
        bcd_correlation_peak_quality: parts[26] !== '' ? parseFloat(parts[26]) : null,
        // Inter-method cross-validation (27-28)
        inter_method_agreements: inter_method_agreements,
        inter_method_disagreements: inter_method_disagreements
      });
    } else if (parts.length >= 16) {
      let timestamp = parts[0].trim();
      if (timestamp.endsWith('+00:00')) {
        timestamp = timestamp.replace('+00:00', 'Z');
      }
      
      let tick_windows = null;
      if (parts[15] && parts[15].trim() !== '') {
        try {
          tick_windows = JSON.parse(parts[15].trim());
        } catch (e) {
          console.warn(`Failed to parse tick_windows_10sec JSON at line ${i}:`, e);
        }
      }
      
      records.push({
        timestamp_utc: timestamp,
        minute_timestamp: parseInt(parts[1]),
        minute_number: parseInt(parts[2]),
        wwv_detected: parts[3] === '1',
        wwvh_detected: parts[4] === '1',
        wwv_snr_db: parts[5] !== '' ? parseFloat(parts[5]) : null,
        wwvh_snr_db: parts[6] !== '' ? parseFloat(parts[6]) : null,
        power_ratio_db: parts[7] !== '' ? parseFloat(parts[7]) : null,
        differential_delay_ms: parts[8] !== '' ? parseFloat(parts[8]) : null,
        tone_440hz_wwv_detected: parts[9] === '1',
        tone_440hz_wwv_power_db: parts[10] !== '' ? parseFloat(parts[10]) : null,
        tone_440hz_wwvh_detected: parts[11] === '1',
        tone_440hz_wwvh_power_db: parts[12] !== '' ? parseFloat(parts[12]) : null,
        dominant_station: parts[13],
        confidence: parts[14],
        tick_windows_10sec: tick_windows,
        bcd_wwv_amplitude: null,
        bcd_wwvh_amplitude: null,
        bcd_differential_delay_ms: null,
        bcd_correlation_quality: null,
        bcd_windows: null
      });
    } else if (parts.length >= 15) {
      let timestamp = parts[0].trim();
      if (timestamp.endsWith('+00:00')) {
        timestamp = timestamp.replace('+00:00', 'Z');
      }
      
      records.push({
        timestamp_utc: timestamp,
        minute_timestamp: parseInt(parts[1]),
        minute_number: parseInt(parts[2]),
        wwv_detected: parts[3] === '1',
        wwvh_detected: parts[4] === '1',
        wwv_snr_db: parts[5] !== '' ? parseFloat(parts[5]) : null,
        wwvh_snr_db: parts[6] !== '' ? parseFloat(parts[6]) : null,
        power_ratio_db: parts[7] !== '' ? parseFloat(parts[7]) : null,
        differential_delay_ms: parts[8] !== '' ? parseFloat(parts[8]) : null,
        tone_440hz_wwv_detected: parts[9] === '1',
        tone_440hz_wwv_power_db: parts[10] !== '' ? parseFloat(parts[10]) : null,
        tone_440hz_wwvh_detected: parts[11] === '1',
        tone_440hz_wwvh_power_db: parts[12] !== '' ? parseFloat(parts[12]) : null,
        dominant_station: parts[13],
        confidence: parts[14],
        tick_windows_10sec: null
      });
    } else if (parts.length >= 10) {
      let timestamp = parts[0].trim();
      if (timestamp.endsWith('+00:00')) {
        timestamp = timestamp.replace('+00:00', 'Z');
      }
      
      records.push({
        timestamp_utc: timestamp,
        minute_timestamp: parseInt(parts[1]),
        minute_number: null,
        wwv_detected: parts[2] === '1',
        wwvh_detected: parts[3] === '1',
        wwv_snr_db: parts[4] !== '' ? parseFloat(parts[4]) : null,
        wwvh_snr_db: parts[5] !== '' ? parseFloat(parts[5]) : null,
        power_ratio_db: parts[6] !== '' ? parseFloat(parts[6]) : null,
        differential_delay_ms: parts[7] !== '' ? parseFloat(parts[7]) : null,
        tone_440hz_wwv_detected: false,
        tone_440hz_wwv_power_db: null,
        tone_440hz_wwvh_detected: false,
        tone_440hz_wwvh_power_db: null,
        dominant_station: parts[8],
        confidence: parts[9]
      });
    }
  }
  
  return { filePath, records };
}

function computeDominanceValue(record) {
  if (record.wwv_detected && !record.wwvh_detected) return 2;
  if (!record.wwv_detected && record.wwvh_detected) return -2;
  if (!record.wwv_detected && !record.wwvh_detected) return 0;
  const wwv = record.wwv_power_db ?? record.wwv_snr_db ?? 0;
  const wwvh = record.wwvh_power_db ?? record.wwvh_snr_db ?? 0;
  const diff = wwv - wwvh;
  if (diff > 3) return 2;
  if (diff < -3) return -2;
  if (diff > 0) return 1;
  if (diff < 0) return -1;
  return 0;
}

function calculateRatioDb(wwvAmp, wwvhAmp) {
  if (typeof wwvAmp !== 'number' || typeof wwvhAmp !== 'number') {
    return null;
  }
  if (wwvAmp <= 0 || wwvhAmp <= 0) {
    return null;
  }
  return 20 * Math.log10(wwvAmp / wwvhAmp);
}

/**
 * GET /api/v1/channels/:channelName/discrimination/:date
 * Get discrimination time-series data for a channel and date
 */
app.get('/api/v1/channels/:channelName/discrimination/:date', async (req, res) => {
  try {
    const { channelName, date } = req.params;
    const parsed = loadDiscriminationRecords(channelName, date);
    
    if (!parsed.records) {
      return res.json({
        date,
        channel: channelName,
        data: [],
        message: 'No data for this date'
      });
    }
    
    res.json({
      date,
      channel: channelName,
      data: parsed.records,
      count: parsed.records.length
    });
  } catch (error) {
    console.error('Failed to get discrimination data:', error);
    res.status(500).json({
      error: 'Failed to get discrimination data',
      details: error.message
    });
  }
});

/**
 * GET /api/v1/channels/:channelName/discrimination/:date/dashboard
 * Aggregated dashboard data for redesigned discrimination page
 */
app.get('/api/v1/channels/:channelName/discrimination/:date/dashboard', async (req, res) => {
  try {
    const { channelName, date } = req.params;
    const parsed = loadDiscriminationRecords(channelName, date);
    
    if (!parsed.records) {
      return res.json({
        date,
        channel: channelName,
        timeline: [],
        message: 'No data for this date'
      });
    }
    
    const records = parsed.records;
    if (records.length === 0) {
      return res.json({
        date,
        channel: channelName,
        timeline: [],
        message: 'No data for this date'
      });
    }
    
    let wwvDetected = 0;
    let wwvhDetected = 0;
    let hz440Wwv = 0;
    let hz440Wwvh = 0;
    let bothDetected = 0;
    const dominanceCounts = { wwv: 0, wwvh: 0, balanced: 0 };
    
    const timeline = records.map(record => {
      if (record.wwv_detected) wwvDetected++;
      if (record.wwvh_detected) wwvhDetected++;
      if (record.wwv_detected && record.wwvh_detected) bothDetected++;
      if (record.tone_440hz_wwv_detected) hz440Wwv++;
      if (record.tone_440hz_wwvh_detected) hz440Wwvh++;
      
      const dominanceValue = computeDominanceValue(record);
      if (dominanceValue > 0) dominanceCounts.wwv++;
      else if (dominanceValue < 0) dominanceCounts.wwvh++;
      else dominanceCounts.balanced++;
      
      const wwvPower = record.wwv_power_db ?? record.wwv_snr_db ?? null;
      const wwvhPower = record.wwvh_power_db ?? record.wwvh_snr_db ?? null;
      const snrDiff = (wwvPower !== null && wwvhPower !== null) ? (wwvPower - wwvhPower) : null;
      
      return {
        timestamp_utc: record.timestamp_utc,
        minute_timestamp: record.minute_timestamp,
        wwv_power_db: wwvPower,
        wwvh_power_db: wwvhPower,
        power_ratio_db: record.power_ratio_db,
        snr_difference_db: snrDiff,
        differential_delay_ms: record.differential_delay_ms,
        dominant_station: record.dominant_station,
        confidence: record.confidence,
        dominance_value: dominanceValue
      };
    });
    
    // Collect BCD samples, tick windows, and method parameters
    const bcdSamples = [];
    const tickSamples = [];
    let wwvAmpSum = 0;
    let wwvhAmpSum = 0;
    let wwvAmpCount = 0;
    let wwvhAmpCount = 0;
    const ratioValues = [];
    const qualityValues = [];
    const bcdWindowsPerMinute = [];
    const tickWindowsPerMinute = [];
    
    records.forEach(record => {
      let bcdCount = 0;
      let tickCount = 0;
      
      // BCD windows
      if (Array.isArray(record.bcd_windows)) {
        const baseTime = new Date(record.timestamp_utc);
        bcdCount = record.bcd_windows.length;
        
        record.bcd_windows.forEach(win => {
          if (!baseTime || isNaN(baseTime.getTime())) {
            return;
          }
          const windowOffset = typeof win.window_start_sec === 'number' ? win.window_start_sec : 0;
          const sampleTime = new Date(baseTime.getTime() + windowOffset * 1000);
          const ratioDb = calculateRatioDb(win.wwv_amplitude, win.wwvh_amplitude);
          
          if (typeof win.wwv_amplitude === 'number' && isFinite(win.wwv_amplitude)) {
            wwvAmpSum += win.wwv_amplitude;
            wwvAmpCount++;
          }
          if (typeof win.wwvh_amplitude === 'number' && isFinite(win.wwvh_amplitude)) {
            wwvhAmpSum += win.wwvh_amplitude;
            wwvhAmpCount++;
          }
          if (ratioDb !== null && isFinite(ratioDb)) {
            ratioValues.push(ratioDb);
          }
          if (typeof win.correlation_quality === 'number' && isFinite(win.correlation_quality)) {
            qualityValues.push(win.correlation_quality);
          }
          
          bcdSamples.push({
            timestamp_utc: sampleTime.toISOString(),
            minute_timestamp: record.minute_timestamp,
            wwv_amplitude: win.wwv_amplitude ?? null,
            wwvh_amplitude: win.wwvh_amplitude ?? null,
            ratio_db: ratioDb,
            differential_delay_ms: win.differential_delay_ms ?? null,
            correlation_quality: win.correlation_quality ?? null
          });
        });
      }
      
      // Tick windows
      if (Array.isArray(record.tick_windows_10sec)) {
        const baseTime = new Date(record.timestamp_utc);
        tickCount = record.tick_windows_10sec.length;
        
        record.tick_windows_10sec.forEach(win => {
          if (!baseTime || isNaN(baseTime.getTime())) return;
          const windowOffset = typeof win.second === 'number' ? win.second : 0;
          const sampleTime = new Date(baseTime.getTime() + windowOffset * 1000);
          
          tickSamples.push({
            timestamp_utc: sampleTime.toISOString(),
            minute_timestamp: record.minute_timestamp,
            wwv_coherent_snr: win.coherent_wwv_snr_db ?? null,
            wwvh_coherent_snr: win.coherent_wwvh_snr_db ?? null,
            wwv_incoherent_snr: win.incoherent_wwv_snr_db ?? null,
            wwvh_incoherent_snr: win.incoherent_wwvh_snr_db ?? null,
            coherence_quality_wwv: win.coherence_quality_wwv ?? null,
            coherence_quality_wwvh: win.coherence_quality_wwvh ?? null
          });
        });
      }
      
      if (bcdCount > 0) bcdWindowsPerMinute.push(bcdCount);
      if (tickCount > 0) tickWindowsPerMinute.push(tickCount);
    });
    
    const mean = (arr) => arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0;
    const stddev = (arr) => {
      if (arr.length === 0) return 0;
      const avg = mean(arr);
      const variance = arr.reduce((sum, val) => sum + Math.pow(val - avg, 2), 0) / arr.length;
      return Math.sqrt(variance);
    };
    
    const bcdSummary = {
      total_windows: bcdSamples.length,
      wwv_amplitude_mean: wwvAmpCount ? wwvAmpSum / wwvAmpCount : 0,
      wwvh_amplitude_mean: wwvhAmpCount ? wwvhAmpSum / wwvhAmpCount : 0,
      ratio_mean_db: ratioValues.length ? mean(ratioValues) : 0,
      ratio_std_db: ratioValues.length ? stddev(ratioValues) : 0,
      quality_mean: qualityValues.length ? mean(qualityValues) : 0
    };
    
    const votingSeries = records.map(record => ({
      timestamp_utc: record.timestamp_utc,
      dominant_station: record.dominant_station || 'NONE',
      confidence: record.confidence || 'low',
      dominance_value: computeDominanceValue(record)
    }));
    
    const votingCounts = {
      wwv: votingSeries.filter(v => v.dominant_station === 'WWV').length,
      wwvh: votingSeries.filter(v => v.dominant_station === 'WWVH').length,
      balanced: votingSeries.filter(v => v.dominant_station === 'BALANCED').length,
      none: votingSeries.filter(v => !v.dominant_station || v.dominant_station === 'NONE').length
    };
    
    const totalMinutes = records.length || 1;
    
    // Calculate method parameters
    const methodParams = {
      bcd_windows_per_minute: bcdWindowsPerMinute.length ? mean(bcdWindowsPerMinute).toFixed(1) : 0,
      tick_windows_per_minute: tickWindowsPerMinute.length ? mean(tickWindowsPerMinute).toFixed(1) : 0,
      hz440_samples_per_hour: 2, // Fixed: WWV minute 2, WWVH minute 1
      per_minute_tone_samples: 1, // Fixed: 1000/1200 Hz tones at :00
      minutes_with_bcd: bcdWindowsPerMinute.length,
      minutes_with_ticks: tickWindowsPerMinute.length
    };
    
    // Determine UTC day range
    const timestamps = records.map(r => new Date(r.timestamp_utc).getTime()).filter(t => !isNaN(t));
    const minTime = timestamps.length ? Math.min(...timestamps) : null;
    const maxTime = timestamps.length ? Math.max(...timestamps) : null;
    const dayStart = minTime ? new Date(new Date(minTime).setUTCHours(0, 0, 0, 0)).toISOString() : null;
    const dayEnd = minTime ? new Date(new Date(minTime).setUTCHours(23, 59, 59, 999)).toISOString() : null;
    
    const summary = {
      total_minutes: records.length,
      wwv_detected: wwvDetected,
      wwvh_detected: wwvhDetected,
      both_detected: bothDetected,
      hz440_wwv_detections: hz440Wwv,
      hz440_wwvh_detections: hz440Wwvh,
      dominance_pct: {
        wwv: ((dominanceCounts.wwv / totalMinutes) * 100).toFixed(1),
        wwvh: ((dominanceCounts.wwvh / totalMinutes) * 100).toFixed(1),
        balanced: ((dominanceCounts.balanced / totalMinutes) * 100).toFixed(1)
      },
      bcd_windows: bcdSamples.length,
      bcd_ratio_mean_db: bcdSummary.ratio_mean_db,
      bcd_ratio_std_db: bcdSummary.ratio_std_db,
      bcd_quality_mean: bcdSummary.quality_mean
    };
    
    res.json({
      date,
      channel: channelName,
      summary,
      timeline,
      time_range: {
        day_start_utc: dayStart,
        day_end_utc: dayEnd,
        data_start_utc: minTime ? new Date(minTime).toISOString() : null,
        data_end_utc: maxTime ? new Date(maxTime).toISOString() : null
      },
      method_params: methodParams,
      bcd: {
        samples: bcdSamples,
        summary: bcdSummary
      },
      ticks: {
        samples: tickSamples,
        windows_per_minute: methodParams.tick_windows_per_minute
      },
      voting: {
        series: votingSeries,
        counts: votingCounts
      }
    });
  } catch (error) {
    console.error('Failed to get discrimination dashboard data:', error);
    res.status(500).json({
      error: 'Failed to get discrimination dashboard data',
      details: error.message
    });
  }
});

/**
 * GET /api/v1/channels/:channelName/discrimination/:date/metrics
 * Get per-method performance metrics for discrimination analysis
 */
app.get('/api/v1/channels/:channelName/discrimination/:date/metrics', async (req, res) => {
  try {
    const { channelName, date } = req.params;
    const fileChannelName = channelName.replace(/ /g, '_');
    const fileName = `${fileChannelName}_discrimination_${date}.csv`;
    const filePath = join(paths.getDiscriminationDir(channelName), fileName);
    
    if (!fs.existsSync(filePath)) {
      return res.json({
        date: date,
        channel: channelName,
        message: 'No data for this date'
      });
    }
    
    // Read and parse CSV
    const csvContent = fs.readFileSync(filePath, 'utf8');
    const lines = csvContent.trim().split('\n');
    
    // Calculate metrics by parsing all rows
    let totalMinutes = 0;
    let wwvDetections = 0;
    let wwvhDetections = 0;
    let bothDetected = 0;
    let hz440WwvDetections = 0;
    let hz440WwvhDetections = 0;
    let bcdValidWindows = 0;
    let bcdTotalWindows = 0;
    let tickCoherentCount = 0;
    let tickIncoherentCount = 0;
    let tickTotalWindows = 0;
    let highConfidence = 0;
    let mediumConfidence = 0;
    let lowConfidence = 0;
    let wwvDominant = 0;
    let wwvhDominant = 0;
    let balanced = 0;
    
    const powerRatios = [];
    const differentialDelays = [];
    const bcdQuality = [];
    
    // Parse each row
    for (let i = 1; i < lines.length; i++) {
      let line = lines[i];
      const parts = [];
      let inQuotes = false;
      let current = '';
      
      for (let j = 0; j < line.length; j++) {
        const char = line[j];
        const nextChar = j < line.length - 1 ? line[j + 1] : null;
        
        if (char === '"' && nextChar === '"' && inQuotes) {
          current += '"';
          j++;
        } else if (char === '"') {
          inQuotes = !inQuotes;
        } else if (char === ',' && !inQuotes) {
          parts.push(current);
          current = '';
        } else {
          current += char;
        }
      }
      parts.push(current);
      
      if (parts.length >= 15) {
        totalMinutes++;
        
        // Method 3: Timing Tones
        if (parts[3] === '1') wwvDetections++;
        if (parts[4] === '1') wwvhDetections++;
        if (parts[3] === '1' && parts[4] === '1') bothDetected++;
        
        const powerRatio = parseFloat(parts[7]);
        if (!isNaN(powerRatio)) powerRatios.push(powerRatio);
        
        const diffDelay = parts[8] !== '' ? parseFloat(parts[8]) : null;
        if (diffDelay !== null && !isNaN(diffDelay)) differentialDelays.push(diffDelay);
        
        // Method 1: 440 Hz
        if (parts[9] === '1') hz440WwvDetections++;
        if (parts[11] === '1') hz440WwvhDetections++;
        
        // Method 5: Weighted Voting
        const confidence = parts[14];
        if (confidence === 'high') highConfidence++;
        else if (confidence === 'medium') mediumConfidence++;
        else if (confidence === 'low') lowConfidence++;
        
        const dominant = parts[13];
        if (dominant === 'WWV') wwvDominant++;
        else if (dominant === 'WWVH') wwvhDominant++;
        else if (dominant === 'BALANCED') balanced++;
        
        // Method 4: Tick Windows
        if (parts[15] && parts[15].trim() !== '') {
          try {
            const tickWindows = JSON.parse(parts[15].trim());
            if (tickWindows && Array.isArray(tickWindows)) {
              tickWindows.forEach(win => {
                tickTotalWindows++;
                if (win.integration_method === 'coherent') tickCoherentCount++;
                else if (win.integration_method === 'incoherent') tickIncoherentCount++;
              });
            }
          } catch (e) {
            // Ignore parse errors
          }
        }
        
        // Method 2: BCD
        if (parts.length >= 21 && parts[20] && parts[20].trim() !== '') {
          try {
            const bcdWindows = JSON.parse(parts[20].trim());
            if (bcdWindows && Array.isArray(bcdWindows)) {
              bcdTotalWindows += bcdWindows.length;
              bcdValidWindows += bcdWindows.filter(w => w.correlation_quality > 0).length;
              bcdWindows.forEach(w => {
                if (w.correlation_quality && !isNaN(w.correlation_quality)) {
                  bcdQuality.push(w.correlation_quality);
                }
              });
            }
          } catch (e) {
            // Ignore parse errors
          }
        }
      }
    }
    
    // Calculate statistics
    const meanPowerRatio = powerRatios.length > 0 
      ? powerRatios.reduce((a,b) => a+b) / powerRatios.length : 0;
    const stdPowerRatio = powerRatios.length > 0
      ? Math.sqrt(powerRatios.reduce((sum, val) => sum + Math.pow(val - meanPowerRatio, 2), 0) / powerRatios.length) : 0;
    
    const meanDiffDelay = differentialDelays.length > 0
      ? differentialDelays.reduce((a,b) => a+b) / differentialDelays.length : 0;
    const stdDiffDelay = differentialDelays.length > 0
      ? Math.sqrt(differentialDelays.reduce((sum, val) => sum + Math.pow(val - meanDiffDelay, 2), 0) / differentialDelays.length) : 0;
    
    const meanBcdQuality = bcdQuality.length > 0
      ? bcdQuality.reduce((a,b) => a+b) / bcdQuality.length : 0;
    
    res.json({
      date: date,
      channel: channelName,
      total_minutes: totalMinutes,
      method_1_hz440: {
        name: "440 Hz ID Tones",
        temporal_resolution: "2/hour",
        wwv_detections: hz440WwvDetections,
        wwvh_detections: hz440WwvhDetections,
        total_possible: 48, // 24 hours × 2 per hour
        detection_rate: (hz440WwvDetections + hz440WwvhDetections) / 48
      },
      method_2_bcd: {
        name: "BCD Correlation",
        temporal_resolution: "~15/minute",
        total_windows: bcdTotalWindows,
        valid_windows: bcdValidWindows,
        mean_correlation_quality: meanBcdQuality.toFixed(2),
        minutes_with_bcd: Math.floor(bcdTotalWindows / 15)
      },
      method_3_timing_tones: {
        name: "Timing Tones (1000/1200 Hz)",
        temporal_resolution: "1/minute",
        wwv_detections: wwvDetections,
        wwvh_detections: wwvhDetections,
        both_detected: bothDetected,
        detection_rate: bothDetected / totalMinutes,
        mean_power_ratio_db: meanPowerRatio.toFixed(1),
        std_power_ratio_db: stdPowerRatio.toFixed(1),
        mean_differential_delay_ms: meanDiffDelay.toFixed(1),
        std_differential_delay_ms: stdDiffDelay.toFixed(1)
      },
      method_4_ticks: {
        name: "Tick Windows",
        temporal_resolution: "6/minute",
        total_windows: tickTotalWindows,
        coherent_integration: tickCoherentCount,
        incoherent_integration: tickIncoherentCount,
        coherent_rate: tickTotalWindows > 0 ? (tickCoherentCount / tickTotalWindows).toFixed(2) : 0
      },
      method_5_voting: {
        name: "Weighted Voting",
        temporal_resolution: "1/minute",
        wwv_dominant: wwvDominant,
        wwvh_dominant: wwvhDominant,
        balanced: balanced,
        high_confidence: highConfidence,
        medium_confidence: mediumConfidence,
        low_confidence: lowConfidence,
        high_confidence_rate: totalMinutes > 0 ? (highConfidence / totalMinutes).toFixed(2) : 0
      }
    });
  } catch (error) {
    console.error('Failed to get discrimination metrics:', error);
    res.status(500).json({
      error: 'Failed to get discrimination metrics',
      details: error.message
    });
  }
});

/**
 * GET /api/monitoring/station-info
 * Station configuration and server uptime (for timing dashboard)
 */
app.get('/api/monitoring/station-info', async (req, res) => {
  try {
    const stationInfo = config.station;
    
    if (!stationInfo) {
      return res.json({
        available: false,
        message: 'Station configuration not found'
      });
    }
    
    // Calculate uptime
    const uptimeMs = Date.now() - serverStartTime;
    const uptimeSeconds = Math.floor(uptimeMs / 1000);
    const uptimeMinutes = Math.floor(uptimeSeconds / 60);
    const uptimeHours = Math.floor(uptimeMinutes / 60);
    const uptimeDays = Math.floor(uptimeHours / 24);
    
    const uptimeFormatted = uptimeDays > 0 
      ? `${uptimeDays}d ${uptimeHours % 24}h ${uptimeMinutes % 60}m`
      : uptimeHours > 0
      ? `${uptimeHours}h ${uptimeMinutes % 60}m`
      : `${uptimeMinutes}m ${uptimeSeconds % 60}s`;
    
    res.json({
      available: true,
      station: {
        callsign: stationInfo.callsign || 'UNKNOWN',
        gridSquare: stationInfo.grid_square || 'UNKNOWN',
        stationId: stationInfo.id || 'UNKNOWN',
        instrumentId: stationInfo.instrument_id || 'UNKNOWN',
        description: stationInfo.description || ''
      },
      server: {
        uptime: uptimeFormatted,
        uptimeSeconds: uptimeSeconds,
        startTime: new Date(serverStartTime).toISOString()
      }
    });
    
  } catch (error) {
    console.error('Failed to get station info:', error);
    res.json({
      available: false,
      error: error.message
    });
  }
});

/**
 * GET /api/monitoring/timing-quality
 * Timing & Quality Dashboard API - V2 Architecture compatible
 */
app.get('/api/monitoring/timing-quality', async (req, res) => {
  try {
    // Get status from V2 architecture status files
    const coreStatusFile = paths.getCoreStatusFile();
    
    if (!fs.existsSync(coreStatusFile)) {
      return res.json({
        available: false,
        message: 'Core recorder status not available. Is the recorder running?'
      });
    }
    
    const coreContent = fs.readFileSync(coreStatusFile, 'utf8');
    const coreStatus = JSON.parse(coreContent);
    
    // Build channel data from core recorder status
    const channelData = {};
    let timeSnapStatus = null;
    
    if (coreStatus.channels) {
      for (const [ssrc, channelInfo] of Object.entries(coreStatus.channels)) {
        const channelName = channelInfo.channel_name;
        const totalSamples = channelInfo.packets_received * 320;
        const gapSamples = channelInfo.total_gap_samples || 0;
        const completeness = totalSamples > 0 ? ((totalSamples - gapSamples) / totalSamples * 100) : 100;
        const packetLoss = totalSamples > 0 ? (gapSamples / totalSamples * 100) : 0;
        
        channelData[channelName] = {
          status: channelInfo.status || 'unknown',
          sampleCompleteness: completeness,
          avgPacketLoss: packetLoss,
          npzFilesWritten: channelInfo.npz_files_written || 0,
          packetsReceived: channelInfo.packets_received || 0,
          gapsDetected: channelInfo.gaps_detected || 0,
          lastPacketTime: channelInfo.last_packet_time || null,
          wwvDetections: 0,
          wwvhDetections: 0,
          chuDetections: 0,
          npzProcessed: 0,
          digitalRfSamples: 0
        };
      }
    }
    
    // Add analytics data if available
    const channels = paths.discoverChannels();
    for (const channelName of channels) {
      const statusDir = paths.getAnalyticsStatusDir(channelName);
      const statusFile = join(statusDir, 'analytics-service-status.json');
      
      if (fs.existsSync(statusFile)) {
        try {
          const content = fs.readFileSync(statusFile, 'utf8');
          const analyticsStatus = JSON.parse(content);
          
          // Analytics status has channels object with channel name as key
          const channelAnalytics = analyticsStatus.channels?.[channelName];
          
          if (channelAnalytics) {
            if (!channelData[channelName]) {
              channelData[channelName] = {};
            }
            
            // Merge analytics data from the nested channel object
            Object.assign(channelData[channelName], {
              wwvDetections: channelAnalytics.tone_detections?.wwv || 0,
              wwvhDetections: channelAnalytics.tone_detections?.wwvh || 0,
              chuDetections: channelAnalytics.tone_detections?.chu || 0,
              npzProcessed: channelAnalytics.npz_files_processed || 0,
              digitalRfSamples: channelAnalytics.digital_rf?.samples_written || 0
            });
            
            // Track time_snap status
            if (channelAnalytics.time_snap && channelAnalytics.time_snap.established && !timeSnapStatus) {
              timeSnapStatus = {
                established: true,
                source: channelName,
                station: channelAnalytics.time_snap.station,
                confidence: channelAnalytics.time_snap.confidence,
                age: channelAnalytics.time_snap.age_minutes,
                status: channelAnalytics.time_snap.source
              };
            }
          }
        } catch (err) {
          // Skip invalid status file
          console.error(`Error reading analytics status for ${channelName}:`, err.message);
        }
      }
    }
    
    res.json({
      available: true,
      source: 'v2_status_files',
      channels: channelData,
      timeSnap: timeSnapStatus,
      overall: {
        summary: {
          channels_active: coreStatus.overall?.channels_active || 0,
          channels_total: coreStatus.overall?.channels_total || 0,
          npz_written: coreStatus.overall?.total_npz_written || 0,
          packets_received: coreStatus.overall?.total_packets_received || 0,
          npz_processed: Object.values(channelData).reduce((sum, ch) => sum + (ch.npzProcessed || 0), 0)
        }
      },
      alerts: []
    });
    
  } catch (error) {
    console.error('Failed to get timing-quality data:', error);
    res.status(500).json({
      error: 'Failed to get timing-quality data',
      details: error.message,
      available: false
    });
  }
});

/**
 * GET /spectrograms/{date}/{subdirectory}/{filename}
 * Serve spectrogram PNG files from subdirectories (wide-decimated, native-carrier)
 */
app.get('/spectrograms/:date/:subdirectory/:filename', (req, res) => {
  try {
    const { date, subdirectory, filename } = req.params;
    const spectrogramPath = join(paths.getSpectrogramsDateDir(date), subdirectory, filename);
    
    if (!fs.existsSync(spectrogramPath)) {
      return res.status(404).json({ error: 'Spectrogram not found' });
    }
    
    res.sendFile(spectrogramPath);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /spectrograms/{date}/{filename}
 * Serve spectrogram PNG files (legacy path for backward compatibility)
 */
app.get('/spectrograms/:date/:filename', (req, res) => {
  try {
    const { date, filename } = req.params;
    const spectrogramPath = join(paths.getSpectrogramsDateDir(date), filename);
    
    if (!fs.existsSync(spectrogramPath)) {
      return res.status(404).json({ error: 'Spectrogram not found' });
    }
    
    res.sendFile(spectrogramPath);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /quality-analysis/{filename}
 * Serve quality analysis JSON reports
 */
app.get('/quality-analysis/:filename', (req, res) => {
  try {
    const { filename } = req.params;
    
    // Only allow JSON files to prevent directory traversal
    if (!filename.endsWith('.json')) {
      return res.status(400).json({ error: 'Only JSON files are allowed' });
    }
    
    const qualityAnalysisPath = join(dataRoot, 'quality-analysis', filename);
    
    if (!fs.existsSync(qualityAnalysisPath)) {
      return res.status(404).json({ error: 'Quality analysis report not found' });
    }
    
    // Set headers to prevent caching (always serve fresh data)
    res.set({
      'Cache-Control': 'no-cache, no-store, must-revalidate',
      'Pragma': 'no-cache',
      'Expires': '0'
    });
    
    res.sendFile(qualityAnalysisPath);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/analysis/correlations
 * Correlation analysis for identifying scientifically interesting patterns
 */
app.get('/api/analysis/correlations', async (req, res) => {
  try {
    const { channel, date } = req.query;
    
    if (!channel || !date) {
      return res.status(400).json({ 
        error: 'Missing required parameters: channel and date' 
      });
    }
    
    // Load NPZ data for gap analysis
    const npzData = await loadNPZData(paths, channel, date);
    
    // Load discrimination data for SNR analysis
    const discriminationData = await loadDiscriminationData(paths, channel, date);
    
    // Compute correlations
    const correlations = {};
    
    // Time of day patterns (always available if we have NPZ data)
    if (npzData.length > 0) {
      correlations.time_of_day = analyzeTimeOfDay(npzData, discriminationData);
    }
    
    // SNR-based correlations (require discrimination data)
    if (discriminationData.length >= 10) {
      correlations.snr_vs_gaps = analyzeSNRvsGaps(npzData, discriminationData);
      correlations.confidence_vs_snr = analyzeConfidenceVsSNR(discriminationData);
    }
    
    res.json({
      channel,
      date,
      correlations,
      data_summary: {
        npz_records: npzData.length,
        discrimination_records: discriminationData.length
      }
    });
    
  } catch (error) {
    console.error('Failed to compute correlations:', error);
    res.status(500).json({
      error: 'Failed to compute correlations',
      details: error.message
    });
  }
});

// Helper functions for correlation analysis

async function loadNPZData(paths, channelName, dateStr) {
  const npzDir = paths.getArchiveDir(channelName);
  const pattern = `${dateStr}T*Z_*_iq.npz`;
  const npzFiles = fs.readdirSync(npzDir).filter(f => f.match(new RegExp(`^${dateStr}T.*_iq\\.npz$`))).sort();
  
  const data = [];
  for (const filename of npzFiles) {
    try {
      // Extract hour and minute from filename: 20251115T023400Z
      const hour = parseInt(filename.substring(9, 11));
      const minute = parseInt(filename.substring(11, 13));
      
      // Read NPZ file (simplified - just read metadata from filename pattern)
      const npzPath = join(npzDir, filename);
      const stats = fs.statSync(npzPath);
      
      // For now, estimate from file presence (actual NPZ parsing would require python bridge)
      // In production, read from quality CSV or status files
      data.push({
        timestamp: `${dateStr}T${filename.substring(9, 15)}Z`,
        hour,
        minute,
        completeness_pct: 95.0, // Placeholder - would come from quality metrics
        gaps_count: 0
      });
    } catch (err) {
      continue;
    }
  }
  
  return data;
}

async function loadDiscriminationData(paths, channelName, dateStr) {
  const csvDir = paths.getDiscriminationDir(channelName);
  const csvPattern = `*_discrimination_${dateStr}.csv`;
  const csvFiles = fs.readdirSync(csvDir).filter(f => f.includes(`discrimination_${dateStr}.csv`));
  
  if (csvFiles.length === 0) {
    return [];
  }
  
  const data = [];
  const csvPath = join(csvDir, csvFiles[0]);
  const content = fs.readFileSync(csvPath, 'utf8');
  const lines = content.split('\n');
  
  // Skip header
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;
    
    try {
      const parts = line.split(',');
      const timestamp = parts[0];
      const date = new Date(timestamp);
      
      const wwvSnr = parseFloat(parts[4]) || null;
      const wwvhSnr = parseFloat(parts[5]) || null;
      const maxSnr = Math.max(
        wwvSnr !== null && wwvSnr > 0 ? wwvSnr : -Infinity,
        wwvhSnr !== null && wwvhSnr > 0 ? wwvhSnr : -Infinity
      );
      
      data.push({
        timestamp,
        hour: date.getUTCHours(),
        minute: date.getUTCMinutes(),
        wwv_snr_db: wwvSnr,
        wwvh_snr_db: wwvhSnr,
        max_snr_db: maxSnr > -Infinity ? maxSnr : null,
        confidence: parts[9] || 'low'
      });
    } catch (err) {
      continue;
    }
  }
  
  return data;
}

function analyzeTimeOfDay(npzData, discriminationData) {
  const hourly = {};
  
  // Initialize all hours
  for (let h = 0; h < 24; h++) {
    hourly[h] = {
      completeness_values: [],
      snr_values: [],
      avg_completeness: null,
      avg_snr: null,
      completeness_samples: 0,
      snr_samples: 0
    };
  }
  
  // Aggregate NPZ data by hour
  npzData.forEach(item => {
    if (item.completeness_pct !== undefined) {
      hourly[item.hour].completeness_values.push(item.completeness_pct);
    }
  });
  
  // Aggregate discrimination data by hour
  discriminationData.forEach(item => {
    if (item.max_snr_db !== null && item.max_snr_db > 0) {
      hourly[item.hour].snr_values.push(item.max_snr_db);
    }
  });
  
  // Calculate averages
  for (let h = 0; h < 24; h++) {
    const hour = hourly[h];
    
    if (hour.completeness_values.length > 0) {
      hour.avg_completeness = hour.completeness_values.reduce((a, b) => a + b, 0) / hour.completeness_values.length;
      hour.completeness_samples = hour.completeness_values.length;
    }
    
    if (hour.snr_values.length > 0) {
      hour.avg_snr = hour.snr_values.reduce((a, b) => a + b, 0) / hour.snr_values.length;
      hour.snr_samples = hour.snr_values.length;
    }
    
    // Clean up temporary arrays
    delete hour.completeness_values;
    delete hour.snr_values;
  }
  
  return hourly;
}

function analyzeSNRvsGaps(npzData, discriminationData) {
  // Match discrimination data to NPZ data by hour:minute
  const matched = [];
  
  discriminationData.forEach(disc => {
    if (disc.max_snr_db === null || disc.max_snr_db <= 0) return;
    
    const matchingNpz = npzData.find(npz => 
      npz.hour === disc.hour && npz.minute === disc.minute
    );
    
    if (matchingNpz) {
      matched.push({
        snr_db: disc.max_snr_db,
        completeness_pct: matchingNpz.completeness_pct
      });
    }
  });
  
  // Bin by SNR ranges
  const bins = {
    'Very Strong (>30 dB)': [],
    'Strong (20-30 dB)': [],
    'Moderate (10-20 dB)': [],
    'Weak (<10 dB)': []
  };
  
  matched.forEach(item => {
    if (item.snr_db > 30) {
      bins['Very Strong (>30 dB)'].push(item.completeness_pct);
    } else if (item.snr_db > 20) {
      bins['Strong (20-30 dB)'].push(item.completeness_pct);
    } else if (item.snr_db > 10) {
      bins['Moderate (10-20 dB)'].push(item.completeness_pct);
    } else {
      bins['Weak (<10 dB)'].push(item.completeness_pct);
    }
  });
  
  // Calculate averages
  const result = {};
  for (const [binName, values] of Object.entries(bins)) {
    if (values.length > 0) {
      result[binName] = {
        count: values.length,
        avg_completeness: values.reduce((a, b) => a + b, 0) / values.length,
        values: values
      };
    }
  }
  
  return result;
}

function analyzeConfidenceVsSNR(discriminationData) {
  const confidenceLevels = {
    'high': [],
    'medium': [],
    'low': []
  };
  
  discriminationData.forEach(item => {
    if (item.max_snr_db !== null && item.max_snr_db > 0) {
      const conf = item.confidence || 'low';
      if (confidenceLevels[conf]) {
        confidenceLevels[conf].push(item.max_snr_db);
      }
    }
  });
  
  const result = {};
  for (const [level, snrValues] of Object.entries(confidenceLevels)) {
    if (snrValues.length > 0) {
      result[level] = {
        count: snrValues.length,
        avg_snr: snrValues.reduce((a, b) => a + b, 0) / snrValues.length,
        min_snr: Math.min(...snrValues),
        max_snr: Math.max(...snrValues),
        values: snrValues
      };
    } else {
      result[level] = null;
    }
  }
  
  return result;
}

// ============================================================================
// NEW ANALYTICS ENDPOINTS - Priority 1 Implementation
// ============================================================================

/**
 * GET /api/v1/timing/status
 * Real-time timing status with time_snap details
 */
app.get('/api/v1/timing/status', async (req, res) => {
  try {
    const timingStatus = await getTimingStatus(paths);
    res.json(timingStatus);
  } catch (err) {
    console.error('Error getting timing status:', err);
    res.status(500).json({ error: err.message });
  }
});

// ============================================================================
// TIMING ANALYSIS API (New - for comprehensive timing dashboard)
// ============================================================================

/**
 * GET /api/v1/timing/primary-reference
 * Get the system's primary (best) time reference
 */
app.get('/api/v1/timing/primary-reference', async (req, res) => {
  try {
    const primaryRef = await getPrimaryTimeReference(paths, config);
    res.json(primaryRef);
  } catch (err) {
    console.error('Error getting primary reference:', err);
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/v1/timing/health-summary
 * System-wide timing health metrics
 */
app.get('/api/v1/timing/health-summary', async (req, res) => {
  try {
    const health = await getTimingHealthSummary(paths, config);
    res.json(health);
  } catch (err) {
    console.error('Error getting timing health:', err);
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/v1/timing/metrics?channel=WWV%2010%20MHz&date=20251126&hours=24
 * Timing metrics time series for drift analysis
 */
app.get('/api/v1/timing/metrics', async (req, res) => {
  try {
    const { channel, date, hours = 24 } = req.query;
    const metrics = await getTimingMetrics(channel, date, parseInt(hours), paths);
    res.json(metrics);
  } catch (err) {
    console.error('Error getting timing metrics:', err);
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/v1/timing/transitions?channel=all&hours=24
 * Time source transition events
 */
app.get('/api/v1/timing/transitions', async (req, res) => {
  try {
    const { channel = 'all', hours = 24 } = req.query;
    const transitions = await getTimingTransitions(channel, parseInt(hours), paths, config);
    res.json(transitions);
  } catch (err) {
    console.error('Error getting transitions:', err);
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/v1/timing/timeline?channel=all&hours=24
 * Time source timeline for visualization
 */
app.get('/api/v1/timing/timeline', async (req, res) => {
  try {
    const { channel = 'all', hours = 24 } = req.query;
    const timeline = await getTimingTimeline(channel, parseInt(hours), paths);
    res.json(timeline);
  } catch (err) {
    console.error('Error getting timeline:', err);
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/v1/timing/propagation
 * Propagation mode data for all channels (from PropagationModeSolver)
 */
app.get('/api/v1/timing/propagation', async (req, res) => {
  try {
    const channels = config.recorder?.channels || [];
    const enabledChannels = channels.filter(ch => ch.enabled);
    
    const propagationData = [];
    
    for (const channel of enabledChannels) {
      const channelName = channel.description || `Channel ${channel.ssrc}`;
      const key = channelNameToKey(channelName);
      const propFile = join(paths.getAnalyticsDir(channelName), 'timing', 'propagation_status.json');
      
      if (fs.existsSync(propFile)) {
        try {
          const data = JSON.parse(fs.readFileSync(propFile, 'utf-8'));
          propagationData.push(data);
        } catch (err) {
          console.warn(`Error reading propagation status for ${channelName}:`, err.message);
        }
      }
    }
    
    res.json({
      timestamp: new Date().toISOString(),
      channels: propagationData,
      count: propagationData.length
    });
  } catch (err) {
    console.error('Error getting propagation data:', err);
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/v1/tones/current
 * Current tone power levels for all channels
 */
app.get('/api/v1/tones/current', async (req, res) => {
  try {
    const tonePowers = await getCurrentTonePowers(paths);
    res.json(tonePowers);
  } catch (err) {
    console.error('Error getting tone powers:', err);
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/v1/channels/:channelName/discrimination/:date/methods
 * Enhanced discrimination data with all 5 methods
 */
app.get('/api/v1/channels/:channelName/discrimination/:date/methods', async (req, res) => {
  try {
    const { channelName, date } = req.params;
    const allMethods = await loadAllDiscriminationMethods(channelName, date, paths);
    res.json(allMethods);
  } catch (err) {
    console.error('Error loading enhanced discrimination:', err);
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/v1/channels/:channelName/carrier-power/:date
 * Get 10Hz carrier power time series from decimated NPZ files
 */
app.get('/api/v1/channels/:channelName/carrier-power/:date', async (req, res) => {
  try {
    const { channelName, date } = req.params;
    const decimatedDir = paths.getDecimatedDir(channelName);
    
    if (!fs.existsSync(decimatedDir)) {
      return res.json({ channel: channelName, date, records: [], status: 'no_data' });
    }
    
    // Find all 10Hz NPZ files for this date
    const files = fs.readdirSync(decimatedDir)
      .filter(f => f.startsWith(date) && f.endsWith('_10hz.npz'))
      .sort();
    
    if (files.length === 0) {
      return res.json({ channel: channelName, date, records: [], status: 'no_files' });
    }
    
    // Use Python to extract power from NPZ files (Node can't read NPZ directly)
    // Write script to temp file to avoid shell escaping issues
    const tmpScript = `/tmp/carrier_power_${Date.now()}.py`;
    const pythonScript = `
import numpy as np
import json
import sys
from pathlib import Path

decimated_dir = Path(sys.argv[1])
date = sys.argv[2]
records = []

for npz_file in sorted(decimated_dir.glob(f'{date}*_10hz.npz')):
    try:
        data = np.load(npz_file)
        iq = data['iq']
        ts_str = npz_file.name.split('_')[0]
        power_linear = np.mean(np.abs(iq)**2)
        power_db = 10 * np.log10(power_linear + 1e-12)
        peak_power = np.max(np.abs(iq)**2)
        peak_db = 10 * np.log10(peak_power + 1e-12)
        records.append({
            'timestamp': ts_str,
            'power_db': round(float(power_db), 2),
            'peak_db': round(float(peak_db), 2)
        })
    except Exception as e:
        pass

print(json.dumps(records))
`;
    
    fs.writeFileSync(tmpScript, pythonScript);
    
    try {
      const result = execSync(
        `source ${process.env.HOME}/signal-recorder/venv/bin/activate && python3 ${tmpScript} "${decimatedDir}" "${date}"`,
        { encoding: 'utf8', maxBuffer: 10 * 1024 * 1024, shell: '/bin/bash' }
      );
      
      fs.unlinkSync(tmpScript);
      const records = JSON.parse(result.trim());
      
      res.json({
        channel: channelName,
        date,
        records,
        count: records.length,
        status: 'OK'
      });
    } catch (pyErr) {
      fs.unlinkSync(tmpScript);
      throw pyErr;
    }
    
  } catch (err) {
    console.error('Error loading carrier power:', err);
    res.status(500).json({ error: err.message });
  }
});

// ============================================================================
// HELPER FUNCTIONS - NEW ANALYTICS
// ============================================================================

/**
 * Get comprehensive timing status across all channels
 */
async function getTimingStatus(paths) {
  const channels = config.recorder?.channels || [];
  const enabledChannels = channels.filter(ch => ch.enabled);
  
  let primaryReference = null;
  let channelBreakdown = {
    tone_locked: 0,
    ntp_synced: 0,
    interpolated: 0,
    wall_clock: 0
  };
  let recentAdoptions = [];
  
  // Scan all enabled channels for timing status
  for (const channel of enabledChannels) {
    const channelName = channel.description || `Channel ${channel.ssrc}`;
    // Convert "WWV 10 MHz" to "wwv10" for state file naming
    const channelKey = channelName.toLowerCase().replace(' mhz', '').replace(/ /g, '');
    const stateFile = join(paths.getStateDir(), `analytics-${channelKey}.json`);
    
    if (!fs.existsSync(stateFile)) continue;
    
    try {
      const content = fs.readFileSync(stateFile, 'utf8');
      const state = JSON.parse(content);
      
      // Extract time_snap info
      if (state.time_snap) {
        // Use established_at if last_update not available
        const lastUpdate = state.time_snap.last_update || state.time_snap.established_at;
        const ageSeconds = Date.now() / 1000 - lastUpdate;
        const source = state.time_snap.source || 'UNKNOWN';
        const confidence = state.time_snap.confidence || 0;
        
        // Classify timing quality
        // Source values: wwv_startup, chu_startup, wwvh_startup, ntp, wall_clock, archive_time_snap
        // Check if source is tone-based (contains wwv or chu)
        const sourceLower = source.toLowerCase();
        const isToneSource = sourceLower.includes('wwv') || sourceLower.includes('chu');
        
        let timingClass;
        if (isToneSource && ageSeconds < 300) {
          // Fresh tone detection (< 5 minutes) = actively tone-locked
          timingClass = 'TONE_LOCKED';
          channelBreakdown.tone_locked++;
        } else if (isToneSource && ageSeconds < 3600) {
          // Aged tone reference (5 min - 1 hour) = interpolated
          timingClass = 'INTERPOLATED';
          channelBreakdown.interpolated++;
        } else if (sourceLower === 'ntp' || sourceLower === 'ntp_synced') {
          // NTP-synced
          timingClass = 'NTP_SYNCED';
          channelBreakdown.ntp_synced++;
        } else {
          // Wall clock or very old reference
          timingClass = 'WALL_CLOCK';
          channelBreakdown.wall_clock++;
        }
        
        // Select best reference (highest confidence, newest, tone-locked preferred)
        if (!primaryReference || 
            (timingClass === 'TONE_LOCKED' && 
             (primaryReference.timing_class !== 'TONE_LOCKED' || 
              confidence > (primaryReference.confidence || 0)))) {
          primaryReference = {
            channel: channelName,
            station: state.time_snap.station || 'UNKNOWN',
            time_snap_rtp: state.time_snap.rtp_timestamp,
            time_snap_utc: new Date(state.time_snap.utc_timestamp * 1000).toISOString(),
            source: source,
            confidence: confidence,
            age_seconds: Math.round(ageSeconds),
            timing_class: timingClass
          };
        }
      }
      
      // Check for recent adoptions (if history exists)
      if (state.time_snap_history && Array.isArray(state.time_snap_history)) {
        const recentHistory = state.time_snap_history
          .filter(h => h.event_type === 'ARCHIVE_ADOPTION')
          .slice(-3); // Last 3 adoptions
        
        recentAdoptions.push(...recentHistory.map(h => ({
          timestamp: new Date(h.timestamp * 1000).toISOString(),
          channel: channelName,
          reason: h.reason || 'Archive time_snap adopted',
          improvement_ms: h.improvement_ms || null
        })));
      }
    } catch (err) {
      console.error(`Error reading state for ${channelName}:`, err);
    }
  }
  
  // Determine overall status
  let overallStatus = 'WALL_CLOCK';
  let precisionEstimateMs = 1000;
  
  if (channelBreakdown.tone_locked > 0) {
    overallStatus = 'TONE_LOCKED';
    precisionEstimateMs = 1.0;
  } else if (channelBreakdown.ntp_synced > 0) {
    overallStatus = 'NTP_SYNCED';
    precisionEstimateMs = 10.0;
  } else if (channelBreakdown.interpolated > 0) {
    overallStatus = 'INTERPOLATED';
    precisionEstimateMs = 100.0;
  }
  
  // Sort adoptions by timestamp (newest first)
  recentAdoptions.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
  
  return {
    overall_status: overallStatus,
    precision_estimate_ms: precisionEstimateMs,
    primary_reference: primaryReference,
    channel_breakdown: channelBreakdown,
    total_channels: enabledChannels.length,
    recent_adoptions: recentAdoptions.slice(0, 5), // Top 5 most recent
    last_updated: new Date().toISOString()
  };
}

/**
 * Get current tone power levels for all enabled channels
 */
async function getCurrentTonePowers(paths) {
  const channels = config.recorder?.channels || [];
  const enabledChannels = channels.filter(ch => ch.enabled);
  const result = [];
  const today = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  
  for (const channel of enabledChannels) {
    const channelName = channel.description || `Channel ${channel.ssrc}`;
    const fileChannelName = channelName.replace(/ /g, '_');
    
    // Read from combined discrimination CSV
    const csvPath = join(
      paths.getDiscriminationDir(channelName),
      `${fileChannelName}_discrimination_${today}.csv`
    );
    
    if (!fs.existsSync(csvPath)) {
      result.push({
        channel: channelName,
        tone_1000_hz_db: null,
        tone_1200_hz_db: null,
        status: 'NO_DATA'
      });
      continue;
    }
    
    try {
      // Read last line of CSV for most recent data
      const content = fs.readFileSync(csvPath, 'utf8');
      const lines = content.trim().split('\n');
      
      if (lines.length < 2) {
        result.push({
          channel: channelName,
          tone_1000_hz_db: null,
          tone_1200_hz_db: null,
          status: 'EMPTY'
        });
        continue;
      }
      
      // Parse CSV header
      const header = lines[0].split(',');
      const wwvPowerIdx = header.indexOf('wwv_power_db');
      const wwvhPowerIdx = header.indexOf('wwvh_power_db');
      const ratioIdx = header.indexOf('power_ratio_db');
      
      // Get most recent line (last non-empty line)
      const lastLine = lines[lines.length - 1];
      const fields = lastLine.split(',');
      
      const wwvPower = fields[wwvPowerIdx] ? parseFloat(fields[wwvPowerIdx]) : null;
      const wwvhPower = fields[wwvhPowerIdx] ? parseFloat(fields[wwvhPowerIdx]) : null;
      const ratio = fields[ratioIdx] ? parseFloat(fields[ratioIdx]) : null;
      
      result.push({
        channel: channelName,
        tone_1000_hz_db: wwvPower,
        tone_1200_hz_db: wwvhPower,
        ratio_db: ratio,
        status: 'OK'
      });
      
    } catch (err) {
      console.error(`Error reading tones for ${channelName}:`, err);
      result.push({
        channel: channelName,
        tone_1000_hz_db: null,
        tone_1200_hz_db: null,
        status: 'ERROR'
      });
    }
  }
  
  return {
    channels: result,
    last_updated: new Date().toISOString()
  };
}

/**
 * Load all 5 discrimination methods for a channel and date
 * 
 * Now reads from separate CSV files per method:
 * - tone_detections/{channel}_tones_{date}.csv
 * - tick_windows/{channel}_ticks_{date}.csv
 * - station_id_440hz/{channel}_440hz_{date}.csv
 * - bcd_discrimination/{channel}_bcd_{date}.csv
 * - discrimination/{channel}_discrimination_{date}.csv
 */
async function loadAllDiscriminationMethods(channelName, date, paths) {
  // Match Python's channel_dir encoding: replace spaces AND dots with underscores
  const fileChannelName = channelName.replace(/ /g, '_').replace(/\./g, '_');
  const result = {
    channel: channelName,
    date: date,
    methods: {}
  };
  
  // Helper function to parse CSV using proper parser
  const parseCSV = (filePath) => {
    if (!fs.existsSync(filePath)) {
      return { status: 'NO_DATA', records: [], count: 0 };
    }
    
    try {
      const content = fs.readFileSync(filePath, 'utf8');
      
      // Use csv-parse for proper CSV parsing (handles quoted fields, etc.)
      const records = csvParse(content, {
        columns: true,
        skip_empty_lines: true,
        relax_column_count: true,
        trim: true
      });
      
      return {
        status: 'OK',
        records: records,
        count: records.length
      };
    } catch (err) {
      console.error(`Error parsing ${filePath}:`, err);
      return { status: 'ERROR', error: err.message, records: [], count: 0 };
    }
  };
  
  // Use GRAPEPaths API for all method-specific directories (matches Python paths.py)
  
  // 1. Load 1000/1200 Hz tone detections
  const tonesPath = join(paths.getToneDetectionsDir(channelName), `${fileChannelName}_tones_${date}.csv`);
  const tonesData = parseCSV(tonesPath);
  result.methods.timing_tones = {
    status: tonesData.status,
    records: tonesData.records.map(r => ({
      timestamp_utc: r.timestamp_utc,
      station: r.station,
      frequency_hz: parseFloat(r.frequency_hz),
      tone_power_db: parseFloat(r.tone_power_db),
      snr_db: parseFloat(r.snr_db)
    })),
    count: tonesData.count
  };
  
  // 2. Load tick windows (10-sec coherent integration)
  const ticksPath = join(paths.getTickWindowsDir(channelName), `${fileChannelName}_ticks_${date}.csv`);
  const ticksData = parseCSV(ticksPath);
  result.methods.tick_windows = {
    status: ticksData.status,
    records: ticksData.records.map(r => ({
      timestamp_utc: r.timestamp_utc,
      window_second: parseInt(r.window_second),
      wwv_snr_db: parseFloat(r.wwv_snr_db),
      wwvh_snr_db: parseFloat(r.wwvh_snr_db),
      ratio_db: parseFloat(r.ratio_db),
      integration_method: r.integration_method
    })),
    count: ticksData.count
  };
  
  // 3. Load 440 Hz station ID detections
  const id440Path = join(paths.getStationId440HzDir(channelName), `${fileChannelName}_440hz_${date}.csv`);
  const id440Data = parseCSV(id440Path);
  result.methods.station_id = {
    status: id440Data.status,
    records: id440Data.records.map(r => ({
      timestamp_utc: r.timestamp_utc,
      minute_number: parseInt(r.minute_number),
      wwv_detected: r.wwv_detected === '1',
      wwvh_detected: r.wwvh_detected === '1',
      wwv_power_db: r.wwv_power_db ? parseFloat(r.wwv_power_db) : null,
      wwvh_power_db: r.wwvh_power_db ? parseFloat(r.wwvh_power_db) : null
    })),
    count: id440Data.count
  };
  
  // 3.5. Load test signal detections (minutes 8 and 44)
  const testSignalPath = join(paths.getTestSignalDir(channelName), `${fileChannelName}_test_signal_${date}.csv`);
  const testSignalData = parseCSV(testSignalPath);
  result.methods.test_signal = {
    status: testSignalData.status,
    records: testSignalData.records.map(r => ({
      timestamp_utc: r.timestamp_utc,
      minute_number: parseInt(r.minute_number),
      detected: r.detected === '1',
      station: r.station || null,
      confidence: parseFloat(r.confidence),
      multitone_score: parseFloat(r.multitone_score),
      chirp_score: parseFloat(r.chirp_score),
      snr_db: r.snr_db ? parseFloat(r.snr_db) : null
    })),
    count: testSignalData.count
  };
  
  // 4. Load BCD discrimination windows
  const bcdPath = join(paths.getBcdDiscriminationDir(channelName), `${fileChannelName}_bcd_${date}.csv`);
  const bcdData = parseCSV(bcdPath);
  result.methods.bcd = {
    status: bcdData.status,
    records: bcdData.records.map(r => ({
      timestamp_utc: r.timestamp_utc,
      window_start_sec: parseFloat(r.window_start_sec),
      wwv_amplitude: parseFloat(r.wwv_amplitude),
      wwvh_amplitude: parseFloat(r.wwvh_amplitude),
      differential_delay_ms: parseFloat(r.differential_delay_ms),
      correlation_quality: parseFloat(r.correlation_quality),
      detection_type: r.detection_type || null,
      amplitude_ratio_db: r.amplitude_ratio_db ? parseFloat(r.amplitude_ratio_db) : null
    })),
    count: bcdData.count
  };
  
  // 4.5. Load Doppler estimation (ionospheric channel characterization)
  const dopplerPath = join(paths.getDopplerDir(channelName), `${fileChannelName}_doppler_${date}.csv`);
  const dopplerData = parseCSV(dopplerPath);
  result.methods.doppler = {
    status: dopplerData.status,
    records: dopplerData.records.map(r => ({
      timestamp_utc: r.timestamp_utc,
      wwv_doppler_hz: parseFloat(r.wwv_doppler_hz),
      wwvh_doppler_hz: parseFloat(r.wwvh_doppler_hz),
      wwv_doppler_std_hz: parseFloat(r.wwv_doppler_std_hz),
      wwvh_doppler_std_hz: parseFloat(r.wwvh_doppler_std_hz),
      max_coherent_window_sec: parseFloat(r.max_coherent_window_sec),
      doppler_quality: parseFloat(r.doppler_quality),
      phase_variance_rad: parseFloat(r.phase_variance_rad),
      valid_tick_count: parseInt(r.valid_tick_count)
    })),
    count: dopplerData.count
  };
  
  // 5. Load final weighted voting results
  const discPath = join(paths.getDiscriminationDir(channelName), `${fileChannelName}_discrimination_${date}.csv`);
  const discData = parseCSV(discPath);
  result.methods.weighted_voting = {
    status: discData.status,
    records: discData.records.map(r => ({
      timestamp_utc: r.timestamp_utc,
      dominant_station: r.dominant_station,
      confidence: r.confidence,
      method_weights: r.method_weights
    })),
    count: discData.count
  };
  
  // 6. Extract 500/600 Hz ground truth from discrimination CSV
  // These are exclusive broadcast minutes where only one station transmits 500/600 Hz
  const groundTruthRecords = discData.records
    .filter(r => r.tone_500_600_detected === '1' && r.tone_500_600_ground_truth_station)
    .map(r => ({
      timestamp_utc: r.timestamp_utc,
      minute_number: parseInt(r.minute_number),
      detected: true,
      power_db: r.tone_500_600_power_db ? parseFloat(r.tone_500_600_power_db) : null,
      freq_hz: r.tone_500_600_freq_hz ? parseInt(r.tone_500_600_freq_hz) : null,
      ground_truth_station: r.tone_500_600_ground_truth_station,
      dominant_station: r.dominant_station,
      agrees: r.tone_500_600_ground_truth_station === r.dominant_station
    }));
  
  result.methods.ground_truth_500_600 = {
    status: groundTruthRecords.length > 0 ? 'OK' : 'NO_DATA',
    records: groundTruthRecords,
    count: groundTruthRecords.length,
    agreements: groundTruthRecords.filter(r => r.agrees).length,
    disagreements: groundTruthRecords.filter(r => !r.agrees).length
  };
  
  // 7. Extract harmonic power ratios from discrimination CSV (Vote 8)
  // These columns: harmonic_ratio_500_1000, harmonic_ratio_600_1200
  const harmonicRecords = discData.records
    .filter(r => r.harmonic_ratio_500_1000 || r.harmonic_ratio_600_1200)
    .map(r => ({
      timestamp_utc: r.timestamp_utc,
      minute_number: parseInt(r.minute_number),
      harmonic_ratio_500_1000: r.harmonic_ratio_500_1000 ? parseFloat(r.harmonic_ratio_500_1000) : null,
      harmonic_ratio_600_1200: r.harmonic_ratio_600_1200 ? parseFloat(r.harmonic_ratio_600_1200) : null
    }));
  
  result.methods.harmonic_ratio = {
    status: harmonicRecords.length > 0 ? 'OK' : 'NO_DATA',
    records: harmonicRecords,
    count: harmonicRecords.length
  };
  
  return result;
}

// ============================================================================
// AUDIO STREAMING API
// ============================================================================

/**
 * GET /api/v1/audio/stream/:channel
 * Start audio stream for a channel (creates AM channel with AGC)
 * Returns WebSocket URL for audio data
 */
app.get('/api/v1/audio/stream/:channel', async (req, res) => {
  const channelName = req.params.channel.replace(/_/g, ' ');
  
  console.log(`🎵 Audio stream request for channel: ${channelName}`);
  
  const frequencyHz = channelNameToFrequency(channelName);
  if (!frequencyHz) {
    return res.status(400).json({
      success: false,
      error: `Could not determine frequency for channel: ${channelName}`
    });
  }
  
  try {
    const stream = await audioProxy.startAudioStream(frequencyHz);
    
    res.json({
      success: true,
      channel: channelName,
      ssrc: stream.ssrc,
      frequency_hz: stream.frequency,
      sample_rate: stream.sampleRate,
      websocket: `ws://${req.headers.host}/api/v1/audio/ws/${stream.ssrc}`,
      multicast: `${stream.multicastAddress}:${stream.multicastPort}`
    });
  } catch (error) {
    console.error('❌ Failed to create audio stream:', error);
    res.status(500).json({
      success: false,
      error: 'Failed to create audio stream',
      details: error.message
    });
  }
});

/**
 * DELETE /api/v1/audio/stream/:ssrc
 * Stop audio stream
 */
app.delete('/api/v1/audio/stream/:ssrc', async (req, res) => {
  const ssrc = parseInt(req.params.ssrc);
  
  await audioProxy.stopAudioStream(ssrc);
  
  // Also close any WebSocket session
  const session = global.audioSessions.get(ssrc);
  if (session && session.ws) {
    try {
      session.ws.close(1000, 'Stream stopped');
    } catch (e) {}
    global.audioSessions.delete(ssrc);
  }
  
  res.json({ success: true, message: 'Stream stopped' });
});

/**
 * GET /api/v1/audio/health
 * Audio proxy health check
 */
app.get('/api/v1/audio/health', async (req, res) => {
  const streamInfo = Array.from(audioProxy.activeStreams.entries()).map(([ssrc, stream]) => ({
    ssrc,
    frequency_hz: stream.frequency,
    frequency_mhz: stream.frequency / 1000000,
    active: stream.active
  }));
  
  // Check Python/ka9q availability
  let pythonStatus = 'unknown';
  let pythonError = null;
  
  try {
    const pythonScript = `import sys; import json; 
try:
    from ka9q import RadiodControl
    print(json.dumps({'success': True}))
except Exception as e:
    print(json.dumps({'success': False, 'error': str(e)}))`;
    
    const { stdout } = await execAsync(
      `echo "${pythonScript.replace(/"/g, '\\"')}" | ${PYTHON_CMD}`,
      { timeout: 5000 }
    );
    
    const result = JSON.parse(stdout.trim());
    pythonStatus = result.success ? 'ok' : 'error';
    pythonError = result.error || null;
  } catch (e) {
    pythonStatus = 'error';
    pythonError = e.message;
  }
  
  res.json({
    status: pythonStatus === 'ok' ? 'ok' : 'degraded',
    service: 'grape-audio-proxy',
    radiod_hostname: RADIOD_HOSTNAME,
    active_streams: audioProxy.activeStreams.size,
    streams: streamInfo,
    python: {
      status: pythonStatus,
      error: pythonError
    }
  });
});

/**
 * GET /api/v1/audio/channels
 * List all channels with their audio SSRCs
 */
app.get('/api/v1/audio/channels', (req, res) => {
  try {
    const channels = paths.discoverChannels();
    const audioChannels = channels.map(channelName => {
      const frequencyHz = channelNameToFrequency(channelName);
      const audioSsrc = frequencyHz ? getAudioSSRC(frequencyHz) : null;
      const iqSsrc = frequencyHz ? Math.floor(frequencyHz) : null;
      
      // Check if stream is active
      const isActive = audioSsrc && audioProxy.activeStreams.has(audioSsrc);
      
      return {
        name: channelName,
        frequency_hz: frequencyHz,
        frequency_mhz: frequencyHz ? frequencyHz / 1000000 : null,
        iq_ssrc: iqSsrc,
        audio_ssrc: audioSsrc,
        audio_active: isActive,
        stream_url: frequencyHz ? `/api/v1/audio/stream/${channelName.replace(/ /g, '_')}` : null
      };
    });
    
    res.json({
      channels: audioChannels,
      radiod_hostname: RADIOD_HOSTNAME
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ============================================================================
// HEALTH CHECK
// ============================================================================

app.get('/health', (req, res) => {
  res.json({ 
    status: 'ok', 
    uptime: Date.now() - serverStartTime,
    version: '3.1.0'  // Bumped for audio support
  });
});

// ============================================================================
// SOLAR ZENITH API
// ============================================================================

/**
 * GET /api/v1/solar-zenith
 * Calculate solar elevation angles at WWV/WWVH path midpoints
 * Query params: date (YYYYMMDD), grid (Maidenhead grid square)
 */
app.get('/api/v1/solar-zenith', async (req, res) => {
  try {
    const { date, grid } = req.query;
    
    if (!date || !grid) {
      return res.status(400).json({ error: 'Missing required parameters: date, grid' });
    }
    
    // Validate date format
    if (!/^\d{8}$/.test(date)) {
      return res.status(400).json({ error: 'Invalid date format. Use YYYYMMDD' });
    }
    
    // Call Python calculator - use project root (parent of web-ui directory)
    const projectRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
    const pythonPath = join(projectRoot, 'venv', 'bin', 'python3');
    const scriptPath = join(projectRoot, 'src', 'signal_recorder', 'grape', 'solar_zenith_calculator.py');
    
    const cmd = `${pythonPath} ${scriptPath} --date ${date} --grid ${grid} --interval 5`;
    
    const execPromise = promisify(exec);
    const { stdout, stderr } = await execPromise(cmd, { timeout: 10000 });
    
    if (stderr) {
      console.error('Solar zenith calculator stderr:', stderr);
    }
    
    const result = JSON.parse(stdout);
    res.json(result);
    
  } catch (err) {
    console.error('Error calculating solar zenith:', err);
    res.status(500).json({ error: err.message });
  }
});

// ============================================================================
// START SERVER WITH WEBSOCKET SUPPORT
// ============================================================================

const server = app.listen(PORT, () => {
  console.log(`\n✅ Server running on http://localhost:${PORT}`);
  console.log(`📊 Summary: http://localhost:${PORT}/summary.html`);
  console.log(`🎯 Carrier Analysis: http://localhost:${PORT}/carrier.html`);
  console.log(`🔍 Health: http://localhost:${PORT}/health`);
  console.log(`🔊 Audio Streaming: WebSocket enabled`);
  console.log(`\n📡 API Endpoints:`);
  console.log(`   Summary:`);
  console.log(`     GET /api/v1/summary (aggregated)`);
  console.log(`     GET /api/v1/station/info`);
  console.log(`     GET /api/v1/system/processes`);
  console.log(`     GET /api/v1/system/continuity`);
  console.log(`     GET /api/v1/system/storage`);
  console.log(`     GET /api/v1/channels/status`);
  console.log(`   Carrier Analysis:`);
  console.log(`     GET /api/v1/carrier/quality?date=YYYYMMDD`);
  console.log(`     GET /spectrograms/{date}/{filename}`);
  console.log(`   ⏱️  Timing & Analytics:`);
  console.log(`     GET /api/v1/timing/status`);
  console.log(`     GET /api/v1/tones/current`);
  console.log(`     GET /api/v1/channels/:name/discrimination/:date/methods`);
  console.log(`   🔊 Audio Streaming:`);
  console.log(`     GET /api/v1/audio/channels`);
  console.log(`     GET /api/v1/audio/stream/:channel`);
  console.log(`     DELETE /api/v1/audio/stream/:ssrc`);
  console.log(`     GET /api/v1/audio/health`);
  console.log(`     WS /api/v1/audio/ws/:ssrc`);
  console.log(``);
});

// WebSocket server for audio streaming
const wss = new WebSocketServer({ noServer: true });

// Handle WebSocket upgrade requests
server.on('upgrade', (request, socket, head) => {
  const url = new URL(request.url, `http://${request.headers.host}`);
  
  if (url.pathname.startsWith('/api/v1/audio/ws/')) {
    const ssrc = parseInt(url.pathname.split('/')[5]);
    if (!isNaN(ssrc)) {
      console.log(`🔄 WebSocket upgrade request for audio SSRC ${ssrc}`);
      wss.handleUpgrade(request, socket, head, (ws) => {
        console.log(`✅ WebSocket upgrade successful for SSRC ${ssrc}`);
        wss.emit('connection', ws, request, ssrc);
      });
    } else {
      console.warn(`❌ Invalid SSRC in WebSocket path: ${url.pathname}`);
      socket.destroy();
    }
  } else {
    console.warn(`❌ Non-audio WebSocket path: ${url.pathname}`);
    socket.destroy();
  }
});

// Handle WebSocket connections
wss.on('connection', (ws, request, ssrc) => {
  console.log(`🎵 WebSocket audio connection for SSRC ${ssrc}`);
  
  // Close any existing session for this SSRC (handles reconnection)
  const existingSession = global.audioSessions.get(ssrc);
  if (existingSession && existingSession.ws) {
    console.log(`♻️  Replacing existing WebSocket session for SSRC ${ssrc}`);
    try {
      existingSession.ws.close(1000, 'Replaced by new connection');
    } catch (e) {}
  }
  
  const session = {
    ws,
    ssrc,
    audio_active: true  // Start active immediately
  };
  
  global.audioSessions.set(ssrc, session);
  console.log(`✅ Audio activated for SSRC ${ssrc}`);
  
  ws.on('message', (message) => {
    const msg = message.toString();
    
    if (msg.startsWith('A:')) {
      if (msg.includes('START')) {
        session.audio_active = true;
        console.log(`▶️  Audio START for SSRC ${ssrc}`);
      } else if (msg.includes('STOP')) {
        session.audio_active = false;
        console.log(`⏹️  Audio STOP for SSRC ${ssrc}`);
      }
    }
  });
  
  ws.on('close', (code, reason) => {
    console.log(`👋 WebSocket closed for SSRC ${ssrc} (code: ${code})`);
    session.audio_active = false;
    
    // Clean up after delay to allow reconnection
    setTimeout(() => {
      const currentSession = global.audioSessions.get(ssrc);
      if (currentSession === session) {
        global.audioSessions.delete(ssrc);
        console.log(`🗑️  Session cleaned up for SSRC ${ssrc}`);
      }
    }, 5000);
  });
  
  ws.on('error', (error) => {
    console.error(`❌ WebSocket error for SSRC ${ssrc}:`, error.message);
  });
});

// Handle graceful shutdown
process.on('SIGINT', () => {
  console.log('\n🛑 Shutting down GRAPE Monitoring Server...');
  audioProxy.shutdown();
  server.close();
  process.exit(0);
});

process.on('SIGTERM', () => {
  console.log('\n🛑 Received SIGTERM, shutting down...');
  audioProxy.shutdown();
  server.close();
  process.exit(0);
});
