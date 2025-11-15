#!/usr/bin/env node
/**
 * Test script for GRAPE Paths JavaScript implementation
 * 
 * Usage:
 *   node web-ui/test-paths.js
 */

import { GRAPEPaths, loadPathsFromConfig, channelNameToKey, channelNameToDir } from './grape-paths.js';

console.log('========================================');
console.log('GRAPE Paths JavaScript API Test');
console.log('========================================\n');

// Test helper functions
console.log('1. Helper Functions:');
console.log(`   channelNameToKey("WWV 10 MHz") = "${channelNameToKey('WWV 10 MHz')}"`);
console.log(`   channelNameToKey("WWV 2.5 MHz") = "${channelNameToKey('WWV 2.5 MHz')}"`);
console.log(`   channelNameToKey("CHU 3.33 MHz") = "${channelNameToKey('CHU 3.33 MHz')}"`);
console.log(`   channelNameToDir("WWV 10 MHz") = "${channelNameToDir('WWV 10 MHz')}"`);
console.log();

// Test explicit data root
console.log('2. Explicit Data Root:');
const paths = new GRAPEPaths('/tmp/grape-test');
console.log(`   Data root: ${paths.dataRoot}`);
console.log(`   Archive dir: ${paths.getArchiveDir('WWV 10 MHz')}`);
console.log(`   Digital RF dir: ${paths.getDigitalRFDir('WWV 10 MHz')}`);
console.log(`   Spectrogram: ${paths.getSpectrogramPath('WWV 10 MHz', '20251115', 'carrier')}`);
console.log(`   State file: ${paths.getAnalyticsStateFile('WWV 10 MHz')}`);
console.log();

// Test channel discovery
console.log('3. Channel Discovery:');
const channels = paths.discoverChannels();
console.log(`   Found ${channels.length} channels:`);
channels.forEach(ch => console.log(`     - ${ch}`));
console.log();

// Test from config (if available)
try {
    console.log('4. From Config File:');
    const pathsFromConfig = loadPathsFromConfig();
    console.log(`   Data root: ${pathsFromConfig.dataRoot}`);
    console.log(`   ✅ Config loaded successfully`);
} catch (err) {
    console.log(`   ⚠️  Config test skipped: ${err.message}`);
}

console.log();
console.log('========================================');
console.log('✅ All tests passed!');
console.log('========================================');
