#!/usr/bin/env bash
set -u

SERVER_PID=""
TUNNEL_PID=""
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
    [[ -n "$TUNNEL_PID" ]] && kill "$TUNNEL_PID" 2>/dev/null || true
    [[ -n "$SERVER_PID" ]] && wait "$SERVER_PID" 2>/dev/null || true
    [[ -n "$TUNNEL_PID" ]] && wait "$TUNNEL_PID" 2>/dev/null || true
    echo "[$(date +%T)] Done."
}

trap cleanup EXIT SIGINT SIGTERM

run_server() {
    local child_pid=""
    trap '[[ -n "$child_pid" ]] && kill "$child_pid" 2>/dev/null || true; exit 0' SIGINT SIGTERM
    while true; do
        echo "[$(date +%T)] Starting Python File Server..."
        ./.venv/bin/python3 main.py &
        child_pid=$!
        wait "$child_pid" || true
        child_pid=""
        echo "[$(date +%T)] Server stopped. Restarting in 2s..."
        sleep 2
    done
}

run_tunnel() {
    local child_pid=""
    trap '[[ -n "$child_pid" ]] && kill "$child_pid" 2>/dev/null || true; exit 0' SIGINT SIGTERM
    while true; do
        echo "[$(date +%T)] Opening LocalTunnel..."
        lt --port 5000 --subdomain redstonemaster01-files-drive &
        child_pid=$!
        wait "$child_pid" || true
        child_pid=""
        echo "[$(date +%T)] Tunnel dropped. Restarting in 5s..."
        sleep 5
    done
}

run_server &
SERVER_PID=$!

if $USE_TUNNEL; then
    run_tunnel &
    TUNNEL_PID=$!
    echo "LAN and tunnel access enabled."
else
    echo "LAN access enabled. Start with --tunnel to also open LocalTunnel."
fi

wait "$SERVER_PID"
