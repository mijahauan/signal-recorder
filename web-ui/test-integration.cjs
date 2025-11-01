#!/usr/bin/env node

// Test the ka9q-radio proxy integration
const http = require('http');

function testAudioStream() {
  console.log('Testing audio stream integration...');
  
  const options = {
    hostname: 'localhost',
    port: 3000,
    path: '/api/audio/stream/5000000',
    method: 'GET'
  };

  const req = http.request(options, (res) => {
    console.log(`Status: ${res.statusCode}`);
    console.log(`Headers:`, res.headers);
    
    let dataCount = 0;
    res.on('data', (chunk) => {
      dataCount += chunk.length;
      console.log(`Received ${chunk.length} bytes (total: ${dataCount})`);
      
      // Stop after receiving some data
      if (dataCount > 1000) {
        req.destroy();
        console.log('✅ Integration test successful - receiving audio data!');
        process.exit(0);
      }
    });
    
    res.on('end', () => {
      console.log(`Total received: ${dataCount} bytes`);
      if (dataCount > 0) {
        console.log('✅ Integration test successful!');
      } else {
        console.log('❌ No audio data received');
      }
    });
  });

  req.on('error', (e) => {
    console.error(`❌ Request error: ${e.message}`);
  });

  req.setTimeout(5000, () => {
    console.log('❌ Request timeout');
    req.destroy();
  });

  req.end();
}

testAudioStream();
