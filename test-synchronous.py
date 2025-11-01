#!/usr/bin/env python3
"""Test synchronous processing without background thread"""
import sys, os, time, wave, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from signal_recorder.audio_streamer import AudioStreamer

# Create a modified version that processes synchronously
class SynchronousAudioStreamer:
    def __init__(self, multicast_address, multicast_port, mode):
        self.multicast_address = multicast_address
        self.multicast_port = multicast_port
        self.mode = mode
        self.socket = None
        
    def get_chunk_sync(self, timeout=1.0):
        """Get one chunk synchronously without threading"""
        import socket, struct
        
        if not self.socket:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind(('', self.multicast_port))
            mreq = struct.pack('4sl', socket.inet_aton(self.multicast_address), socket.INADDR_ANY)
            self.socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        
        # Collect exactly 2 packets (640 samples)
        samples = []
        start = time.time()
        
        while len(samples) < 640 and time.time() - start < timeout:
            data, _ = self.socket.recvfrom(8192)
            if len(data) < 12:
                continue
                
            pkt_ssrc = struct.unpack('>I', data[8:12])[0]
            if pkt_ssrc != 5000000:  # WWV 5 MHz
                continue
            
            # Parse RTP header
            header_byte0 = data[0]
            csrc_count = header_byte0 & 0x0F
            has_extension = (header_byte0 & 0x10) != 0
            payload_offset = 12 + (csrc_count * 4)
            if has_extension and len(data) >= payload_offset + 4:
                ext_length_words = struct.unpack('>H', data[payload_offset+2:payload_offset+4])[0]
                payload_offset += 4 + (ext_length_words * 4)
            
            payload = data[payload_offset:]
            if len(payload) % 4 != 0:
                continue
            
            samples_int16 = np.frombuffer(payload, dtype='>i2').reshape(-1, 2)
            samples_float = samples_int16.astype(np.float32) / 32768.0
            iq = samples_float[:, 1] + 1j * samples_float[:, 0]
            
            samples.extend(iq)
        
        if len(samples) < 640:
            return None
        
        # Process exactly 640 samples
        iq_array = np.array(samples[:640])
        audio = np.abs(iq_array)
        audio = audio * 0.5
        audio_8k = audio[::2]
        audio_int16 = (audio_8k * 32767).astype(np.int16)
        
        return audio_int16.tobytes()

# Test synchronous processing
print("Testing synchronous audio processing...")
streamer = SynchronousAudioStreamer('239.192.152.141', 5004, 'AM')

chunks = []
for i in range(100):
    chunk = streamer.get_chunk_sync(timeout=0.1)
    if chunk:
        chunks.append(chunk)
    if (i+1) % 20 == 0:
        print(f"  {i+1}/100 chunks collected")

if streamer.socket:
    streamer.socket.close()

# Save result
all_data = b''.join(chunks)
with wave.open('/tmp/test-synchronous.wav', 'w') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(8000)
    w.writeframes(all_data)

print(f"\n✓ Saved {len(chunks)} chunks to /tmp/test-synchronous.wav")
print(f"  Duration: {len(all_data) // 2 / 8000:.2f} seconds")
print("\nPlay with: aplay /tmp/test-synchronous.wav")
print("\nIf this is smooth, the problem is AudioStreamer's threading!")
