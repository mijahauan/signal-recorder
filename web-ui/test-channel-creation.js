/**
 * Test script to verify channel creation actually works
 */

import { createChannel, verifyChannel } from './utils/radiod.js';

const testSSRC = 55555555;
const testFreq = 21074000;

console.log('Testing channel creation...');
console.log(`SSRC: ${testSSRC}`);
console.log(`Frequency: ${testFreq} Hz (${testFreq/1e6} MHz)`);
console.log('');

try {
  // Create channel
  console.log('Creating channel in radiod...');
  const result = await createChannel({
    ssrc: testSSRC,
    frequencyHz: testFreq,
    preset: 'iq',
    sampleRate: 16000,
    statusAddress: 'bee1-hf-status.local'
  });
  
  console.log('✅ Channel created successfully!');
  console.log('Result:', result);
  console.log('');
  
  // Verify
  console.log('Verifying channel exists...');
  const verification = await verifyChannel(testSSRC, 'bee1-hf-status.local');
  
  if (verification.exists) {
    console.log('✅ Channel verified in radiod!');
    console.log('Verification:', verification);
  } else {
    console.log('❌ Channel verification failed');
    console.log('Verification:', verification);
  }
  
} catch (error) {
  console.error('❌ Test failed:', error.message);
  console.error(error);
  process.exit(1);
}
