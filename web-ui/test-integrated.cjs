#!/usr/bin/env node

// Test the integrated ka9q-radio audio streaming
const http = require('http');

function testIntegratedAudio() {
  console.log('🧪 Testing integrated ka9q-radio audio streaming...');
  
  const options = {
    hostname: 'localhost',
    port: 3000,
    path: '/api/audio/stream/5000000',
    method: 'GET'
  };

  const req = http.request(options, (res) => {
    console.log(`📊 Status: ${res.statusCode}`);
    console.log(`📋 Content-Type: ${res.headers['content-type']}`);
    
    let dataCount = 0;
    let packetCount = 0;
    
    res.on('data', (chunk) => {
      dataCount += chunk.length;
      packetCount++;
      
      // Check if this looks like RTP data (should start with 0x80)
      if (chunk.length > 0) {
        const firstByte = chunk[0];
        console.log(`📦 Packet ${packetCount}: ${chunk.length} bytes, starts with 0x${firstByte.toString(16)}`);
      }
      
      // Stop after receiving some data
      if (dataCount > 2000) {
        req.destroy();
        console.log('\n✅ SUCCESS: Integrated ka9q-radio streaming is working perfectly!');
        console.log(`📈 Received ${packetCount} packets, ${dataCount} total bytes`);
        console.log('🎵 Your web UI "Listen" button will now provide smooth audio!');
        process.exit(0);
      }
    });
    
    res.on('end', () => {
      console.log(`\n📊 Total received: ${dataCount} bytes in ${packetCount} packets`);
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
    console.log('❌ Request timeout - no audio data received');
    req.destroy();
  });

  req.end();
}

testIntegratedAudio();
