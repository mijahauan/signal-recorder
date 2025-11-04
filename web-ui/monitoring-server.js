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
// MONITORING API ENDPOINTS (No Authentication Required)
// ============================================================================

/**
 * Station info and server uptime
 */
app.get('/api/monitoring/station-info', (req, res) => {
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
    const today = new Date().toISOString().split('T')[0].replace(/-/g, '');
    const qualityDir = join(dataRoot, 'analytics', 'quality', today);
    
    console.log(`Looking for quality data in: ${qualityDir}`);
    
    // Check if quality directory exists
    if (!fs.existsSync(qualityDir)) {
      return res.json({
        available: false,
        message: `Quality data directory not found: ${qualityDir}`
      });
    }
    
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
      
      channelData[channelName] = {
        latestGrade: latestRecord.quality_grade || 'UNKNOWN',
        latestScore: parseFloat(latestRecord.quality_score || 0),
        minutesInHour: recentRecords.length,
        sampleCompleteness: 100.0,
        avgPacketLoss: avgLoss,
        avgDrift: avgDrift,
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
 * Live quality status (simple check)
 */
app.get('/api/monitoring/live-quality', (req, res) => {
  try {
    const possibleStatusFiles = [
      join(installDir, 'analytics', 'live_quality_status.json'),
      '/tmp/signal-recorder/overnight_20251103/analytics/live_quality_status.json',
      '/tmp/signal-recorder/overnight_20251104/analytics/live_quality_status.json',
      '/var/lib/signal-recorder/analytics/live_quality_status.json'
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
        message: 'Recorder not running or no status file found'
      });
    }
    
    const statusData = JSON.parse(fs.readFileSync(statusFile, 'utf8'));
    res.json({
      available: true,
      ...statusData
    });
    
  } catch (error) {
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
  console.log('🚀 GRAPE Monitoring Server Running');
  console.log('=' .repeat(60));
  console.log('');
  console.log('📊 Timing & Quality Dashboard:');
  console.log(`   http://localhost:${PORT}/`);
  console.log(`   http://localhost:${PORT}/timing-dashboard.html`);
  console.log('');
  console.log('📡 API Endpoints:');
  console.log(`   http://localhost:${PORT}/api/monitoring/timing-quality`);
  console.log(`   http://localhost:${PORT}/api/monitoring/live-quality`);
  console.log('');
  console.log('💡 Features:');
  console.log('   - No authentication required');
  console.log('   - Real-time quality monitoring');
  console.log('   - KA9Q timing architecture metrics');
  console.log('   - Auto-refresh every 60 seconds');
  console.log('');
  console.log('📝 Configuration:');
  console.log('   Edit TOML files directly in: config/');
  console.log('');
  console.log('=' .repeat(60));
});
