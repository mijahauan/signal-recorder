#!/usr/bin/env python3
"""Debug what's happening at chunk boundaries"""
import sys, os, time, wave, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from signal_recorder.audio_streamer import AudioStreamer

# Monkey patch to save exactly what's being processed
original_demodulate = AudioStreamer._demodulate
processed_chunks = []

def debug_demodulate(self, iq_samples):
    """Save raw IQ and processed audio for analysis"""
    # Call original
    audio = original_demodulate(self, iq_samples)
    
    # Save for analysis
    processed_chunks.append({
        'iq_samples': iq_samples.copy(),
        'audio_16k': audio.copy(),
        'chunk_len': len(iq_samples)
    })
    
    return audio

AudioStreamer._demodulate = debug_demodulate

# Run test
streamer = AudioStreamer(
    multicast_address='239.192.152.141',
    multicast_port=5004,
    mode='AM',
    audio_rate=8000
)

print("Starting streamer...")
streamer.start()
time.sleep(0.5)

# Collect chunks
chunks = []
for i in range(100):
    chunk = streamer.get_audio_chunk(timeout=0.1)
    chunks.append(chunk)

streamer.stop()

print(f"\nCollected {len(processed_chunks)} processed chunks")

# Analyze chunk boundaries
print("\n=== CHUNK ANALYSIS ===")
chunk_lengths = [c['chunk_len'] for c in processed_chunks]
print(f"IQ chunk lengths: min={min(chunk_lengths)}, max={max(chunk_lengths)}")
print(f"Unique lengths: {set(chunk_lengths)}")

# Check first and last samples of each chunk for discontinuities
print("\n=== CHECKING BOUNDARY DISCONTINUITIES ===")
discontinuities = []
for i in range(1, len(processed_chunks)):
    prev_last = processed_chunks[i-1]['audio_16k'][-1]
    curr_first = processed_chunks[i]['audio_16k'][0]
    diff = abs(curr_first - prev_last)
    if diff > 0.1:  # Arbitrary threshold
        discontinuities.append((i, diff))
        if len(discontinuities) <= 10:
            print(f"Chunk {i-1}→{i}: discontinuity = {diff:.3f}")

print(f"\nTotal discontinuities >0.1: {len(discontinuities)}")

# Save the raw IQ that was processed
all_iq = np.concatenate([c['iq_samples'] for c in processed_chunks])
print(f"\nTotal IQ processed: {len(all_iq)} samples")

# Create a version processed exactly like the chunks
all_audio = np.concatenate([c['audio_16k'] for c in processed_chunks])
all_audio_8k = all_audio[::2]
all_audio_int16 = (all_audio_8k * 32767).astype(np.int16)

with wave.open('/tmp/debug-chunked.wav', 'w') as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(8000)
    w.writeframes(all_audio_int16.tobytes())

print(f"\nSaved: /tmp/debug-chunked.wav")
print("This should be identical to realtime-test.wav if processing is consistent")
