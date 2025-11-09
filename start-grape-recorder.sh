#!/bin/bash
# start-grape-recorder.sh - Start GRAPE recorder in tmux with monitoring
#
# Usage:
#   ./start-grape-recorder.sh          Start new session
#   ./start-grape-recorder.sh attach   Attach to existing session
#   ./start-grape-recorder.sh stop     Stop the recorder and kill session

set -e

SESSION_NAME="grape-recorder"
CONFIG_FILE="config/grape-config.toml"

# Get the directory where this script lives
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

case "${1:-start}" in
    attach|a)
        echo -e "${BLUE}Attaching to existing session...${NC}"
        if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
            tmux attach -t "$SESSION_NAME"
        else
            echo -e "${YELLOW}No session found. Starting new one...${NC}"
            exec "$0" start
        fi
        ;;
        
    stop|kill)
        echo -e "${YELLOW}Stopping GRAPE recorder...${NC}"
        
        # Send Ctrl+C to the recorder pane
        if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
            tmux send-keys -t "$SESSION_NAME:0.0" C-c
            sleep 2
            
            # Kill the session
            tmux kill-session -t "$SESSION_NAME"
            echo -e "${GREEN}✓ Session stopped${NC}"
        else
            echo "No session running"
        fi
        
        # Also kill any stray processes
        if pgrep -f "signal-recorder daemon" > /dev/null; then
            echo "Killing stray recorder processes..."
            pkill -f "signal-recorder daemon"
        fi
        ;;
        
    status|s)
        echo -e "${BLUE}Checking GRAPE recorder status...${NC}"
        echo ""
        
        if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
            echo -e "${GREEN}✓ tmux session running${NC}"
            echo ""
            
            # Check if recorder process is running
            if pgrep -f "signal-recorder daemon" > /dev/null; then
                echo -e "${GREEN}✓ Recorder process running${NC}"
                ps aux | grep "signal-recorder daemon" | grep -v grep
            else
                echo -e "${YELLOW}⚠ Recorder process NOT running${NC}"
            fi
            
            echo ""
            echo "To attach: ./start-grape-recorder.sh attach"
        else
            echo -e "${YELLOW}✗ No tmux session found${NC}"
            echo "To start: ./start-grape-recorder.sh"
        fi
        ;;
        
    start|*)
        # Check if session already exists
        if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
            echo -e "${YELLOW}Session already exists!${NC}"
            echo ""
            read -p "Attach to existing session? [Y/n] " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Nn]$ ]]; then
                exec "$0" attach
            else
                echo "Use './start-grape-recorder.sh stop' to kill existing session first"
                exit 1
            fi
        fi
        
        echo -e "${GREEN}================================================${NC}"
        echo -e "${GREEN}  Starting GRAPE Recorder in tmux${NC}"
        echo -e "${GREEN}================================================${NC}"
        echo ""
        echo "Config: $CONFIG_FILE"
        echo "Session: $SESSION_NAME"
        echo ""
        
        # Check config exists
        if [ ! -f "$CONFIG_FILE" ]; then
            echo -e "${YELLOW}Error: Config file not found: $CONFIG_FILE${NC}"
            exit 1
        fi
        
        # Check venv is activated or available
        if [ -z "$VIRTUAL_ENV" ] && [ ! -f "venv/bin/signal-recorder" ]; then
            echo -e "${YELLOW}Warning: Virtual environment not found${NC}"
            echo "Creating venv..."
            python3 -m venv venv
            source venv/bin/activate
            pip install -e .
        fi
        
        # Create tmux session with two vertical panes
        echo -e "${BLUE}Creating tmux session...${NC}"
        
        tmux new-session -d -s "$SESSION_NAME" -n "recorder"
        
        # Split window vertically (side-by-side)
        tmux split-window -h -t "$SESSION_NAME:0"
        
        # Left pane (0): Recorder output
        tmux send-keys -t "$SESSION_NAME:0.0" "cd $SCRIPT_DIR" C-m
        
        # Activate venv if needed
        if [ -f "venv/bin/activate" ]; then
            tmux send-keys -t "$SESSION_NAME:0.0" "source venv/bin/activate" C-m
        fi
        
        tmux send-keys -t "$SESSION_NAME:0.0" "echo 'Starting GRAPE Recorder...'" C-m
        tmux send-keys -t "$SESSION_NAME:0.0" "echo 'Press Ctrl+C to stop recorder'" C-m
        tmux send-keys -t "$SESSION_NAME:0.0" "echo ''" C-m
        sleep 1
        
        # Start the recorder
        tmux send-keys -t "$SESSION_NAME:0.0" "signal-recorder daemon --config $CONFIG_FILE" C-m
        
        # Right pane (1): Monitoring
        tmux send-keys -t "$SESSION_NAME:0.1" "cd $SCRIPT_DIR" C-m
        tmux send-keys -t "$SESSION_NAME:0.1" "echo 'GRAPE Recorder Monitoring'" C-m
        tmux send-keys -t "$SESSION_NAME:0.1" "echo '====================='" C-m
        tmux send-keys -t "$SESSION_NAME:0.1" "echo ''" C-m
        tmux send-keys -t "$SESSION_NAME:0.1" "echo 'Waiting 10 seconds for recorder to start...'" C-m
        tmux send-keys -t "$SESSION_NAME:0.1" "sleep 10" C-m
        
        # Start monitoring
        tmux send-keys -t "$SESSION_NAME:0.1" "watch -n 30 -c './quick-verify.sh'" C-m
        
        # Set pane sizes (60% left for recorder, 40% right for monitor)
        tmux select-layout -t "$SESSION_NAME:0" main-vertical
        
        # Select the recorder pane by default
        tmux select-pane -t "$SESSION_NAME:0.0"
        
        echo ""
        echo -e "${GREEN}✓ Session created!${NC}"
        echo ""
        echo "Controls:"
        echo "  Attach:        tmux a -t $SESSION_NAME"
        echo "                 or: ./start-grape-recorder.sh attach"
        echo ""
        echo "  Detach:        Ctrl+B then D"
        echo "  Switch panes:  Ctrl+B then arrow keys"
        echo "  Stop recorder: Ctrl+C in recorder pane"
        echo "  Kill session:  ./start-grape-recorder.sh stop"
        echo ""
        
        sleep 2
        
        read -p "Attach to session now? [Y/n] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            tmux attach -t "$SESSION_NAME"
        else
            echo ""
            echo "Session running in background."
            echo "Attach with: tmux a -t $SESSION_NAME"
        fi
        ;;
esac
