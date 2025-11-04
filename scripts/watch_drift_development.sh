#!/bin/bash
# Watch drift development over time for multi-station detection analysis

LOG_FILE="/tmp/grape-test/logs/recorder_$(date +%Y%m%d)_*.log"

echo "================================================"
echo "🔍 Drift Development Monitor"
echo "================================================"
echo ""
echo "Press Ctrl+C to stop"
echo ""

while true; do
    clear
    echo "================================================"
    echo "🔍 Drift Development Monitor - $(date +%H:%M:%S)"
    echo "================================================"
    echo ""
    
    # First detections (time_snap establishment)
    echo "📍 TIME_SNAP ESTABLISHMENTS:"
    grep "TIME_SNAP ESTABLISHED" $LOG_FILE 2>/dev/null | tail -10 | while read line; do
        echo "  $(echo $line | grep -oP '(WWV|CHU)_[0-9.]+_MHz.*')"
    done
    echo ""
    
    # Drift measurements by channel
    echo "📊 DRIFT MEASUREMENTS (recent 5 per channel):"
    for channel in WWV_2.5_MHz WWV_5_MHz WWV_10_MHz WWV_15_MHz WWV_20_MHz WWV_25_MHz CHU_3.33_MHz CHU_7.85_MHz CHU_14.67_MHz; do
        drifts=$(grep "$channel.*drift =" $LOG_FILE 2>/dev/null | tail -5)
        if [ ! -z "$drifts" ]; then
            echo ""
            echo "  $channel:"
            echo "$drifts" | while read line; do
                drift=$(echo $line | grep -oP 'drift = [+-][0-9.]+')
                time=$(echo $line | grep -oP '\d{2}:\d{2}:\d{2}')
                echo "    [$time] $drift"
            done
        fi
    done
    echo ""
    
    # Multi-station detections (WWV + WWVH differential delay)
    echo "🌍 DIFFERENTIAL PROPAGATION DELAYS:"
    grep "Differential propagation delay" $LOG_FILE 2>/dev/null | tail -5 | while read line; do
        echo "  $(echo $line | grep -oP '(WWV|CHU)_[0-9.]+_MHz.*')"
    done
    [ -z "$(grep "Differential propagation delay" $LOG_FILE 2>/dev/null)" ] && echo "  (Waiting for WWV+WWVH simultaneous detections...)"
    echo ""
    
    # Summary statistics
    echo "📈 SUMMARY (all time):"
    total_est=$(grep "TIME_SNAP ESTABLISHED" $LOG_FILE 2>/dev/null | wc -l)
    total_drift=$(grep "drift =" $LOG_FILE 2>/dev/null | wc -l)
    total_diff=$(grep "Differential propagation delay" $LOG_FILE 2>/dev/null | wc -l)
    
    echo "  Time_snap established: $total_est channels"
    echo "  Drift measurements: $total_drift"
    echo "  WWV+WWVH differential delays: $total_diff"
    
    # Calculate average drift if we have measurements
    if [ $total_drift -gt 0 ]; then
        avg_drift=$(grep "drift =" $LOG_FILE 2>/dev/null | grep -oP 'drift = [+-]\K[0-9.]+' | awk '{sum+=$1; count++} END {if(count>0) print sum/count}')
        echo "  Average drift: ${avg_drift} ms"
    fi
    
    echo ""
    echo "Press Ctrl+C to stop | Updates every 30s"
    echo "================================================"
    
    sleep 30
done
