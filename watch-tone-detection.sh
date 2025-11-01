#!/bin/bash
# Watch for WWV tone detection attempts and results
echo "Monitoring WWV tone detection (Ctrl+C to stop)..."
echo "Waiting for next minute boundary (:59-:02 window)..."
echo ""

tail -f /home/mjh/git/signal-recorder/logs/daemon.log | grep --line-buffered -E "Checking for WWV|WWV detector:|WWV tone detected|❌"
