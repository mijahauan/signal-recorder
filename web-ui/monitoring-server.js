#!/usr/bin/env node
/**
 * GRAPE Signal Recorder - Simplified Monitoring Server
 * 
 * A clean, authentication-free monitoring interface
 * Focused on: Timing & Quality Dashboard
 * 
 * No configuration editing - users edit TOML files directly
 * No authentication - monitoring only
 */

import express from 'express';
import fs from 'fs';
import { join } from 'path';
import { fileURLToPath } from 'url';
import { parse } from 'csv-parse/sync';
import toml from 'toml';
import { exec, spawn } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

// Track ongoing spectrogram generation jobs
const spectrogramJobs = new Map(); // jobId -> { status, type, date, progress, error, startTime }

const __dirname = join(fileURLToPath(import.meta.url), '..');
const app = express();
const PORT = 3000;

// Determine install directory
const installDir = process.env.GRAPE_INSTALL_DIR || join(__dirname, '..');

// Load config file - same one recorder uses
const configPath = process.env.GRAPE_CONFIG || join(installDir, 'config/grape-config.toml');
let config = {};
let dataRoot = join(process.env.HOME, 'grape-data'); // Fallback
let mode = 'test';

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
  
  console.log('📊 GRAPE Monitoring Server');
  console.log('📁 Config file:', configPath);
  console.log(mode === 'production' ? '🚀 Mode: PRODUCTION' : '🧪 Mode: TEST');
  console.log('📁 Data root:', dataRoot);
  console.log('📡 Station:', config.station?.callsign, config.station?.grid_square);
} catch (err) {
  console.error('⚠️  Failed to load config, using defaults:', err.message);
  console.log('📊 GRAPE Monitoring Server (fallback mode)');
  console.log('📁 Data root:', dataRoot);
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

// Server start time for uptime tracking
const serverStartTime = Date.now();

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

/**
 * Get available data range by scanning NPZ files
 */
async function getAvailableDataRange() {
  const archivesDir = join(dataRoot, 'archives');
  
  if (!fs.existsSync(archivesDir)) {
    const now = Date.now() / 1000;
    return { oldest: now, newest: now };
  }
  
  let oldestTimestamp = Infinity;
  let newestTimestamp = 0;
  
  try {
    // Scan all channel directories
    const channelDirs = fs.readdirSync(archivesDir, { withFileTypes: true })
      .filter(d => d.isDirectory())
      .map(d => join(archivesDir, d.name));
    
    for (const channelDir of channelDirs) {
      if (!fs.existsSync(channelDir)) continue;
      
      const npzFiles = fs.readdirSync(channelDir)
        .filter(f => f.endsWith('.npz'))
        .map(f => join(channelDir, f));
      
      for (const npzFile of npzFiles) {
        try {
          // Extract timestamp from filename: YYYYMMDDTHHMMSSZ_freq_iq.npz
          const basename = npzFile.split('/').pop();
          const match = basename.match(/(\d{8}T\d{6})Z/);
          
          if (match) {
            const timestamp = match[1];
            // Parse: 20241111T112400
            const year = parseInt(timestamp.substr(0, 4));
            const month = parseInt(timestamp.substr(4, 2)) - 1;
            const day = parseInt(timestamp.substr(6, 2));
            const hour = parseInt(timestamp.substr(9, 2));
            const minute = parseInt(timestamp.substr(11, 2));
            const second = parseInt(timestamp.substr(13, 2));
            
            const date = new Date(Date.UTC(year, month, day, hour, minute, second));
            const unixTime = date.getTime() / 1000;
            
            if (unixTime < oldestTimestamp) oldestTimestamp = unixTime;
            if (unixTime > newestTimestamp) newestTimestamp = unixTime;
          }
        } catch (err) {
          // Skip files we can't parse
        }
      }
    }
  } catch (error) {
    console.error('Error scanning NPZ files:', error);
  }
  
  // If no files found, return current time
  if (oldestTimestamp === Infinity || newestTimestamp === 0) {
    const now = Date.now() / 1000;
    return { oldest: now, newest: now };
  }
  
  return {
    oldest: oldestTimestamp,
    newest: newestTimestamp
  };
}

/**
 * Calculate continuity metrics and detect gaps
 */
async function calculateContinuity(startTime, endTime) {
  const archivesDir = join(dataRoot, 'archives');
  const gaps = [];
  
  if (!fs.existsSync(archivesDir)) {
    return {
      metrics: {
        uptime_pct: 0,
        capture_seconds: 0,
        downtime_seconds: endTime - startTime,
        gap_count: 1
      },
      gaps: [{
        start: new Date(startTime * 1000).toISOString(),
        end: new Date(endTime * 1000).toISOString(),
        duration_seconds: endTime - startTime,
        cause: 'no_data_available',
        channels_affected: 0,
        severity: 'critical'
      }]
    };
  }
  
  try {
    // Get all NPZ files across all channels in time range
    const allTimestamps = new Set();
    const channelDirs = fs.readdirSync(archivesDir, { withFileTypes: true })
      .filter(d => d.isDirectory())
      .map(d => join(archivesDir, d.name));
    
    const totalChannels = channelDirs.length;
    
    for (const channelDir of channelDirs) {
      if (!fs.existsSync(channelDir)) continue;
      
      const npzFiles = fs.readdirSync(channelDir)
        .filter(f => f.endsWith('.npz'));
      
      for (const npzFile of npzFiles) {
        try {
          const match = npzFile.match(/(\d{8}T\d{6})Z/);
          if (match) {
            const timestamp = match[1];
            const year = parseInt(timestamp.substr(0, 4));
            const month = parseInt(timestamp.substr(4, 2)) - 1;
            const day = parseInt(timestamp.substr(6, 2));
            const hour = parseInt(timestamp.substr(9, 2));
            const minute = parseInt(timestamp.substr(11, 2));
            const second = parseInt(timestamp.substr(13, 2));
            
            const date = new Date(Date.UTC(year, month, day, hour, minute, second));
            const unixTime = date.getTime() / 1000;
            
            if (unixTime >= startTime && unixTime <= endTime) {
              allTimestamps.add(unixTime);
            }
          }
        } catch (err) {
          // Skip files we can't parse
        }
      }
    }
    
    // Sort timestamps to detect gaps
    const sortedTimestamps = Array.from(allTimestamps).sort((a, b) => a - b);
    
    if (sortedTimestamps.length === 0) {
      // No data in range
      return {
        metrics: {
          uptime_pct: 0,
          capture_seconds: 0,
          downtime_seconds: endTime - startTime,
          gap_count: 1
        },
        gaps: [{
          start: new Date(startTime * 1000).toISOString(),
          end: new Date(endTime * 1000).toISOString(),
          duration_seconds: endTime - startTime,
          cause: 'no_data_in_range',
          channels_affected: totalChannels,
          severity: 'critical'
        }]
      };
    }
    
    // Detect gaps (expect files every 60 seconds)
    const expectedInterval = 60; // 1 minute per NPZ file
    const gapThreshold = 120; // Consider >2 minutes a gap
    
    for (let i = 1; i < sortedTimestamps.length; i++) {
      const gap = sortedTimestamps[i] - sortedTimestamps[i - 1];
      
      if (gap > gapThreshold) {
        const gapDuration = gap - expectedInterval;
        gaps.push({
          start: new Date((sortedTimestamps[i - 1] + expectedInterval) * 1000).toISOString(),
          end: new Date(sortedTimestamps[i] * 1000).toISOString(),
          duration_seconds: gapDuration,
          cause: determineCause(gapDuration),
          channels_affected: totalChannels,
          severity: gapDuration > 600 ? 'critical' : (gapDuration > 60 ? 'warning' : 'minor')
        });
      }
    }
    
    // Calculate metrics
    const totalDuration = endTime - startTime;
    const totalGapDuration = gaps.reduce((sum, g) => sum + g.duration_seconds, 0);
    const captureDuration = totalDuration - totalGapDuration;
    
    return {
      metrics: {
        uptime_pct: (captureDuration / totalDuration) * 100,
        capture_seconds: captureDuration,
        downtime_seconds: totalGapDuration,
        gap_count: gaps.length
      },
      gaps: gaps.slice(0, 50) // Limit to 50 most recent gaps
    };
  } catch (error) {
    console.error('Error calculating continuity:', error);
    return {
      metrics: {
        uptime_pct: 0,
        capture_seconds: 0,
        downtime_seconds: endTime - startTime,
        gap_count: 0
      },
      gaps: []
    };
  }
}

/**
 * Determine likely cause of gap based on duration
 */
function determineCause(durationSeconds) {
  if (durationSeconds < 120) {
    return 'network_packet_loss';
  } else if (durationSeconds < 600) {
    return 'brief_interruption';
  } else if (durationSeconds < 3600) {
    return 'service_restart';
  } else {
    return 'extended_outage';
  }
}

/**
 * Get disk usage for a path
 */
async function getDiskUsage(path) {
  try {
    const { stdout } = await execAsync(`df -k "${path}" | tail -1`);
    const parts = stdout.trim().split(/\s+/);
    const totalKB = parseInt(parts[1]);
    const usedKB = parseInt(parts[2]);
    const availKB = parseInt(parts[3]);
    
    return {
      total_gb: (totalKB / (1024 * 1024)).toFixed(2),
      used_gb: (usedKB / (1024 * 1024)).toFixed(2),
      free_gb: (availKB / (1024 * 1024)).toFixed(2),
      percent_used: ((usedKB / totalKB) * 100).toFixed(1)
    };
  } catch (error) {
    console.error('Failed to get disk usage:', error);
    return null;
  }
}

/**
 * Check if recorder daemon is running
 */
async function getRecorderStatus() {
  const possibleStatusFiles = [
    join(dataRoot, 'status', 'recording-stats.json'),
    '/tmp/signal-recorder-stats.json',
    '/var/lib/signal-recorder/status/recording-stats.json'
  ];
  
  for (const file of possibleStatusFiles) {
    if (fs.existsSync(file)) {
      try {
        const stats = fs.statSync(file);
        const ageSeconds = (Date.now() - stats.mtimeMs) / 1000;
        
        // Consider running if file updated in last 5 minutes
        if (ageSeconds < 300) {
          const statusData = JSON.parse(fs.readFileSync(file, 'utf8'));
          return {
            running: true,
            uptime_seconds: statusData.uptime_seconds || 0,
            pid: statusData.pid || null,
            mode: mode,
            status_file: file,
            last_update: new Date(stats.mtime).toISOString()
          };
        }
      } catch (error) {
        console.error(`Error reading status file ${file}:`, error);
      }
    }
  }
  
  return {
    running: false,
    message: 'No recent status file found (daemon may be stopped)'
  };
}

/**
 * Get channel status from live stats
 */
async function getChannelStatus() {
  const possibleStatusFiles = [
    join(dataRoot, 'status', 'recording-stats.json'),
    '/tmp/signal-recorder-stats.json',
    '/var/lib/signal-recorder/status/recording-stats.json'
  ];
  
  for (const file of possibleStatusFiles) {
    if (fs.existsSync(file)) {
      try {
        const statusData = JSON.parse(fs.readFileSync(file, 'utf8'));
        const recorders = statusData.recorders || {};
        const channels = Object.values(recorders);
        
        return {
          total: channels.length,
          active: channels.filter(c => c.total_packets > 0).length,
          errors: 0
        };
      } catch (error) {
        console.error(`Error reading status file ${file}:`, error);
      }
    }
  }
  
  // Fallback to configured channels
  const configuredChannels = config.recorder?.channels?.length || 0;
  return {
    total: configuredChannels,
    active: 0,
    errors: 0
  };
}

/**
 * Get time_snap status
 */
async function getTimeSnapStatus() {
  const possibleStatusFiles = [
    join(dataRoot, 'status', 'recording-stats.json'),
    '/tmp/signal-recorder-stats.json',
    '/var/lib/signal-recorder/status/recording-stats.json'
  ];
  
  for (const file of possibleStatusFiles) {
    if (fs.existsSync(file)) {
      try {
        const statusData = JSON.parse(fs.readFileSync(file, 'utf8'));
        const recorders = statusData.recorders || {};
        
        // Find first WWV/CHU channel with time_snap established
        for (const rec of Object.values(recorders)) {
          if (rec.time_snap_established) {
            return {
              established: true,
              source: rec.channel_name,
              age_minutes: rec.time_snap_age_minutes || 0,
              confidence: rec.time_snap_source === 'wwv_verified' ? 0.95 : 0.8
            };
          }
        }
      } catch (error) {
        console.error(`Error reading status file ${file}:`, error);
      }
    }
  }
  
  return {
    established: false,
    message: 'No WWV time_snap established yet'
  };
}

/**
 * Get recent errors from daemon log
 */
async function getRecentErrors(limit = 10) {
  const logFile = join(dataRoot, '../logs/signal-recorder.log');
  
  if (!fs.existsSync(logFile)) {
    return [];
  }
  
  try {
    // Get last 100 lines and filter for errors/warnings
    const { stdout } = await execAsync(`tail -100 "${logFile}" | grep -E "(ERROR|WARNING)" | tail -${limit}`);
    const lines = stdout.trim().split('\n').filter(l => l.length > 0);
    
    return lines.map(line => {
      // Parse log line: timestamp level message
      const match = line.match(/(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})[\s,]+(ERROR|WARNING)[\s:]+(.+)/);
      if (match) {
        return {
          timestamp: match[1],
          level: match[2].toLowerCase(),
          message: match[3].trim()
        };
      }
      return {
        timestamp: new Date().toISOString(),
        level: 'unknown',
        message: line
      };
    });
  } catch (error) {
    // No errors found or command failed
    return [];
  }
}

/**
 * Read Core Recorder status from JSON file (V2 Architecture)
 */
async function getCoreRecorderStatus() {
  try {
    const statusFile = join(dataRoot, 'status', 'core-recorder-status.json');
    if (!fs.existsSync(statusFile)) {
      return { running: false, error: 'Status file not found' };
    }
    
    // Check file age (stale if > 30 seconds old)
    const stats = fs.statSync(statusFile);
    const ageSeconds = (Date.now() - stats.mtimeMs) / 1000;
    
    const content = fs.readFileSync(statusFile, 'utf8');
    const status = JSON.parse(content);
    
    return {
      running: ageSeconds < 30,
      stale: ageSeconds >= 30,
      age_seconds: ageSeconds,
      ...status
    };
  } catch (error) {
    console.error('Failed to read core recorder status:', error);
    return { running: false, error: error.message };
  }
}

/**
 * Read Analytics Service status from JSON files (V2 Architecture - per channel)
 */
async function getAnalyticsServiceStatus() {
  try {
    // V2 analytics writes per-channel status files
    const analyticsDir = join(dataRoot, 'analytics');
    if (!fs.existsSync(analyticsDir)) {
      return { running: false, error: 'Analytics directory not found' };
    }
    
    // Aggregate status from all channel directories
    const channelDirs = fs.readdirSync(analyticsDir, { withFileTypes: true })
      .filter(d => d.isDirectory())
      .map(d => d.name);
    
    const aggregated = {
      running: false,
      channels: {},
      overall: {
        channels_processing: 0,
        total_npz_processed: 0,
        pending_npz_files: 0
      },
      uptime_seconds: 0
    };
    
    let newestAge = Infinity;
    
    for (const channelDir of channelDirs) {
      const statusFile = join(analyticsDir, channelDir, 'status', 'analytics-service-status.json');
      if (!fs.existsSync(statusFile)) continue;
      
      try {
        // Check file age
        const stats = fs.statSync(statusFile);
        const ageSeconds = (Date.now() - stats.mtimeMs) / 1000;
        if (ageSeconds < newestAge) newestAge = ageSeconds;
        
        const content = fs.readFileSync(statusFile, 'utf8');
        const status = JSON.parse(content);
        
        // Merge channel data
        if (status.channels) {
          Object.assign(aggregated.channels, status.channels);
        }
        
        // Aggregate overall stats
        if (status.overall) {
          aggregated.overall.channels_processing += status.overall.channels_processing || 0;
          aggregated.overall.total_npz_processed += status.overall.total_npz_processed || 0;
          aggregated.overall.pending_npz_files += status.overall.pending_npz_files || 0;
        }
        
        // Use max uptime
        if (status.uptime_seconds > aggregated.uptime_seconds) {
          aggregated.uptime_seconds = status.uptime_seconds;
        }
      } catch (err) {
        console.error(`Failed to read ${statusFile}:`, err);
      }
    }
    
    // Consider running if we have any recent status files
    aggregated.running = newestAge < 30 && Object.keys(aggregated.channels).length > 0;
    aggregated.stale = newestAge >= 30;
    aggregated.age_seconds = newestAge;
    
    return aggregated;
  } catch (error) {
    console.error('Failed to read analytics service status:', error);
    return { running: false, error: error.message };
  }
}

// ============================================================================
// API v1 ENDPOINTS (New versioned API)
// ============================================================================

/**
 * System status - comprehensive health check (V2 Dual-Service Architecture)
 */
app.get('/api/v1/system/status', async (req, res) => {
  try {
    const coreStatus = await getCoreRecorderStatus();
    const analyticsStatus = await getAnalyticsServiceStatus();
    const diskUsage = await getDiskUsage(dataRoot);
    const recentErrors = await getRecentErrors(5);
    
    // Aggregate time_snap from analytics service (first channel with time_snap)
    let timeSnapStatus = { established: false };
    if (analyticsStatus.running && analyticsStatus.channels) {
      for (const [channelName, channelData] of Object.entries(analyticsStatus.channels)) {
        if (channelData.time_snap && channelData.time_snap.established) {
          timeSnapStatus = {
            established: true,
            source: channelData.time_snap.station,
            channel: channelName,
            confidence: channelData.time_snap.confidence,
            age_minutes: channelData.time_snap.age_minutes
          };
          break;
        }
      }
    }
    
    // Calculate overall completeness from core recorder
    let overallCompleteness = 0;
    if (coreStatus.running && coreStatus.overall) {
      const total = coreStatus.overall.total_packets_received || 0;
      const gaps = coreStatus.overall.total_gaps_detected || 0;
      overallCompleteness = total > 0 ? ((total - gaps) / total * 100).toFixed(1) : 0;
    }
    
    res.json({
      timestamp: new Date().toISOString(),
      services: {
        core_recorder: {
          running: coreStatus.running,
          stale: coreStatus.stale,
          uptime_seconds: coreStatus.uptime_seconds || 0,
          channels_active: coreStatus.overall?.channels_active || 0,
          channels_total: coreStatus.overall?.channels_total || 0,
          npz_files_written: coreStatus.overall?.total_npz_written || 0,
          packets_received: coreStatus.overall?.total_packets_received || 0,
          gaps_detected: coreStatus.overall?.total_gaps_detected || 0
        },
        analytics_service: {
          running: analyticsStatus.running,
          stale: analyticsStatus.stale,
          uptime_seconds: analyticsStatus.uptime_seconds || 0,
          npz_processed: analyticsStatus.overall?.total_npz_processed || 0,
          pending_files: analyticsStatus.overall?.pending_npz_files || 0
        }
      },
      radiod: {
        connected: coreStatus.running,
        status_address: config.ka9q?.status_address || 'unknown'
      },
      channels: coreStatus.channels || {},
      time_snap: timeSnapStatus,
      quality: {
        overall_completeness_pct: parseFloat(overallCompleteness),
        period: 'current'
      },
      data_paths: {
        archive: join(dataRoot, 'archives'),
        analytics: join(dataRoot, 'analytics'),
        upload: config.recorder?.upload_dir || null
      },
      disk: diskUsage,
      recent_errors: recentErrors,
      station: {
        callsign: config.station?.callsign || 'UNKNOWN',
        grid_square: config.station?.grid_square || 'UNKNOWN',
        mode: mode
      }
    });
  } catch (error) {
    console.error('Failed to get system status:', error);
    res.status(500).json({
      error: 'Failed to get system status',
      details: error.message
    });
  }
});

/**
 * Simple health check
 */
app.get('/api/v1/system/health', async (req, res) => {
  const recorderStatus = await getRecorderStatus();
  const diskUsage = await getDiskUsage(dataRoot);
  
  const checks = {
    recorder: recorderStatus.running ? 'ok' : 'error',
    disk_space: (diskUsage && parseFloat(diskUsage.percent_used) < 90) ? 'ok' : 'warning',
    time_snap: 'ok' // Will enhance this later
  };
  
  const allOk = Object.values(checks).every(v => v === 'ok');
  
  res.json({
    status: allOk ? 'healthy' : 'degraded',
    checks: checks
  });
});

/**
 * Get recent errors with filtering
 */
app.get('/api/v1/system/errors', async (req, res) => {
  try {
    const limit = parseInt(req.query.limit) || 20;
    const severity = req.query.severity; // 'error' or 'warning'
    
    let errors = await getRecentErrors(limit * 2); // Get more, then filter
    
    if (severity) {
      errors = errors.filter(e => e.level === severity.toLowerCase());
    }
    
    errors = errors.slice(0, limit);
    
    res.json({
      errors: errors,
      total_count: errors.length,
      filter: {
        severity: severity || 'all',
        limit: limit
      }
    });
  } catch (error) {
    console.error('Failed to get errors:', error);
    res.status(500).json({
      error: 'Failed to get errors',
      details: error.message
    });
  }
});

/**
 * Data capture continuity - system-wide gap analysis
 */
app.get('/api/v1/system/continuity', async (req, res) => {
  try {
    const startParam = req.query.start;
    const endParam = req.query.end;
    
    // Get available data range from NPZ files
    const dataRange = await getAvailableDataRange();
    
    // Parse time range parameters
    let startTime, endTime;
    const now = Date.now() / 1000;
    
    if (startParam && endParam) {
      // Custom range
      startTime = parseInt(startParam);
      endTime = parseInt(endParam);
    } else if (startParam === 'all') {
      // All available data
      startTime = dataRange.oldest;
      endTime = dataRange.newest;
    } else {
      // Quick pick ranges (default: 24 hours)
      const range = req.query.range || '24h';
      endTime = now;
      
      switch (range) {
        case '24h':
          startTime = now - 86400;
          break;
        case '7d':
          startTime = now - 604800;
          break;
        case '30d':
          startTime = now - 2592000;
          break;
        default:
          startTime = now - 86400;
      }
    }
    
    // Constrain to available data
    startTime = Math.max(startTime, dataRange.oldest);
    endTime = Math.min(endTime, dataRange.newest);
    
    // Calculate continuity metrics
    const continuity = await calculateContinuity(startTime, endTime);
    
    res.json({
      range: {
        start: new Date(startTime * 1000).toISOString(),
        end: new Date(endTime * 1000).toISOString(),
        duration_seconds: endTime - startTime
      },
      available_data: {
        oldest_npz: new Date(dataRange.oldest * 1000).toISOString(),
        newest_npz: new Date(dataRange.newest * 1000).toISOString(),
        total_duration_seconds: dataRange.newest - dataRange.oldest
      },
      continuity: continuity.metrics,
      gap_events: continuity.gaps
    });
  } catch (error) {
    console.error('Failed to get continuity:', error);
    res.status(500).json({
      error: 'Failed to get continuity',
      details: error.message
    });
  }
});

/**
 * Get discrimination time-series data for a channel and date
 */
app.get('/api/v1/channels/:channelName/discrimination/:date', async (req, res) => {
  try {
    const { channelName, date } = req.params;
    
    // Map channel names to their actual directory names
    // (Directory names preserve dots: WWV 2.5 MHz -> WWV_2.5_MHz)
    const dirMap = {
      'WWV 2.5 MHz': 'WWV_2.5_MHz',
      'WWV 5 MHz': 'WWV_5_MHz',
      'WWV 10 MHz': 'WWV_10_MHz',
      'WWV 15 MHz': 'WWV_15_MHz'
    };
    
    const channelDirName = dirMap[channelName] || channelName.replace(/ /g, '_');
    const fileChannelName = channelName.replace(/ /g, '_');
    const fileName = `${fileChannelName}_discrimination_${date}.csv`;
    const filePath = join(dataRoot, 'analytics', channelDirName, 'discrimination', fileName);
    
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
    const data = [];
    for (let i = 1; i < lines.length; i++) {
      const parts = lines[i].split(',');
      if (parts.length >= 10) {
        // Normalize timestamp to use 'Z' suffix instead of '+00:00' for UTC
        let timestamp = parts[0].trim();
        if (timestamp.endsWith('+00:00')) {
          timestamp = timestamp.replace('+00:00', 'Z');
        }
        
        data.push({
          timestamp_utc: timestamp,
          minute_timestamp: parseInt(parts[1]),
          wwv_detected: parts[2] === '1',
          wwvh_detected: parts[3] === '1',
          wwv_snr_db: parseFloat(parts[4]),
          wwvh_snr_db: parseFloat(parts[5]),
          power_ratio_db: parseFloat(parts[6]),
          differential_delay_ms: parts[7] !== '' ? parseFloat(parts[7]) : null,
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
 * Get spectrogram image for a channel and date
 * Currently supports only carrier (10 Hz) spectrograms from Digital RF.
 * For the current UTC day, the carrier spectrogram is always regenerated
 * so that same-day views reflect the latest data.
 */
app.get('/api/v1/channels/:channelName/spectrogram/:type/:date', async (req, res) => {
  try {
    const { channelName, type, date } = req.params;
    
    // Map channel names to their actual directory names
    const channelMap = {
      'WWV 2.5 MHz': 'WWV_2.5_MHz',
      'WWV 5 MHz': 'WWV_5_MHz',
      'WWV 10 MHz': 'WWV_10_MHz',
      'WWV 15 MHz': 'WWV_15_MHz',
      'WWV 20 MHz': 'WWV_20_MHz',
      'WWV 25 MHz': 'WWV_25_MHz',
      'CHU 3.33 MHz': 'CHU_3.33_MHz',
      'CHU 7.85 MHz': 'CHU_7.85_MHz',
      'CHU 14.67 MHz': 'CHU_14.67_MHz'
    };
    
    const channelDirName = channelMap[channelName] || channelName.replace(/ /g, '_');
    
    // Only carrier (10 Hz) spectrograms are supported now
    if (type !== 'carrier') {
      return res.status(400).json({
        error: 'Invalid spectrogram type',
        message: `Only 'carrier' spectrograms are supported`
      });
    }
    
    const spectrogramPath = join(
      dataRoot,
      'spectrograms',
      date,
      `${channelDirName}_${date}_carrier_spectrogram.png`
    );
    
    // For the current UTC date, always regenerate the carrier spectrogram
    // so that the visualization reflects the latest data, even if a PNG
    // already exists from earlier in the day.
    const nowUtc = new Date();
    const todayUtcStr = nowUtc.toISOString().slice(0, 10).replace(/-/g, '');
    
    if (date === todayUtcStr) {
      try {
        const scriptPath = join(installDir, 'scripts', 'generate_spectrograms_drf.py');
        if (!fs.existsSync(scriptPath)) {
          return res.status(500).json({
            error: 'Generation script not found',
            message: `Expected script at ${scriptPath}`
          });
        }
        
        const cmd = `python3 "${scriptPath}" --date ${date} --data-root "${dataRoot}"`;
        await execAsync(cmd);
      } catch (err) {
        console.error('Failed to regenerate carrier spectrogram:', err);
        return res.status(500).json({
          error: 'Failed to regenerate spectrogram',
          message: err.message
        });
      }
    }
    
    // Check if file exists after potential regeneration
    if (!fs.existsSync(spectrogramPath)) {
      return res.status(404).json({
        error: 'Spectrogram not found',
        message: `No carrier spectrogram available for ${channelName} on ${date}`,
        path: spectrogramPath,
        suggestion: `Run: python3 scripts/generate_spectrograms_drf.py --date ${date}`
      });
    }
    
    // Serve the PNG file
    res.sendFile(spectrogramPath);
  } catch (error) {
    console.error('Failed to get spectrogram:', error);
    res.status(500).json({
      error: 'Failed to get spectrogram',
      details: error.message
    });
  }
});

/**
 * Legacy endpoint - defaults to archive type
 */
app.get('/api/v1/channels/:channelName/spectrogram/:date', async (req, res) => {
  const { channelName, date } = req.params;
  req.params.type = 'archive';
  return app._router.handle(req, res);
});

/**
 * Generate spectrograms for a specific date and type
 * Runs in background, returns job ID for status tracking
 */
app.post('/api/v1/spectrograms/generate', async (req, res) => {
  try {
    const { date, type } = req.body;
    
    if (!date || !type) {
      return res.status(400).json({
        error: 'Missing required parameters',
        message: 'Both date and type are required'
      });
    }
    
    // Only carrier (10 Hz) spectrograms are supported.
    if (type !== 'carrier') {
      return res.status(400).json({
        error: 'Invalid type',
        message: 'Type must be "carrier"'
      });
    }
    
    // Validate date format (YYYYMMDD)
    if (!/^\d{8}$/.test(date)) {
      return res.status(400).json({
        error: 'Invalid date format',
        message: 'Date must be in YYYYMMDD format'
      });
    }
    
    // Create unique job ID
    const jobId = `${type}_${date}_${Date.now()}`;
    
    // Check if already generating this combination
    const existingJob = Array.from(spectrogramJobs.values()).find(
      job => job.date === date && job.type === type && job.status === 'running'
    );
    
    if (existingJob) {
      return res.json({
        jobId: Array.from(spectrogramJobs.entries()).find(([k, v]) => v === existingJob)[0],
        status: 'already_running',
        message: `Spectrogram generation for ${type} ${date} is already in progress`
      });
    }
    
    // Determine script path
    const scriptName = 'generate_spectrograms_drf.py';
    const scriptPath = join(installDir, 'scripts', scriptName);
    
    // Check if script exists
    if (!fs.existsSync(scriptPath)) {
      return res.status(500).json({
        error: 'Script not found',
        message: `Generation script not found: ${scriptPath}`
      });
    }
    
    // Initialize job status
    spectrogramJobs.set(jobId, {
      status: 'running',
      type,
      date,
      progress: 0,
      error: null,
      startTime: Date.now(),
      output: []
    });
    
    console.log(`Starting spectrogram generation: ${type} for ${date} (job ${jobId})`);
    
    // Spawn background process
    const pythonPath = process.env.PYTHON_PATH || 'python3';
    const args = [scriptPath, '--date', date, '--data-root', dataRoot];
    
    const child = spawn(pythonPath, args, {
      cwd: installDir,
      env: { ...process.env, PYTHONUNBUFFERED: '1' }
    });
    
    const job = spectrogramJobs.get(jobId);
    
    // Capture stdout
    child.stdout.on('data', (data) => {
      const output = data.toString();
      job.output.push(output);
      console.log(`[${jobId}] ${output.trim()}`);
      
      // Parse progress if possible
      // Match patterns: "Progress: 100/993" or "Processing 5/9"
      const progressMatch = output.match(/Progress:?\s+(\d+)\/(\d+)/i) || 
                           output.match(/Processing.*?(\d+)\/(\d+)/);
      if (progressMatch) {
        job.progress = Math.round((parseInt(progressMatch[1]) / parseInt(progressMatch[2])) * 100);
      }
    });
    
    // Capture stderr
    child.stderr.on('data', (data) => {
      const output = data.toString();
      job.output.push(output);
      console.error(`[${jobId}] ERROR: ${output.trim()}`);
    });
    
    // Handle completion
    child.on('close', (code) => {
      if (code === 0) {
        job.status = 'completed';
        job.progress = 100;
        console.log(`Spectrogram generation completed: ${jobId}`);
      } else {
        job.status = 'failed';
        job.error = `Process exited with code ${code}`;
        console.error(`Spectrogram generation failed: ${jobId} (code ${code})`);
      }
      
      // Clean up old jobs after 5 minutes
      setTimeout(() => {
        spectrogramJobs.delete(jobId);
        console.log(`Cleaned up job: ${jobId}`);
      }, 5 * 60 * 1000);
    });
    
    child.on('error', (error) => {
      job.status = 'failed';
      job.error = error.message;
      console.error(`Spectrogram generation error: ${jobId}`, error);
    });
    
    // Return job ID immediately
    res.json({
      jobId,
      status: 'started',
      message: `Spectrogram generation started for ${type} ${date}`,
      pollUrl: `/api/v1/spectrograms/status/${jobId}`
    });
    
  } catch (error) {
    console.error('Failed to start spectrogram generation:', error);
    res.status(500).json({
      error: 'Failed to start generation',
      details: error.message
    });
  }
});

/**
 * Check status of spectrogram generation job
 */
app.get('/api/v1/spectrograms/status/:jobId', (req, res) => {
  const { jobId } = req.params;
  const job = spectrogramJobs.get(jobId);
  
  if (!job) {
    return res.status(404).json({
      error: 'Job not found',
      message: 'Job may have completed and been cleaned up, or never existed'
    });
  }
  
  res.json({
    jobId,
    status: job.status,
    type: job.type,
    date: job.date,
    progress: job.progress,
    error: job.error,
    elapsedSeconds: Math.round((Date.now() - job.startTime) / 1000),
    recentOutput: job.output.slice(-10).join('') // Last 10 lines
  });
});

/**
 * Channel details - comprehensive per-channel metrics
 */
app.get('/api/v1/channels/details', async (req, res) => {
  try {
    const coreStatus = await getCoreRecorderStatus();
    const analyticsStatus = await getAnalyticsServiceStatus();
    
    const channels = [];
    
    // Iterate through core recorder channels
    if (coreStatus.channels) {
      for (const [ssrc, coreChannel] of Object.entries(coreStatus.channels)) {
        const channelName = coreChannel.channel_name;
        
        // Find corresponding analytics data
        let analyticsChannel = null;
        if (analyticsStatus.channels) {
          analyticsChannel = analyticsStatus.channels[channelName];
        }
        
        // Calculate packet loss rate
        const packetLossRate = coreChannel.packets_received > 0
          ? (coreChannel.gaps_detected / coreChannel.packets_received * 100)
          : 0;
        
        // Time snap status
        let timeSnapStatus = {
          established: false,
          source: null,
          confidence: 0,
          age_minutes: null
        };
        
        if (analyticsChannel && analyticsChannel.time_snap) {
          timeSnapStatus = {
            established: analyticsChannel.time_snap.established,
            source: analyticsChannel.time_snap.station || analyticsChannel.time_snap.source,
            confidence: analyticsChannel.time_snap.confidence || 0,
            age_minutes: analyticsChannel.time_snap.age_minutes || null
          };
        }
        
        // WWV/H time difference from discrimination
        let wwvhTimeDiff = null;
        const isWWVChannel = channelName.includes('WWV') && !channelName.includes('WWVH');
        if (isWWVChannel && analyticsChannel && analyticsChannel.wwvh_discrimination) {
          const disc = analyticsChannel.wwvh_discrimination;
          if (disc.enabled) {
            // Use latest measurement if available, otherwise use mean
            if (disc.latest && disc.latest.differential_delay_ms !== null && disc.latest.differential_delay_ms !== undefined) {
              wwvhTimeDiff = disc.latest.differential_delay_ms;
            } else if (disc.mean_differential_delay_ms !== null && disc.mean_differential_delay_ms !== undefined) {
              wwvhTimeDiff = disc.mean_differential_delay_ms;
            }
          }
        }
        
        channels.push({
          ssrc: ssrc,
          channel_name: channelName,
          frequency_hz: coreChannel.frequency_hz,
          rtp_stream: {
            status: coreChannel.status,
            active: coreChannel.status === 'recording',
            packets_received: coreChannel.packets_received,
            last_packet_time: coreChannel.last_packet_time
          },
          time_snap: timeSnapStatus,
          packet_loss_rate: packetLossRate,
          wwvh_time_diff_ms: wwvhTimeDiff,
          quality: analyticsChannel ? {
            completeness_pct: analyticsChannel.quality_metrics?.last_completeness_pct || null,
            packet_loss_pct: analyticsChannel.quality_metrics?.last_packet_loss_pct || null
          } : null,
          tone_detections: analyticsChannel ? analyticsChannel.tone_detections : null,
          digital_rf: analyticsChannel ? {
            samples_written: analyticsChannel.digital_rf?.samples_written || 0,
            files_written: analyticsChannel.digital_rf?.files_written || 0
          } : null
        });
      }
    }
    
    res.json({
      timestamp: new Date().toISOString(),
      channels: channels,
      summary: {
        total_channels: channels.length,
        active_channels: channels.filter(c => c.rtp_stream.active).length,
        time_snap_established: channels.filter(c => c.time_snap.established).length
      }
    });
  } catch (error) {
    console.error('Failed to get channel details:', error);
    res.status(500).json({
      error: 'Failed to get channel details',
      details: error.message
    });
  }
});

// ============================================================================
// LEGACY API ENDPOINTS (Backward Compatibility)
// ============================================================================
//  Redirect to new /api/v1/ endpoints

/**
 * Station info and server uptime (LEGACY - redirects to /api/v1/system/status)
 */
app.get('/api/monitoring/station-info', async (req, res) => {
  try {
    // Use already-loaded config
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
 * Timing & Quality Dashboard API
 * Returns comprehensive quality metrics - V2 Architecture compatible
 */
app.get('/api/monitoring/timing-quality', async (req, res) => {
  try {
    // Try V2 status files first
    const coreStatus = await getCoreRecorderStatus();
    const analyticsStatus = await getAnalyticsServiceStatus();
    
    if (coreStatus.running) {
      // V2 Architecture: Return data from status JSON files
      const channelData = {};
      let timeSnapStatus = null;
      
      // Get data from core recorder status
      if (coreStatus.channels) {
        for (const [ssrc, channelInfo] of Object.entries(coreStatus.channels)) {
          const channelName = channelInfo.channel_name;
          const totalSamples = channelInfo.packets_received * 320;
          const gapSamples = channelInfo.total_gap_samples || 0;
          const completeness = totalSamples > 0 ? ((totalSamples - gapSamples) / totalSamples * 100) : 100;
          const packetLoss = totalSamples > 0 ? (gapSamples / totalSamples * 100) : 0;
          
          channelData[channelName] = {
            latestGrade: 'UNKNOWN',  // V2 doesn't use grades
            latestScore: completeness,  // Keep as number, dashboard will format
            minutesInHour: 60,
            sampleCompleteness: completeness,
            avgPacketLoss: packetLoss,
            avgDrift: null,
            wwvDetections: 0,
            wwvhDetections: 0,
            chuDetections: 0,
            totalDetections: 0,
            npzFilesWritten: channelInfo.npz_files_written || 0,
            packetsReceived: channelInfo.packets_received || 0,
            gapsDetected: channelInfo.gaps_detected || 0,
            status: channelInfo.status || 'unknown',
            lastPacketTime: channelInfo.last_packet_time || null
          };
        }
      }
      
      // Add analytics data if available
      if (analyticsStatus.running && analyticsStatus.channels) {
        for (const [channelName, analyticsInfo] of Object.entries(analyticsStatus.channels)) {
          if (!channelData[channelName]) {
            channelData[channelName] = {};
          }
          
          // Merge analytics data
          Object.assign(channelData[channelName], {
            wwvDetections: analyticsInfo.tone_detections?.wwv || 0,
            wwvhDetections: analyticsInfo.tone_detections?.wwvh || 0,
            chuDetections: analyticsInfo.tone_detections?.chu || 0,
            totalDetections: analyticsInfo.tone_detections?.total || 0,
            npzProcessed: analyticsInfo.npz_files_processed || 0,
            lastCompleteness: analyticsInfo.quality_metrics?.last_completeness_pct || 0,
            lastPacketLoss: analyticsInfo.quality_metrics?.last_packet_loss_pct || 0,
            digitalRfSamples: analyticsInfo.digital_rf?.samples_written || 0,
            timeSnapEstablished: analyticsInfo.time_snap?.established || false,
            timeSnapSource: analyticsInfo.time_snap?.station || null,
            timeSnapAge: analyticsInfo.time_snap?.age_minutes || 0
          });
          
          // Track time_snap status
          if (analyticsInfo.time_snap && analyticsInfo.time_snap.established) {
            if (!timeSnapStatus) {
              timeSnapStatus = {
                established: true,
                source: channelName,
                station: analyticsInfo.time_snap.station,
                confidence: analyticsInfo.time_snap.confidence,
                age: analyticsInfo.time_snap.age_minutes,
                status: analyticsInfo.time_snap.source
              };
            }
          }
        }
      }
      
      // Add detection rates
      for (const [channelName, data] of Object.entries(channelData)) {
        data.wwvDetectionRate = data.wwvDetections || 0;
        data.wwvhDetectionRate = data.wwvhDetections || 0;
        data.chuDetectionRate = data.chuDetections || 0;
        data.recentMinutes = [];  // V2 doesn't have minute-by-minute history yet
        data.avgDifferentialDelay = null;  // Not yet implemented
      }
      
      return res.json({
        available: true,
        source: 'v2_status_files',
        channels: channelData,  // Frontend expects 'channels', not 'channelData'
        timeSnap: timeSnapStatus,  // Frontend expects 'timeSnap', not 'timeSnapStatus'
        overall: {
          gradePercentages: { A: 0, B: 0, C: 0, D: 100, F: 0 },  // V2 doesn't use grades
          summary: {
            channels_active: coreStatus.overall?.channels_active || 0,
            channels_total: coreStatus.overall?.channels_total || 0,
            npz_written: coreStatus.overall?.total_npz_written || 0,
            packets_received: coreStatus.overall?.total_packets_received || 0,
            npz_processed: analyticsStatus.overall?.total_npz_processed || 0
          }
        },
        alerts: []  // No alerts yet in V2
      });
    }
    
    // Fallback to V1 CSV files if V2 status not available
    const now = new Date();
    const today = now.toISOString().split('T')[0].replace(/-/g, '');
    const yesterday = new Date(now - 24*60*60*1000).toISOString().split('T')[0].replace(/-/g, '');
    
    let qualityDir = join(dataRoot, 'analytics', 'quality', today);
    
    // Try today first, fall back to yesterday
    if (!fs.existsSync(qualityDir)) {
      qualityDir = join(dataRoot, 'analytics', 'quality', yesterday);
      console.log(`Today's directory not found, trying yesterday: ${qualityDir}`);
    }
    
    // Check if quality directory exists
    if (!fs.existsSync(qualityDir)) {
      return res.json({
        available: false,
        message: `Quality data directory not found for today (${today}) or yesterday (${yesterday}). V2 status files also not available.`
      });
    }
    
    console.log(`Using quality data from: ${qualityDir}`);
    
    // Find CSV files
    const csvFiles = fs.readdirSync(qualityDir)
      .filter(f => f.endsWith('.csv') && f.includes('minute_quality'));
    
    if (csvFiles.length === 0) {
      return res.json({
        available: false,
        message: 'No quality CSV files found for today'
      });
    }
    
    // Parse CSV files and aggregate data
    const channelData = {};
    let timeSnapStatus = null;
    
    for (const csvFile of csvFiles) {
      const channelName = csvFile.split('_minute_quality_')[0].split('/').pop();
      const csvPath = join(qualityDir, csvFile);
      
      if (!fs.existsSync(csvPath)) continue;
      
      const csvContent = fs.readFileSync(csvPath, 'utf8');
      const records = parse(csvContent, { columns: true, skip_empty_lines: true });
      
      if (records.length === 0) continue;
      
      // Get last 60 minutes for hourly summary
      const recentRecords = records.slice(-60);
      const latestRecord = records[records.length - 1];
      
      // Calculate statistics (handle old CSV format without quality_grade)
      const grades = recentRecords.map(r => r.quality_grade).filter(g => g && g !== '');
      const hasQualityGrades = grades.length > 0;
      
      const gradeCounts = {
        A: grades.filter(g => g === 'A').length,
        B: grades.filter(g => g === 'B').length,
        C: grades.filter(g => g === 'C').length,
        D: grades.filter(g => g === 'D').length,
        F: grades.filter(g => g === 'F').length
      };
      
      const avgLoss = recentRecords.reduce((sum, r) => 
        sum + parseFloat(r.packet_loss_pct || 0), 0) / recentRecords.length;
      
      const drifts = recentRecords
        .map(r => parseFloat(r.drift_ms))
        .filter(d => !isNaN(d));
      const avgDrift = drifts.length > 0 ? 
        drifts.reduce((sum, d) => sum + d, 0) / drifts.length : null;
      
      // Count separate station detections
      const wwvDetections = recentRecords.filter(r => r.wwv_detected === 'True').length;
      const wwvhDetections = recentRecords.filter(r => r.wwvh_detected === 'True').length;
      const chuDetections = recentRecords.filter(r => r.chu_detected === 'True').length;
      const totalDetections = wwvDetections + wwvhDetections + chuDetections;
      
      // Calculate average differential delay (WWV-WWVH propagation difference)
      const differentialDelays = recentRecords
        .map(r => parseFloat(r.differential_delay_ms))
        .filter(d => !isNaN(d));
      const avgDifferentialDelay = differentialDelays.length > 0 ?
        differentialDelays.reduce((sum, d) => sum + d, 0) / differentialDelays.length : null;
      
      channelData[channelName] = {
        latestGrade: latestRecord.quality_grade || 'UNKNOWN',
        latestScore: parseFloat(latestRecord.quality_score || 0),
        minutesInHour: recentRecords.length,
        sampleCompleteness: 100.0,
        avgPacketLoss: avgLoss,
        avgDrift: avgDrift,
        avgDifferentialDelay: avgDifferentialDelay,
        wwvDetections: wwvDetections,
        wwvhDetections: wwvhDetections,
        chuDetections: chuDetections,
        totalDetections: totalDetections,
        wwvDetectionRate: (wwvDetections / recentRecords.length * 100).toFixed(1),
        wwvhDetectionRate: (wwvhDetections / recentRecords.length * 100).toFixed(1),
        chuDetectionRate: (chuDetections / recentRecords.length * 100).toFixed(1),
        gradeCounts: gradeCounts,
        recentMinutes: recentRecords.slice(-10).map(r => ({
          time: r.minute_start,
          grade: r.quality_grade,
          score: parseFloat(r.quality_score || 0),
          samples: parseInt(r.samples || 0),
          loss: parseFloat(r.packet_loss_pct || 0),
          drift: r.drift_ms ? parseFloat(r.drift_ms) : null,
          gaps: parseInt(r.gaps || 0),
          alerts: r.alerts || '',
          resequenced: parseInt(r.resequenced || 0)
        })),
        alerts: latestRecord.alerts || null
      };
      
      // Track time_snap status per channel (WWV/CHU channels)
      const timeSnapValue = latestRecord.time_snap || '';
      const isEstablished = timeSnapValue.startsWith('wwv_');
      
      // Store per-channel time_snap info
      channelData[channelName].timeSnapEstablished = isEstablished;
      channelData[channelName].timeSnapSource = timeSnapValue;
      channelData[channelName].timeSnapAge = parseInt(latestRecord.time_snap_age_minutes || 0);
      
      // Keep old behavior for backward compatibility (pick "best" channel)
      if ((channelName.startsWith('WWV') || channelName.startsWith('CHU')) && isEstablished) {
        if (!timeSnapStatus || (avgDrift && Math.abs(avgDrift) < Math.abs(timeSnapStatus.drift))) {
          timeSnapStatus = {
            established: true,
            source: channelName,
            drift: avgDrift || 0,
            age: parseInt(latestRecord.time_snap_age_minutes || 0),
            status: timeSnapValue
          };
        }
      }
    }
    
    // Calculate overall statistics
    const allGrades = Object.values(channelData)
      .flatMap(ch => Object.entries(ch.gradeCounts)
        .flatMap(([grade, count]) => Array(count).fill(grade)));
    
    const gradeDistribution = {
      A: allGrades.filter(g => g === 'A').length,
      B: allGrades.filter(g => g === 'B').length,
      C: allGrades.filter(g => g === 'C').length,
      D: allGrades.filter(g => g === 'D').length,
      F: allGrades.filter(g => g === 'F').length
    };
    
    const totalMinutes = allGrades.length;
    const gradePercentages = {};
    for (const [grade, count] of Object.entries(gradeDistribution)) {
      gradePercentages[grade] = totalMinutes > 0 ? 
        (count / totalMinutes * 100).toFixed(1) : '0.0';
    }
    
    // Collect active alerts
    const activeAlerts = [];
    for (const [channel, data] of Object.entries(channelData)) {
      if (data.alerts) {
        activeAlerts.push({
          channel: channel,
          time: data.recentMinutes[data.recentMinutes.length - 1]?.time || 'Unknown',
          alert: data.alerts
        });
      }
    }
    
    res.json({
      available: true,
      timestamp: new Date().toISOString(),
      timeSnap: timeSnapStatus || {
        established: false,
        message: 'No WWV time_snap established yet - waiting for first WWV detection'
      },
      channels: channelData,
      overall: {
        gradeDistribution: gradeDistribution,
        gradePercentages: gradePercentages,
        totalMinutes: totalMinutes
      },
      alerts: activeAlerts
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
 * Live quality status - reads recording-stats.json from daemon
 */
app.get('/api/monitoring/live-quality', (req, res) => {
  try {
    // Check multiple possible locations for status file
    const possibleStatusFiles = [
      join(dataRoot, 'status', 'recording-stats.json'),  // PathResolver location
      '/tmp/signal-recorder-stats.json',  // Default fallback
      '/var/lib/signal-recorder/status/recording-stats.json'  // Production
    ];
    
    let statusFile = null;
    for (const file of possibleStatusFiles) {
      if (fs.existsSync(file)) {
        statusFile = file;
        break;
      }
    }
    
    if (!statusFile) {
      return res.json({
        available: false,
        message: 'Recorder not running or no status file found',
        searchedPaths: possibleStatusFiles
      });
    }
    
    const statusData = JSON.parse(fs.readFileSync(statusFile, 'utf8'));
    
    // Extract timing_validation data for display
    const timingData = {};
    if (statusData.recorders) {
      Object.entries(statusData.recorders).forEach(([ssrc, rec]) => {
        if (rec.timing_validation && rec.timing_validation.enabled) {
          timingData[rec.channel_name] = {
            stations_active: rec.timing_validation.stations_active || [],
            wwv_detections: rec.timing_validation.wwv_detections || 0,
            wwvh_detections: rec.timing_validation.wwvh_detections || 0,
            chu_detections: rec.timing_validation.chu_detections || 0,
            total_detections: rec.timing_validation.total_detections || 0,
            detection_rate: rec.timing_validation.detection_rate || 0,
            timing_error_mean_ms: rec.timing_validation.timing_error_mean_ms || 0,
            timing_error_std_ms: rec.timing_validation.timing_error_std_ms || 0,
            differential_mean_ms: rec.timing_validation.wwv_wwvh_differential_mean_ms || 0,
            differential_std_ms: rec.timing_validation.wwv_wwvh_differential_std_ms || 0
          };
        }
      });
    }
    
    res.json({
      available: true,
      status: statusData,
      timing_detections: timingData,
      timestamp: statusData.timestamp || new Date().toISOString()
    });
    
  } catch (error) {
    console.error('Error reading status file:', error);
    res.json({ 
      available: false,
      error: error.message
    });
  }
});

/**
 * Timing and Gap Analysis - detailed timing quality and packet loss analysis
 * GET /api/v1/timing/analysis?date=20251115&channel=WWV+10+MHz
 */
app.get('/api/v1/timing/analysis', async (req, res) => {
  try {
    const date = req.query.date;
    const channel = req.query.channel;
    
    if (!date) {
      return res.status(400).json({ error: 'date parameter required (YYYYMMDD)' });
    }
    
    // Build command
    const scriptPath = join(installDir, 'scripts/analyze_timing.py');
    let cmd = `python3 "${scriptPath}" --date ${date} --data-root "${dataRoot}"`;
    
    if (channel) {
      cmd += ` --channel "${channel}"`;
    }
    
    // Export to temp JSON file
    const tmpFile = `/tmp/grape-timing-${date}-${Date.now()}.json`;
    cmd += ` --export "${tmpFile}"`;
    
    // Execute analysis
    const { stdout, stderr } = await execAsync(cmd, { 
      maxBuffer: 10 * 1024 * 1024,
      timeout: 60000 
    });
    
    // Read results from temp file
    let analysisData = null;
    try {
      const jsonContent = fs.readFileSync(tmpFile, 'utf8');
      analysisData = JSON.parse(jsonContent);
      fs.unlinkSync(tmpFile); // Clean up
    } catch (err) {
      console.error('Failed to read analysis results:', err);
      return res.status(500).json({ 
        error: 'Failed to parse analysis results',
        stdout: stdout,
        stderr: stderr 
      });
    }
    
    // Calculate summary statistics
    const files = analysisData.files || [];
    const totalFiles = files.length;
    const filesWithGaps = files.filter(f => f.gaps_count > 0).length;
    const totalGaps = files.reduce((sum, f) => sum + f.gaps_count, 0);
    const totalSamplesFilled = files.reduce((sum, f) => sum + f.gaps_filled, 0);
    const totalPacketsRx = files.reduce((sum, f) => sum + f.packets_received, 0);
    const totalPacketsExpected = files.reduce((sum, f) => sum + f.packets_expected, 0);
    
    const completeness = totalPacketsExpected > 0 
      ? (totalPacketsRx / totalPacketsExpected * 100)
      : 100.0;
    
    // Calculate quality grade
    let grade;
    if (completeness >= 99.9) grade = 'A+';
    else if (completeness >= 99.5) grade = 'A';
    else if (completeness >= 99.0) grade = 'B';
    else if (completeness >= 95.0) grade = 'C';
    else grade = 'F';
    
    // Hourly breakdown
    const hourly = {};
    for (let hour = 0; hour < 24; hour++) {
      hourly[hour] = { count: 0, samples: 0, files: 0, completeness: [] };
    }
    
    for (const file of files) {
      try {
        const hour = parseInt(file.filename.substring(9, 11));
        hourly[hour].count += file.gaps_count;
        hourly[hour].samples += file.gaps_filled;
        hourly[hour].files += 1;
        hourly[hour].completeness.push(file.completeness * 100);
      } catch (err) {
        // Skip files with bad format
      }
    }
    
    // Calculate average completeness per hour
    for (let hour = 0; hour < 24; hour++) {
      const h = hourly[hour];
      if (h.completeness.length > 0) {
        h.avg_completeness = h.completeness.reduce((a, b) => a + b) / h.completeness.length;
      } else {
        h.avg_completeness = null;
      }
      delete h.completeness; // Don't send full array
    }
    
    // Format response
    res.json({
      channel: analysisData.channel,
      date: analysisData.date,
      summary: {
        total_files: totalFiles,
        files_with_gaps: filesWithGaps,
        total_gaps: totalGaps,
        samples_filled: totalSamplesFilled,
        packets_received: totalPacketsRx,
        packets_expected: totalPacketsExpected,
        completeness_percent: completeness,
        quality_grade: grade
      },
      time_snap: analysisData.time_snap,
      hourly_breakdown: hourly,
      files: files  // Full detail if needed
    });
    
  } catch (err) {
    console.error('Timing analysis error:', err);
    res.status(500).json({ 
      error: 'Analysis failed',
      message: err.message 
    });
  }
});

// ============================================================================
// STATIC PAGE ROUTES
// ============================================================================

// Root - redirect to timing dashboard
app.get('/', (req, res) => {
  res.redirect('/timing-dashboard.html');
});

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'GRAPE Monitoring Server' });
});

// ============================================================================
// START SERVER
// ============================================================================

app.listen(PORT, () => {
  console.log('');
  console.log('=' .repeat(60));
  console.log('🚀 GRAPE Monitoring Server Running - API v1');
  console.log('=' .repeat(60));
  console.log('');
  console.log('📊 Dashboards:');
  console.log(`   http://localhost:${PORT}/                   - Main dashboard`);
  console.log(`   http://localhost:${PORT}/timing-dashboard.html  - Timing & quality`);
  console.log(`   http://localhost:${PORT}/timing-analysis.html   - Gap analysis`);
  console.log('');
  console.log('📡 API v1 Endpoints (New):');
  console.log(`   http://localhost:${PORT}/api/v1/system/status      - System health`);
  console.log(`   http://localhost:${PORT}/api/v1/system/health      - Health check`);
  console.log(`   http://localhost:${PORT}/api/v1/system/errors      - Recent errors`);
  console.log(`   http://localhost:${PORT}/api/v1/timing/analysis    - Gap & timing analysis`);
  console.log('');
  console.log('📡 Legacy Endpoints (Backward compatible):');
  console.log(`   http://localhost:${PORT}/api/monitoring/station-info`);
  console.log(`   http://localhost:${PORT}/api/monitoring/timing-quality`);
  console.log(`   http://localhost:${PORT}/api/monitoring/live-quality`);
  console.log('');
  console.log('💡 Features:');
  console.log('   ✅ System status (disk usage, errors, channels)');
  console.log('   ✅ WWV/WWVH discrimination tracking');
  console.log('   ✅ Quality metrics with A-F grading');
  console.log('   ✅ No authentication required');
  console.log('');
  console.log('📝 Configuration:');
  console.log('   Edit TOML files directly in: config/');
  console.log('');
  console.log('=' .repeat(60));
});
