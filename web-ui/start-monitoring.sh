#!/bin/bash
# Start GRAPE Monitoring Server (Simplified, No Auth)

cd "$(dirname "$0")"

echo "🚀 Starting GRAPE Monitoring Server..."
echo ""

# Stop any existing instance
pkill -f monitoring-server.js 2>/dev/null
sleep 1

# Start the server
nohup node monitoring-server.js > monitoring-server.log 2>&1 &

sleep 2

# Check if it started
if pgrep -f monitoring-server.js > /dev/null; then
    echo "✅ Server started successfully!"
    echo ""
    echo "📊 Access the dashboard:"
    echo "   http://localhost:3000/"
    echo ""
    echo "📝 View logs:"
    echo "   tail -f monitoring-server.log"
    echo ""
else
    echo "❌ Failed to start server"
    echo "Check monitoring-server.log for errors"
    exit 1
fi
