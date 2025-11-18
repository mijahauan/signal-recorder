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
 * Get radiod status from dedicated health monitor
 */
async function getRadiodStatus(paths) {
  try {
    const radiodStatusFile = join(paths.getStateDir(), 'radiod-status.json');
    
    if (!fs.existsSync(radiodStatusFile)) {
      // Fallback: try to detect radiod process directly
      try {
        const { execSync } = require('child_process');
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
  
  // Check NTP status once for all channels
  const ntpStatus = await getNTPStatus();
  
  // Group channels by base frequency to show both versions
  const channelGroups = {};
  for (const channelName of channels) {
    const baseName = channelName.replace(/ carrier$/, '');
    if (!channelGroups[baseName]) {
      channelGroups[baseName] = { wide: null, carrier: null };
    }
    if (channelName.includes('carrier')) {
      channelGroups[baseName].carrier = channelName;
    } else {
      channelGroups[baseName].wide = channelName;
    }
  }
  
  // Process each base frequency (show both wide and carrier versions)
  for (const channelName of channels) {
    try {
      // Detect if this is a carrier channel
      const isCarrierChannel = channelName.includes('carrier');
      
      const statusFile = paths.getAnalyticsStatusFile(channelName);
      
      // Construct spectrogram URL with new directory structure
      // Wide channels: wide-decimated/WWV_5_MHz_10Hz_from_16kHz.png
      // Carrier channels: native-carrier/WWV_5_MHz_carrier_10Hz_from_200Hz.png
      const safe_channel_name = channelName.replace(/ /g, '_');
      const subdirectory = isCarrierChannel ? 'native-carrier' : 'wide-decimated';
      const spectrogramFilename = isCarrierChannel 
        ? `${safe_channel_name}_10Hz_from_200Hz.png`
        : `${safe_channel_name}_10Hz_from_16kHz.png`;
      
      let quality = {
        name: channelName,
        channel_type: isCarrierChannel ? 'carrier' : 'wide',
        sample_rate: isCarrierChannel ? '200 Hz (native)' : '16 kHz (decimated)',
        source_type: isCarrierChannel ? 'Native 200 Hz carrier' : 'Wide 16 kHz decimated',
        completeness_pct: null,
        timing_quality: 'WALL_CLOCK',
        time_snap_age_minutes: null,
        snr_db: null,
        packet_loss_pct: null,
        upload_status: 'unknown',
        upload_lag_seconds: null,
        alerts: [],
        spectrogram_url: `/spectrograms/${date}/${subdirectory}/${spectrogramFilename}`
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
          if (isCarrierChannel) {
            // Carrier channels use NTP timing (no tone detection at ~98 Hz bandwidth)
            quality.timing_quality = ntpStatus.synchronized ? 'NTP_SYNCED' : 'WALL_CLOCK';
            quality.time_snap_age_minutes = null; // Not applicable
          } else {
            // Wide channels use time_snap from WWV tone detection
            if (channelData.time_snap && channelData.time_snap.established) {
              const ageMinutes = (Date.now() / 1000 - channelData.time_snap.utc_timestamp) / 60;
              quality.time_snap_age_minutes = Math.round(ageMinutes);
              
              if (ageMinutes < 5) {
                quality.timing_quality = 'GPS_LOCKED';
              } else {
                quality.timing_quality = ntpStatus.synchronized ? 'NTP_SYNCED' : 'WALL_CLOCK';
              }
            } else {
              quality.timing_quality = ntpStatus.synchronized ? 'NTP_SYNCED' : 'WALL_CLOCK';
            }
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
      } else if (isCarrierChannel) {
        // Carrier channels may not have analytics status files yet
        // Set timing based on NTP for now
        quality.timing_quality = ntpStatus.synchronized ? 'NTP_SYNCED' : 'WALL_CLOCK';
        quality.alerts.push({
          severity: 'info',
          type: 'carrier_channel',
          message: 'Carrier channel (~98 Hz, Doppler analysis)'
        });
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
            // Check if directory has any PNG files (including subdirectories)
            let pngCount = 0;
            const checkForPngs = (dir) => {
              const items = fs.readdirSync(dir);
              for (const item of items) {
                const itemPath = join(dir, item);
                const itemStat = fs.statSync(itemPath);
                if (itemStat.isDirectory()) {
                  checkForPngs(itemPath);  // Recursive check subdirectories
                } else if (item.endsWith('.png')) {
                  pngCount++;
                }
              }
            };
            checkForPngs(datePath);
            
            if (pngCount > 0) {
              // Format as YYYY-MM-DD for display
              const formatted = `${entry.slice(0, 4)}-${entry.slice(4, 6)}-${entry.slice(6, 8)}`;
              dates.push({
                date: entry,
                formatted: formatted,
                count: pngCount
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
          
          if (!channelData[channelName]) {
            channelData[channelName] = {};
          }
          
          // Merge analytics data
          Object.assign(channelData[channelName], {
            wwvDetections: analyticsStatus.tone_detections?.wwv || 0,
            wwvhDetections: analyticsStatus.tone_detections?.wwvh || 0,
            chuDetections: analyticsStatus.tone_detections?.chu || 0,
            npzProcessed: analyticsStatus.npz_files_processed || 0,
            digitalRfSamples: analyticsStatus.digital_rf?.samples_written || 0
          });
          
          // Track time_snap status
          if (analyticsStatus.time_snap && analyticsStatus.time_snap.established && !timeSnapStatus) {
            timeSnapStatus = {
              established: true,
              source: channelName,
              station: analyticsStatus.time_snap.station,
              confidence: analyticsStatus.time_snap.confidence,
              age: analyticsStatus.time_snap.age_minutes,
              status: analyticsStatus.time_snap.source
            };
          }
        } catch (err) {
          // Skip invalid status file
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
