#!/usr/bin/env bash
# capture.sh — capture MQTT and CoAP traffic for Task 4.
#
# The original assignment used tshark on the loopback interface. On macOS that
# requires root (BPF device access) and tshark was not installable here, so this
# script uses a no-root userspace recording proxy that writes genuine on-the-wire
# bytes into standard .pcap files (openable in Wireshark). AMQP is omitted per
# the assignment instruction to ignore the AMQP tasks.
#
# Requires: a Mosquitto broker on 127.0.0.1:1883 (start it with the snippet below)
#   /opt/homebrew/sbin/mosquitto -c config/mosquitto.conf   # or any local broker
#
# Usage:  bash scripts/capture.sh

set -e
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
OUTDIR="captures"
mkdir -p "$OUTDIR"

echo "[1/2] Capturing CoAP (port 5683 UDP)  — starts its own CoAP server..."
"$PY" scripts/capture_pcap.py coap

echo ""
echo "[2/2] Capturing MQTT (port 1883)  — requires a broker on 127.0.0.1:1883..."
"$PY" scripts/capture_pcap.py mqtt || {
    echo "  (MQTT capture needs a running broker — see header for how to start one)"
}

echo ""
echo "Captures saved:"
ls -lh "$OUTDIR"/*.pcap 2>/dev/null || echo "  (no pcap files found)"

echo ""
echo "Decode the key packets for report/packet_analysis.md with:"
echo "  $PY scripts/analyze_pcap.py both"
