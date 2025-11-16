#!/usr/bin/env node
/**
 * GRAPE Signal Recorder - Monitoring Server V3
 * 
 * 3-Screen Monitoring Interface:
 * 1. Summary - System status, channel status, station info
 * 2. Carrier - 10 Hz carrier analysis (9 channels)
 * 3. Discrimination - WWV/WWVH propagation analysis (4 channels)
 * 
 * Architecture:
 * - Uses centralized GRAPEPaths API for all file access
 * - RESTful API with individual + aggregated endpoints
 * - No authentication (monitoring only)
 * - No configuration editing (use TOML files directly)
 */

import express from 'express';
import fs from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import toml from 'toml';
import { exec } from 'child_process';
import { promisify } from 'util';
import { GRAPEPaths } from './grape-paths.js';

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
    callsign: config.station?.callsign || 'UNKNOWN',
    grid_square: config.station?.grid_square || 'UNKNOWN',
    receiver: config.station?.receiver_name || 'GRAPE',
    instrument_id: config.station?.instrument_id || 'not configured',
    mode: mode,
    data_root: dataRoot
  };
}

/**
 * Get core recorder status
 * Also indicates radiod status (if packets flowing, radiod is running)
 */
async function getCoreRecorderStatus(paths) {
  try {
    const statusFile = paths.getCoreStatusFile();
    
    if (!fs.existsSync(statusFile)) {
      return { 
        running: false, 
        error: 'Status file not found',
        radiod_running: false
      };
    }
    
    const content = fs.readFileSync(statusFile, 'utf8');
    const status = JSON.parse(content);
    
    // Parse ISO 8601 timestamp
    const statusTimestamp = new Date(status.timestamp).getTime() / 1000;
    const age = Date.now() / 1000 - statusTimestamp;
    const running = age < 30;
    
    // Count active channels and total packets
    const channels = status.channels || {};
    const channelsActive = Object.keys(channels).length;
    const totalPackets = Object.values(channels).reduce((sum, ch) => sum + (ch.packets_received || 0), 0);
    
    // radiod status inferred from packet flow
    const radiodRunning = running && totalPackets > 0;
    
    return {
      running,
      radiod_running: radiodRunning,
      uptime_seconds: status.uptime_seconds || 0,
      channels_active: channelsActive,
      channels_total: 9,
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
            
            if (status.uptime && status.uptime < oldestUptime) {
              oldestUptime = status.uptime;
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
  const coreStatus = await getCoreRecorderStatus(paths);
  const analyticsStatus = await getAnalyticsServiceStatus(paths);
  
  return {
    radiod: {
      running: coreStatus.radiod_running,
      uptime_seconds: coreStatus.running ? coreStatus.uptime_seconds : 0,
      method: 'inferred_from_core_recorder'
    },
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
      return {
        data_span: {
          start: new Date(now * 1000).toISOString(),
          end: new Date(now * 1000).toISOString(),
          duration_seconds: 0
        },
        gaps: [],
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
            systemGaps.push({
              start: new Date(gapStart * 1000).toISOString(),
              end: new Date(gapEnd * 1000).toISOString(),
              duration_seconds: gapEnd - gapStart,
              reason: (gapEnd - gapStart) > 3600 ? 'Planned maintenance' : 'System downtime'
            });
          }
        }
      }
    }
    
    // Calculate totals
    const totalDowntime = systemGaps.reduce((sum, gap) => sum + gap.duration_seconds, 0);
    const spanDuration = globalNewest - globalOldest;
    const downtimePercentage = spanDuration > 0 ? (totalDowntime / spanDuration) * 100 : 0;
    
    return {
      data_span: {
        start: new Date(globalOldest * 1000).toISOString(),
        end: new Date(globalNewest * 1000).toISOString(),
        duration_seconds: spanDuration
      },
      gaps: systemGaps.slice(-5), // Return only 5 most recent gaps
      total_downtime_seconds: totalDowntime,
      downtime_percentage: downtimePercentage
    };
  } catch (err) {
    console.error('Error calculating continuity:', err);
    const now = Date.now() / 1000;
    return {
      data_span: {
        start: new Date(now * 1000).toISOString(),
        end: new Date(now * 1000).toISOString(),
        duration_seconds: 0
      },
      gaps: [],
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
          if (channelData?.time_snap?.established) {
            const age = Date.now() / 1000 - channelData.time_snap.utc_timestamp;
            timeSnapAge = age;
            
            if (age < 10800) {
              // time_snap within 3 hours = tone-locked
              // (Propagation varies naturally, but time_snap remains scientifically valid)
              timeBasis = 'TONE_LOCKED';
            } else if (ntpStatus.synchronized) {
              // Very aged time_snap (>3 hours), fall back to NTP if available
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
 * Get carrier quality metrics for all channels on a specific date
 */
async function getCarrierQuality(paths, date) {
  const channels = paths.discoverChannels();
  const channelQuality = [];
  
  for (const channelName of channels) {
    try {
      const statusFile = paths.getAnalyticsStatusFile(channelName);
      let quality = {
        name: channelName,
        completeness_pct: null,
        timing_quality: 'WALL_CLOCK',
        time_snap_age_minutes: null,
        snr_db: null,
        packet_loss_pct: null,
        upload_status: 'unknown',
        upload_lag_seconds: null,
        alerts: [],
        spectrogram_url: `/spectrograms/${date}/${channelName.replace(/ /g, '_')}_${date}_carrier_spectrogram.png`
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
          
          // Timing quality
          if (channelData.time_snap && channelData.time_snap.established) {
            const ageMinutes = (Date.now() / 1000 - channelData.time_snap.utc_timestamp) / 60;
            quality.time_snap_age_minutes = Math.round(ageMinutes);
            
            if (ageMinutes < 5) {
              quality.timing_quality = 'TONE_LOCKED';
            } else {
              const ntpStatus = await getNTPStatus();
              quality.timing_quality = ntpStatus.synchronized ? 'NTP_SYNCED' : 'WALL_CLOCK';
            }
          } else {
            const ntpStatus = await getNTPStatus();
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
 * List dates with available spectrograms
 */
app.get('/api/v1/carrier/available-dates', async (req, res) => {
  try {
    const spectrogramsRoot = paths.getSpectrogramsRoot();
    const dates = [];
    
    if (fs.existsSync(spectrogramsRoot)) {
      const entries = fs.readdirSync(spectrogramsRoot);
      
      for (const entry of entries) {
        // Check if it's a valid YYYYMMDD directory
        if (/^\d{8}$/.test(entry)) {
          const datePath = join(spectrogramsRoot, entry);
          const stat = fs.statSync(datePath);
          
          if (stat.isDirectory()) {
            // Check if directory has any PNG files
            const files = fs.readdirSync(datePath);
            const hasPngs = files.some(f => f.endsWith('.png'));
            
            if (hasPngs) {
              // Format as YYYY-MM-DD for display
              const formatted = `${entry.slice(0, 4)}-${entry.slice(4, 6)}-${entry.slice(6, 8)}`;
              dates.push({
                date: entry,
                formatted: formatted,
                count: files.filter(f => f.endsWith('.png')).length
              });
            }
          }
        }
      }
    }
    
    // Sort descending (most recent first)
    dates.sort((a, b) => b.date.localeCompare(a.date));
    
    res.json({ dates });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /api/v1/channels/:channelName/discrimination/:date
 * Get discrimination time-series data for a channel and date
 */
app.get('/api/v1/channels/:channelName/discrimination/:date', async (req, res) => {
  try {
    const { channelName, date } = req.params;
    
    // Map channel names to their actual directory names
    const dirMap = {
      'WWV 2.5 MHz': 'WWV_2.5_MHz',
      'WWV 5 MHz': 'WWV_5_MHz',
      'WWV 10 MHz': 'WWV_10_MHz',
      'WWV 15 MHz': 'WWV_15_MHz'
    };
    
    const channelDirName = dirMap[channelName] || channelName.replace(/ /g, '_');
    const fileChannelName = channelName.replace(/ /g, '_');
    const fileName = `${fileChannelName}_discrimination_${date}.csv`;
    
    // Use GRAPEPaths to get discrimination file path
    const filePath = join(paths.getDiscriminationDir(channelName), fileName);
    
    // Check if file exists
    if (!fs.existsSync(filePath)) {
      return res.json({
        date: date,
        channel: channelName,
        data: [],
        message: 'No data for this date'
      });
    }
    
    // Read CSV file
    const csvContent = fs.readFileSync(filePath, 'utf8');
    const lines = csvContent.trim().split('\n');
    
    // Parse CSV (skip header)
    // CSV format: timestamp_utc,minute_timestamp,minute_number,wwv_detected,wwvh_detected,
    //             wwv_power_db,wwvh_power_db,power_ratio_db,differential_delay_ms,
    //             tone_440hz_wwv_detected,tone_440hz_wwv_power_db,
    //             tone_440hz_wwvh_detected,tone_440hz_wwvh_power_db,
    //             dominant_station,confidence
    const data = [];
    for (let i = 1; i < lines.length; i++) {
      const parts = lines[i].split(',');
      if (parts.length >= 15) {
        // New format with 440 Hz analysis (15 fields)
        let timestamp = parts[0].trim();
        if (timestamp.endsWith('+00:00')) {
          timestamp = timestamp.replace('+00:00', 'Z');
        }
        
        data.push({
          timestamp_utc: timestamp,
          minute_timestamp: parseInt(parts[1]),
          minute_number: parseInt(parts[2]),
          wwv_detected: parts[3] === '1',
          wwvh_detected: parts[4] === '1',
          wwv_snr_db: parseFloat(parts[5]),
          wwvh_snr_db: parseFloat(parts[6]),
          power_ratio_db: parseFloat(parts[7]),
          differential_delay_ms: parts[8] !== '' ? parseFloat(parts[8]) : null,
          tone_440hz_wwv_detected: parts[9] === '1',
          tone_440hz_wwv_power_db: parts[10] !== '' ? parseFloat(parts[10]) : null,
          tone_440hz_wwvh_detected: parts[11] === '1',
          tone_440hz_wwvh_power_db: parts[12] !== '' ? parseFloat(parts[12]) : null,
          dominant_station: parts[13],
          confidence: parts[14]
        });
      } else if (parts.length >= 10) {
        // Old format without 440 Hz analysis (10 fields) - for backwards compatibility
        let timestamp = parts[0].trim();
        if (timestamp.endsWith('+00:00')) {
          timestamp = timestamp.replace('+00:00', 'Z');
        }
        
        data.push({
          timestamp_utc: timestamp,
          minute_timestamp: parseInt(parts[1]),
          minute_number: null,
          wwv_detected: parts[2] === '1',
          wwvh_detected: parts[3] === '1',
          wwv_snr_db: parseFloat(parts[4]),
          wwvh_snr_db: parseFloat(parts[5]),
          power_ratio_db: parseFloat(parts[6]),
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
    
    res.json({
      date: date,
      channel: channelName,
      data: data,
      count: data.length
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
 * GET /spectrograms/{date}/{filename}
 * Serve spectrogram PNG files
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

// ============================================================================
// HEALTH CHECK
// ============================================================================

app.get('/health', (req, res) => {
  res.json({ 
    status: 'ok', 
    uptime: Date.now() - serverStartTime,
    version: '3.0.0'
  });
});

// ============================================================================
// START SERVER
// ============================================================================

app.listen(PORT, () => {
  console.log(`\n✅ Server running on http://localhost:${PORT}`);
  console.log(`📊 Summary: http://localhost:${PORT}/summary.html`);
  console.log(`🎯 Carrier Analysis: http://localhost:${PORT}/carrier.html`);
  console.log(`🔍 Health: http://localhost:${PORT}/health`);
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
  console.log(``);
});
