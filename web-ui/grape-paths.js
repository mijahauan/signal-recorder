/**
 * GRAPE Paths - JavaScript/Node.js Implementation
 * 
 * Centralized path management for GRAPE data structures.
 * Matches the Python implementation in src/signal_recorder/paths.py
 * 
 * Usage:
 *   import { GRAPEPaths, loadPathsFromConfig } from './grape-paths.js';
 *   
 *   // From config
 *   const paths = loadPathsFromConfig('./config/grape-config.toml');
 *   
 *   // Or explicit data root
 *   const paths = new GRAPEPaths('/tmp/grape-test');
 *   
 *   // Get paths
 *   const archiveDir = paths.getArchiveDir('WWV 10 MHz');
 *   const drfDir = paths.getDigitalRFDir('WWV 10 MHz');
 *   const specPath = paths.getSpectrogramPath('WWV 10 MHz', '20251115', 'carrier');
 */

import { join, dirname } from 'path';
import { readFileSync, readdirSync, existsSync } from 'fs';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

/**
 * Convert channel name to key format.
 * 
 * Examples:
 *   WWV 10 MHz -> wwv10
 *   WWV 2.5 MHz -> wwv2.5
 *   CHU 3.33 MHz -> chu3.33
 */
function channelNameToKey(channelName) {
    const parts = channelName.split(' ');
    if (parts.length < 2) {
        // Fallback: underscored lowercase
        return channelName.replace(/ /g, '_').toLowerCase();
    }
    
    const station = parts[0].toLowerCase();  // wwv, chu
    const freq = parts[1];                   // 10, 2.5, 3.33
    
    return `${station}${freq}`;
}

/**
 * Convert channel name to directory format.
 * 
 * Examples:
 *   WWV 10 MHz -> WWV_10_MHz
 *   CHU 3.33 MHz -> CHU_3.33_MHz
 */
function channelNameToDir(channelName) {
    return channelName.replace(/ /g, '_');
}

/**
 * Convert directory name back to human-readable format.
 * 
 * Examples:
 *   WWV_10_MHz -> WWV 10 MHz
 */
function dirToChannelName(dirName) {
    return dirName.replace(/_/g, ' ');
}

/**
 * Central path manager for GRAPE data structures.
 */
class GRAPEPaths {
    /**
     * @param {string} dataRoot - Root data directory (e.g., /tmp/grape-test)
     */
    constructor(dataRoot) {
        this.dataRoot = dataRoot;
    }
    
    // ========================================================================
    // Archive Paths (Raw NPZ files)
    // ========================================================================
    
    /**
     * Get archive directory for a channel.
     * 
     * @param {string} channelName - Channel name (e.g., "WWV 10 MHz")
     * @returns {string} Path: {data_root}/archives/{CHANNEL}/
     */
    getArchiveDir(channelName) {
        const channelDir = channelNameToDir(channelName);
        return join(this.dataRoot, 'archives', channelDir);
    }
    
    /**
     * Get path for a specific archive NPZ file.
     * 
     * @param {string} channelName - Channel name
     * @param {string} timestamp - ISO timestamp (YYYYMMDDTHHMMSZ)
     * @param {number} frequencyHz - Frequency in Hz
     * @returns {string} Path: {data_root}/archives/{CHANNEL}/{timestamp}_{freq}_iq.npz
     */
    getArchiveFile(channelName, timestamp, frequencyHz) {
        const archiveDir = this.getArchiveDir(channelName);
        return join(archiveDir, `${timestamp}_${frequencyHz}_iq.npz`);
    }
    
    // ========================================================================
    // Analytics Paths (Per-channel products)
    // ========================================================================
    
    /**
     * Get analytics directory for a channel.
     * 
     * @param {string} channelName - Channel name
     * @returns {string} Path: {data_root}/analytics/{CHANNEL}/
     */
    getAnalyticsDir(channelName) {
        const channelDir = channelNameToDir(channelName);
        return join(this.dataRoot, 'analytics', channelDir);
    }
    
    /**
     * Get Digital RF directory for a channel.
     * 
     * @param {string} channelName - Channel name
     * @returns {string} Path: {data_root}/analytics/{CHANNEL}/digital_rf/
     */
    getDigitalRFDir(channelName) {
        return join(this.getAnalyticsDir(channelName), 'digital_rf');
    }
    
    /**
     * Get WWV/WWVH discrimination directory.
     * 
     * @param {string} channelName - Channel name
     * @returns {string} Path: {data_root}/analytics/{CHANNEL}/discrimination/
     */
    getDiscriminationDir(channelName) {
        return join(this.getAnalyticsDir(channelName), 'discrimination');
    }
    
    /**
     * Get quality metrics directory.
     * 
     * @param {string} channelName - Channel name
     * @returns {string} Path: {data_root}/analytics/{CHANNEL}/quality/
     */
    getQualityDir(channelName) {
        return join(this.getAnalyticsDir(channelName), 'quality');
    }
    
    /**
     * Get analytics logs directory.
     * 
     * @param {string} channelName - Channel name
     * @returns {string} Path: {data_root}/analytics/{CHANNEL}/logs/
     */
    getAnalyticsLogsDir(channelName) {
        return join(this.getAnalyticsDir(channelName), 'logs');
    }
    
    /**
     * Get analytics status directory.
     * 
     * @param {string} channelName - Channel name
     * @returns {string} Path: {data_root}/analytics/{CHANNEL}/status/
     */
    getAnalyticsStatusDir(channelName) {
        return join(this.getAnalyticsDir(channelName), 'status');
    }
    
    // ========================================================================
    // Spectrogram Paths (Web UI)
    // ========================================================================
    
    /**
     * Get spectrograms root directory.
     * 
     * @returns {string} Path: {data_root}/spectrograms/
     */
    getSpectrogramsRoot() {
        return join(this.dataRoot, 'spectrograms');
    }
    
    /**
     * Get spectrograms directory for a specific date.
     * 
     * @param {string} date - Date in YYYYMMDD format
     * @returns {string} Path: {data_root}/spectrograms/{YYYYMMDD}/
     */
    getSpectrogramsDateDir(date) {
        return join(this.getSpectrogramsRoot(), date);
    }
    
    /**
     * Get path for a specific spectrogram PNG.
     * 
     * @param {string} channelName - Channel name
     * @param {string} date - Date in YYYYMMDD format
     * @param {string} specType - Type ('carrier', 'archive', etc.)
     * @returns {string} Path: {data_root}/spectrograms/{YYYYMMDD}/{CHANNEL}_{YYYYMMDD}_{type}_spectrogram.png
     */
    getSpectrogramPath(channelName, date, specType = 'carrier') {
        const channelDir = channelNameToDir(channelName);
        const filename = `${channelDir}_${date}_${specType}_spectrogram.png`;
        return join(this.getSpectrogramsDateDir(date), filename);
    }
    
    // ========================================================================
    // State Paths (Service persistence)
    // ========================================================================
    
    /**
     * Get state directory.
     * 
     * @returns {string} Path: {data_root}/state/
     */
    getStateDir() {
        return join(this.dataRoot, 'state');
    }
    
    /**
     * Get analytics state file for a channel.
     * 
     * @param {string} channelName - Channel name
     * @returns {string} Path: {data_root}/state/analytics-{key}.json
     * 
     * Example: WWV 10 MHz -> analytics-wwv10.json
     */
    getAnalyticsStateFile(channelName) {
        const channelKey = channelNameToKey(channelName);
        return join(this.getStateDir(), `analytics-${channelKey}.json`);
    }
    
    /**
     * Get core recorder status file.
     * 
     * @returns {string} Path: {data_root}/state/core-recorder-status.json
     */
    getCoreStatusFile() {
        return join(this.getStateDir(), 'core-recorder-status.json');
    }
    
    // ========================================================================
    // System Status Paths
    // ========================================================================
    
    /**
     * Get system status directory.
     * 
     * @returns {string} Path: {data_root}/status/
     */
    getStatusDir() {
        return join(this.dataRoot, 'status');
    }
    
    /**
     * Get analytics service status file.
     * 
     * @returns {string} Path: {data_root}/status/analytics-service-status.json
     */
    getAnalyticsServiceStatusFile() {
        return join(this.getStatusDir(), 'analytics-service-status.json');
    }
    
    // ========================================================================
    // Discovery Methods
    // ========================================================================
    
    /**
     * Discover all channels with archive data.
     * 
     * @returns {string[]} List of channel names (human-readable format)
     */
    discoverChannels() {
        const archivesDir = join(this.dataRoot, 'archives');
        
        if (!existsSync(archivesDir)) {
            return [];
        }
        
        const channels = [];
        const entries = readdirSync(archivesDir, { withFileTypes: true });
        
        for (const entry of entries) {
            if (entry.isDirectory()) {
                channels.push(dirToChannelName(entry.name));
            }
        }
        
        return channels.sort();
    }
}

/**
 * Load GRAPEPaths from configuration file.
 * 
 * @param {string} configPath - Path to grape-config.toml (default: ./config/grape-config.toml)
 * @returns {GRAPEPaths} GRAPEPaths instance configured from TOML
 */
async function loadPathsFromConfig(configPath = null) {
    // Dynamic import to avoid breaking if toml not installed
    let toml;
    try {
        const tomlModule = await import('toml');
        toml = tomlModule.default || tomlModule;
    } catch (err) {
        throw new Error('toml package required: npm install toml');
    }
    
    if (!configPath) {
        // Default location
        configPath = join(__dirname, '..', 'config', 'grape-config.toml');
    }
    
    if (!existsSync(configPath)) {
        throw new Error(`Config file not found: ${configPath}`);
    }
    
    const configContent = readFileSync(configPath, 'utf8');
    const config = toml.parse(configContent);
    
    // Determine data root based on mode
    const mode = (config.recorder && config.recorder.mode) || 'test';
    
    let dataRoot;
    if (mode === 'production') {
        dataRoot = (config.recorder && config.recorder.production_data_root) || '/var/lib/signal-recorder';
    } else {
        dataRoot = (config.recorder && config.recorder.test_data_root) || '/tmp/grape-test';
    }
    
    return new GRAPEPaths(dataRoot);
}

export {
    GRAPEPaths,
    loadPathsFromConfig,
    channelNameToKey,
    channelNameToDir,
    dirToChannelName
};
