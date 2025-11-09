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
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

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

// ============================================================================
// API v1 ENDPOINTS (New versioned API)
// ============================================================================

/**
 * System status - comprehensive health check
 */
app.get('/api/v1/system/status', async (req, res) => {
  try {
    const recorderStatus = await getRecorderStatus();
    const channelStatus = await getChannelStatus();
    const timeSnapStatus = await getTimeSnapStatus();
    const diskUsage = await getDiskUsage(dataRoot);
    const recentErrors = await getRecentErrors(5);
    
    // Calculate overall quality grade from recent data
    let overallGrade = 'UNKNOWN';
    try {
      const now = new Date();
      const today = now.toISOString().split('T')[0].replace(/-/g, '');
      const qualityDir = join(dataRoot, 'analytics', 'quality', today);
      
      if (fs.existsSync(qualityDir)) {
        const csvFiles = fs.readdirSync(qualityDir)
          .filter(f => f.endsWith('.csv') && f.includes('minute_quality'));
        
        if (csvFiles.length > 0) {
          const grades = [];
          for (const csvFile of csvFiles) {
            const csvPath = join(qualityDir, csvFile);
            const csvContent = fs.readFileSync(csvPath, 'utf8');
            const records = parse(csvContent, { columns: true, skip_empty_lines: true });
            const recentRecords = records.slice(-10); // Last 10 minutes
            grades.push(...recentRecords.map(r => r.quality_grade).filter(g => g && g !== ''));
          }
          
          if (grades.length > 0) {
            // Calculate weighted average grade
            const gradeValues = { A: 4, B: 3, C: 2, D: 1, F: 0 };
            const avgValue = grades.reduce((sum, g) => sum + (gradeValues[g] || 0), 0) / grades.length;
            overallGrade = avgValue >= 3.5 ? 'A' : avgValue >= 2.5 ? 'B' : avgValue >= 1.5 ? 'C' : avgValue >= 0.5 ? 'D' : 'F';
          }
        }
      }
    } catch (error) {
      console.error('Error calculating overall grade:', error);
    }
    
    res.json({
      timestamp: new Date().toISOString(),
      recorder: recorderStatus,
      radiod: {
        connected: recorderStatus.running,
        status_address: config.ka9q?.status_address || 'unknown'
      },
      channels: channelStatus,
      time_snap: timeSnapStatus,
      quality: {
        overall_grade: overallGrade,
        period: 'last 10 minutes'
      },
      data_paths: {
        archive: join(dataRoot, 'data'),
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
 * Returns comprehensive quality metrics based on KA9Q timing architecture
 */
app.get('/api/monitoring/timing-quality', (req, res) => {
  try {
    // Use config-defined data_root
    // Check both today and yesterday (UTC) to handle timezone mismatches
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
        message: `Quality data directory not found for today (${today}) or yesterday (${yesterday})`
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
  console.log('');
  console.log('📡 API v1 Endpoints (New):');
  console.log(`   http://localhost:${PORT}/api/v1/system/status   - System health`);
  console.log(`   http://localhost:${PORT}/api/v1/system/health   - Health check`);
  console.log(`   http://localhost:${PORT}/api/v1/system/errors   - Recent errors`);
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
