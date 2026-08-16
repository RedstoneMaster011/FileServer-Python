#!/usr/bin/env bash
set -u

SERVER_PID=""
FUNNEL_PID=""
USE_TUNNEL=false
CLEANED=false

if [[ "${1:-}" == "--tunnel" ]]; then
    USE_TUNNEL=true
elif [[ $# -gt 0 ]]; then
    echo "Usage: ./RUN.sh [--tunnel]"
    exit 2
fi

cleanup() {
    $CLEANED && return
    CLEANED=true
    echo ""
    echo "[$(date +%T)] Shutting down..."
    [[ -n "$SERVER_PID" ]] && kill "$SERVER_PID" 2>/dev/null || true
    [[ -n "$FUNNEL_PID" ]] && kill "$FUNNEL_PID" 2>/dev/null || true
    [[ -n "$SERVER_PID" ]] && wait "$SERVER_PID" 2>/dev/null || true
    [[ -n "$FUNNEL_PID" ]] && wait "$FUNNEL_PID" 2>/dev/null || true
    echo "[$(date +%T)] Done."
}

trap cleanup EXIT SIGINT SIGTERM

run_server() {
    while true; do
        echo "[$(date +%T)] Starting Python File Server on Port 5000..."
        ./.venv/bin/python3 main.py &
        SERVER_PID=$!
        wait "$SERVER_PID" || true
        SERVER_PID=""
        echo "[$(date +%T)] Server stopped unexpectedly. Restarting in 2s..."
        sleep 2
    done
}

run_funnel() {
    # Give the python server 2 seconds to bind to port 5000 first
    sleep 2
    while true; do
        echo "[$(date +%T)] Ensuring Public Tailscale Funnel is Active..."

        # Reset the serve config and activate the funnel
        sudo tailscale serve http 5000 >/dev/null 2>&1
        sudo tailscale funnel ON &
        FUNNEL_PID=$!

        wait "$FUNNEL_PID" || true
        FUNNEL_PID=""
        echo "[$(date +%T)] Funnel dropped. Reconnecting in 5s..."
        sleep 5
    done
}

# Fire up the core web application logic
run_server &

if $USE_TUNNEL; then
    run_funnel &
    echo "LAN and secure Tailscale Funnel access enabled."
else
    echo "LAN access enabled. Start with --tunnel to also open Tailscale Funnel."
fi

# Keep the main process script alive
wait
