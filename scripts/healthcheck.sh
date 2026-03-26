#!/usr/bin/env bash
# healthcheck.sh — Verifies a ktranslate container is running after deployment.
# Called by the Azure DevOps pipeline via SSH task after manage-container.sh.
#
# Usage:
#   ./healthcheck.sh [container-name]
#
# If no container name is provided, defaults to "ktranslate-snmp".
# Waits up to MAX_WAIT seconds for the container to reach "running" state,
# then checks recent logs for fatal errors.

set -euo pipefail

CONTAINER="${1:-ktranslate-snmp}"
MAX_WAIT=30

echo "Checking container $CONTAINER..."

for i in $(seq 1 $MAX_WAIT); do
  STATUS=$(docker inspect --format='{{.State.Status}}' "$CONTAINER" 2>/dev/null || echo "missing")
  if [ "$STATUS" = "running" ]; then
    echo "Container running after ${i}s"

    # Check for fatal errors in recent logs
    if docker logs --since=10s "$CONTAINER" 2>&1 | grep -qi "fatal\|panic"; then
      echo "ERROR: Fatal errors detected in container logs"
      docker logs --since=30s "$CONTAINER" 2>&1 | tail -20
      exit 1
    fi

    echo "Health check passed."
    exit 0
  fi
  sleep 1
done

echo "ERROR: Container did not reach running state within ${MAX_WAIT}s"
docker logs "$CONTAINER" 2>&1 | tail -20
exit 1
