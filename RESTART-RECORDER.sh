#!/bin/bash
# Quick script to restart the recorder cleanly

echo "Stopping recorder..."
pkill -f "signal-recorder daemon"
sleep 2

echo "Starting recorder in tmux..."
cd /home/mjh/git/signal-recorder
./start-grape-recorder.sh start

echo ""
echo "Recorder restarted!"
echo "Attach to tmux session with: ./start-grape-recorder.sh attach"
echo ""
echo "Status should now show correct packet counts within 30 seconds."
