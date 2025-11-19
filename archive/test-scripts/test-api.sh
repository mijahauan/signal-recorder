#!/bin/bash
# Test the monitoring server API

echo "🧪 Testing GRAPE Monitoring Server API"
echo ""

# Start server in background
echo "Starting server..."
cd /home/mjh/git/signal-recorder/web-ui
node monitoring-server.js > /tmp/grape-monitoring-test.log 2>&1 &
SERVER_PID=$!

# Wait for server to start
echo "Waiting for server to start (PID: $SERVER_PID)..."
sleep 3

# Check if server is running
if ! kill -0 $SERVER_PID 2>/dev/null; then
    echo "❌ Server failed to start"
    cat /tmp/grape-monitoring-test.log
    exit 1
fi

echo "✅ Server started successfully"
echo ""

# Test API v1 endpoints
echo "Testing /api/v1/system/health..."
curl -s http://localhost:3000/api/v1/system/health | python3 -m json.tool
echo ""

echo "Testing /api/v1/system/status..."
curl -s http://localhost:3000/api/v1/system/status | python3 -m json.tool | head -40
echo ""

echo "Testing /api/v1/system/errors..."
curl -s "http://localhost:3000/api/v1/system/errors?limit=3" | python3 -m json.tool
echo ""

# Test legacy endpoint
echo "Testing legacy /api/monitoring/station-info..."
curl -s http://localhost:3000/api/monitoring/station-info | python3 -m json.tool | head -20
echo ""

# Stop server
echo "Stopping server (PID: $SERVER_PID)..."
kill $SERVER_PID
wait $SERVER_PID 2>/dev/null

echo "✅ Tests complete"
