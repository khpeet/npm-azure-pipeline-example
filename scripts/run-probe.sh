#!/usr/bin/env bash
# run-probe.sh — Runs a temporary ktranslate discovery container to fingerprint devices.
# Runs on the TARGET LINUX HOST (not the pipeline runner).
# Pure bash + docker — no Python or pyyaml required.
#
# Uses -snmp_out_file to write discovery results to a scratch file (discovered-snmp.yaml),
# avoiding mutation of the input probe config.
#
# Usage:
#   ./run-probe.sh --container-id "npm-dc01-01" [--timeout 120]
#
# Output:
#   /etc/ktranslate/probe-{containerID}/discovered-snmp.yaml
#
# Prerequisites:
#   - snmp-probe.yaml already copied to /etc/ktranslate/probe-{containerID}/
#   - Docker installed on the host

set -euo pipefail

CONTAINER_ID=""
PROBE_TIMEOUT=120
KT_IMAGE="kentik/ktranslate:v2"

while [[ $# -gt 0 ]]; do
  case $1 in
    --container-id) CONTAINER_ID="$2"; shift 2 ;;
    --timeout)      PROBE_TIMEOUT="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

if [ -z "$CONTAINER_ID" ]; then
  echo "ERROR: --container-id is required"
  exit 1
fi

PROBE_DIR="/etc/ktranslate/probe-${CONTAINER_ID}"
PROBE_CONFIG="$PROBE_DIR/snmp-probe.yaml"
PROBE_OUTPUT="$PROBE_DIR/discovered-snmp.yaml"
HOST_UID="$(id -u)"
HOST_GID="$(id -g)"

if [ ! -f "$PROBE_CONFIG" ]; then
  echo "ERROR: snmp-probe.yaml not found in $PROBE_DIR"
  exit 1
fi

if [ ! -w "$PROBE_DIR" ]; then
  echo "ERROR: Probe directory is not writable: $PROBE_DIR"
  exit 1
fi

# Remove any stale output from a previous run.
# Pre-create the file so the container can always open it on the bind mount.
rm -f "$PROBE_OUTPUT"
touch "$PROBE_OUTPUT"
chmod 666 "$PROBE_OUTPUT"

echo "Starting ktranslate discovery probe..."
echo "  Config:  $PROBE_CONFIG"
echo "  Output:  $PROBE_OUTPUT"
echo "  Timeout: ${PROBE_TIMEOUT}s"
echo "  Image:   $KT_IMAGE"

# Run the discovery container in the foreground.
# --rm auto-removes the container on exit.
# Run with the current host UID/GID so the container can write to the bind mount.
# -snmp_out_file writes results to the scratch file instead of mutating the input config.
# Docker will use the local image when present and only pull if it is missing.
# 'timeout' kills the container if discovery takes too long.
PROBE_EXIT=0
if timeout "${PROBE_TIMEOUT}" docker run --rm \
  --network host \
  --user "${HOST_UID}:${HOST_GID}" \
  -v "${PROBE_CONFIG}:/snmp-base.yaml:ro" \
  -v "${PROBE_DIR}:/work" \
  "$KT_IMAGE" \
    -snmp /snmp-base.yaml \
    -snmp_out_file /work/discovered-snmp.yaml \
    -snmp_discovery=true \
    -log_level info; then
  :
else
  PROBE_EXIT=$?
  echo "WARNING: ktranslate discovery probe exited with status ${PROBE_EXIT}." >&2
fi

if [ -s "$PROBE_OUTPUT" ]; then
  DEVICE_COUNT=$(grep -c "device_ip:" "$PROBE_OUTPUT" 2>/dev/null || echo "0")
  echo "Probe complete. Discovered ${DEVICE_COUNT} device(s)."
else
  echo "WARNING: No discovery output file produced. Devices may be unreachable via SNMP."
  echo "Pipeline will fall back to user-provided device values."
  # Create an empty output so the pipeline step can handle gracefully.
  echo "{}" > "$PROBE_OUTPUT"
fi

echo "Probe finished."
