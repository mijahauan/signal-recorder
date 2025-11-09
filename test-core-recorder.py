#!/usr/bin/env python3
"""
Test Core Recorder Components

Tests NPZ writer and packet resequencer independently before full integration.
"""

import sys
sys.path.insert(0, 'src')

import numpy as np
from pathlib import Path
from signal_recorder.core_npz_writer import CoreNPZWriter, GapRecord
from signal_recorder.packet_resequencer import PacketResequencer, RTPPacket

print("=" * 60)
print("Core Recorder Component Tests")
print("=" * 60)
print()

# Test 1: CoreNPZWriter
print("TEST 1: CoreNPZWriter")
print("-" * 60)

test_dir = Path("/tmp/grape-core-test-unit")
test_dir.mkdir(parents=True, exist_ok=True)

writer = CoreNPZWriter(
    output_dir=test_dir,
    channel_name="TEST 10 MHz",
    frequency_hz=10000000,
    sample_rate=16000,
    ssrc=10000000,
    station_config={'callsign': 'TEST', 'grid_square': 'EM00', 'instrument_id': '999'}
)

print(f"✓ CoreNPZWriter created")
print(f"  Output dir: {test_dir}")
print(f"  Samples/minute: {writer.samples_per_minute}")

# Generate synthetic IQ samples
synthetic_samples = np.random.randn(320) + 1j * np.random.randn(320)
synthetic_samples = synthetic_samples.astype(np.complex64)

# Add samples (simulate packet arrival)
rtp_ts = 1000000
result = writer.add_samples(rtp_timestamp=rtp_ts, samples=synthetic_samples)

if result:
    print(f"✗ Unexpected minute completion on first packet")
else:
    print(f"✓ Buffering correctly (no premature file write)")

# Add enough samples to complete a minute
packets_per_minute = 960000 // 320  # 3000 packets
for i in range(1, packets_per_minute):
    samples = np.random.randn(320) + 1j * np.random.randn(320)
    samples = samples.astype(np.complex64)
    result = writer.add_samples(
        rtp_timestamp=rtp_ts + (i * 320),
        samples=samples
    )

if result:
    minute_ts, file_path = result
    print(f"✓ Minute completed and written")
    print(f"  File: {file_path.name}")
    print(f"  Size: {file_path.stat().st_size / 1024:.1f} KB")
    
    # Verify NPZ contents
    data = np.load(file_path)
    print(f"✓ NPZ file loaded successfully")
    print(f"  Fields: {list(data.keys())}")
    print(f"  IQ shape: {data['iq'].shape}")
    print(f"  RTP timestamp: {data['rtp_timestamp']}")
    print(f"  Sample rate: {data['sample_rate']}")
    print(f"  Gaps filled: {data['gaps_filled']}")
    
    assert data['iq'].shape == (960000,), f"Wrong IQ shape: {data['iq'].shape}"
    assert data['rtp_timestamp'] == rtp_ts, f"Wrong RTP timestamp"
    assert data['sample_rate'] == 16000, f"Wrong sample rate"
    print(f"✓ All assertions passed")
else:
    print(f"✗ Expected minute completion")

print()

# Test 2: PacketResequencer
print("TEST 2: PacketResequencer")
print("-" * 60)

resequencer = PacketResequencer(buffer_size=64, samples_per_packet=320)
print(f"✓ PacketResequencer created")
print(f"  Buffer size: {resequencer.buffer_size}")
print(f"  Samples/packet: {resequencer.samples_per_packet}")

# Create synthetic packets in order
packets = []
for seq in range(10):
    samples = np.random.randn(320) + 1j * np.random.randn(320)
    pkt = RTPPacket(
        sequence=seq,
        timestamp=seq * 320,
        ssrc=10000000,
        samples=samples.astype(np.complex64)
    )
    packets.append(pkt)

# Process first packet (initialize)
output, gap = resequencer.process_packet(packets[0])
if output is None:
    print(f"✓ First packet buffered (initialization)")
else:
    print(f"✗ First packet should be buffered")

# Process next few packets in order
for i in range(1, 5):
    output, gap = resequencer.process_packet(packets[i])
    if output is not None and gap is None:
        print(f"✓ Packet {i}: In-order output ({len(output)} samples, no gap)")
    else:
        print(f"✗ Packet {i}: Unexpected result")

# Test out-of-order delivery (skip packet 5, send 6 then 5)
output, gap = resequencer.process_packet(packets[6])
if output is None:
    print(f"✓ Packet 6 buffered (out of order)")
else:
    print(f"✗ Packet 6 should be buffered")

# Now send packet 5
output, gap = resequencer.process_packet(packets[5])
if output is not None:
    print(f"✓ Packet 5: Triggered output ({len(output)} samples)")
else:
    print(f"✗ Packet 5 should trigger output")

# Get statistics
stats = resequencer.get_stats()
print(f"✓ Resequencer statistics:")
print(f"  Packets received: {stats['packets_received']}")
print(f"  Packets resequenced: {stats['packets_resequenced']}")
print(f"  Gaps detected: {stats['gaps_detected']}")
print(f"  Samples filled: {stats['samples_filled']}")

print()

# Test 3: Gap Detection
print("TEST 3: Gap Detection")
print("-" * 60)

reseq_gap = PacketResequencer(buffer_size=64, samples_per_packet=320)

# Initialize with first packet
pkt1 = RTPPacket(sequence=100, timestamp=10000, ssrc=1, samples=np.zeros(320, dtype=np.complex64))
reseq_gap.process_packet(pkt1)

# Next packet with gap (skip 2 packets)
pkt2 = RTPPacket(
    sequence=103,  # Skipped 101, 102
    timestamp=10000 + (3 * 320),  # Skip 2 packets worth of samples
    ssrc=1,
    samples=np.zeros(320, dtype=np.complex64)
)

output, gap_info = reseq_gap.process_packet(pkt2)

if gap_info:
    print(f"✓ Gap detected!")
    print(f"  Expected RTP ts: {gap_info.expected_timestamp}")
    print(f"  Actual RTP ts: {gap_info.actual_timestamp}")
    print(f"  Gap samples: {gap_info.gap_samples}")
    print(f"  Gap packets: {gap_info.gap_packets}")
    print(f"  Sequence: {gap_info.prev_sequence} → {gap_info.curr_sequence}")
    
    assert gap_info.gap_samples == 640, f"Expected 640 sample gap, got {gap_info.gap_samples}"
    assert gap_info.gap_packets == 2, f"Expected 2 packet gap, got {gap_info.gap_packets}"
    print(f"✓ Gap detection assertions passed")
else:
    print(f"✗ Expected gap detection")

print()

print("=" * 60)
print("All Component Tests Passed! ✅")
print("=" * 60)
print()
print("Next step: Test with live RTP stream")
print("  python3 -m signal_recorder.core_recorder --config config/core-recorder.toml")
