#!/bin/bash
# Quick control script for GRAPE core recorder service

SERVICE_NAME="grape-core-recorder"

# Auto-detect if using system or user service
if systemctl --user is-enabled $SERVICE_NAME &>/dev/null; then
    SYSTEMCTL="systemctl --user"
    JOURNALCTL="journalctl --user"
    SERVICE_TYPE="user"
elif systemctl is-enabled $SERVICE_NAME &>/dev/null; then
    SYSTEMCTL="sudo systemctl"
    JOURNALCTL="sudo journalctl"
    SERVICE_TYPE="system"
else
    echo "❌ Service not installed. Run: ./install-core-recorder-service.sh"
    exit 1
fi

case "${1:-status}" in
    start)
        echo "Starting core recorder ($SERVICE_TYPE service)..."
        $SYSTEMCTL start $SERVICE_NAME
        sleep 2
        $SYSTEMCTL status $SERVICE_NAME --no-pager
        ;;
    
    stop)
        echo "Stopping core recorder..."
        $SYSTEMCTL stop $SERVICE_NAME
        ;;
    
    restart)
        echo "Restarting core recorder..."
        $SYSTEMCTL restart $SERVICE_NAME
        sleep 2
        $SYSTEMCTL status $SERVICE_NAME --no-pager
        ;;
    
    status|st)
        $SYSTEMCTL status $SERVICE_NAME --no-pager
        ;;
    
    logs|log)
        $JOURNALCTL -u $SERVICE_NAME -f
        ;;
    
    tail)
        $JOURNALCTL -u $SERVICE_NAME -n 50 --no-pager
        ;;
    
    enable)
        echo "Enabling core recorder to start at boot..."
        $SYSTEMCTL enable $SERVICE_NAME
        ;;
    
    disable)
        echo "Disabling auto-start at boot..."
        $SYSTEMCTL disable $SERVICE_NAME
        ;;
    
    *)
        echo "GRAPE Core Recorder Control"
        echo ""
        echo "Usage: $0 {start|stop|restart|status|logs|tail|enable|disable}"
        echo ""
        echo "Commands:"
        echo "  start    - Start core recorder service"
        echo "  stop     - Stop core recorder service"
        echo "  restart  - Restart core recorder service"
        echo "  status   - Show service status"
        echo "  logs     - Follow live logs (Ctrl+C to exit)"
        echo "  tail     - Show last 50 log lines"
        echo "  enable   - Enable auto-start at boot"
        echo "  disable  - Disable auto-start at boot"
        echo ""
        echo "Current status:"
        $SYSTEMCTL status $SERVICE_NAME --no-pager | head -20
        ;;
esac
