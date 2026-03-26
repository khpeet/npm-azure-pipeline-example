#!/usr/bin/env bash
# manage-container.sh — Container lifecycle management script.
# Runs on the TARGET LINUX HOST via SSH from the Azure DevOps pipeline.
#
# Actions:
#   create       — Pull image, start container via docker-compose.
#   restart      — Restart the running container to load updated config files.
#                  Used after add-devices or remove-devices updates devices.yaml.
#   start        — Start a previously stopped container using the preserved Docker container
#                  and existing config files in /etc/ktranslate/{containerID}/.
#   stop         — Stop the container without removing it or its config files.
#   remove       — Stop the container, remove it, and delete all config files.
#
# Usage:
#   ./manage-container.sh \
#     --action create|restart|start|stop|remove \
#     --container-id "npm-tokyo-01"
#
# Credentials are passed via environment variables (set by the CI/CD pipeline):
#   NR_INGEST_KEY — New Relic ingest key
#   NR_ACCOUNT_ID — New Relic account ID
#
# Prerequisites:
#   - Docker and docker-compose installed on the host
#   - Config files already copied to /etc/ktranslate/{containerID}/ (for create/start/restart)

set -euo pipefail

# ── Parse arguments ──────────────────────────────────────────
ACTION=""
CONTAINER_ID=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --action)        ACTION="$2"; shift 2 ;;
    --container-id)  CONTAINER_ID="$2"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

if [ -z "$ACTION" ] || [ -z "$CONTAINER_ID" ]; then
  echo "ERROR: --action and --container-id are required"
  exit 1
fi

# Credentials are required only for create (docker-compose up needs them)
NR_API_KEY="${NR_INGEST_KEY:-}"
if [[ "$ACTION" == "create" ]]; then
  if [ -z "$NR_API_KEY" ]; then
    echo "ERROR: NR_INGEST_KEY environment variable is required for $ACTION"
    exit 1
  fi
  if [ -z "${NR_ACCOUNT_ID:-}" ]; then
    echo "ERROR: NR_ACCOUNT_ID environment variable is required for $ACTION"
    exit 1
  fi
fi

CONFIG_DIR="/etc/ktranslate/${CONTAINER_ID}"
CONTAINER_NAME="ktranslate-${CONTAINER_ID}"

container_exists() {
  docker ps -a --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"
}

container_running() {
  docker ps --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"
}

echo "============================================"
echo "[$(date)] Container Management"
echo "  Action:       $ACTION"
echo "  Container ID: $CONTAINER_ID"
echo "  Container:    $CONTAINER_NAME"
echo "  Config Dir:   $CONFIG_DIR"
echo "============================================"

# ── Action: CREATE ───────────────────────────────────────────
create_container() {
  echo "[$(date)] Creating container $CONTAINER_NAME..."

  if [ ! -f "$CONFIG_DIR/snmp-base.yaml" ]; then
    echo "ERROR: snmp-base.yaml not found in $CONFIG_DIR"
    exit 1
  fi

  if [ ! -f "$CONFIG_DIR/devices.yaml" ]; then
    echo "ERROR: devices.yaml not found in $CONFIG_DIR"
    exit 1
  fi

  if [ ! -f "$CONFIG_DIR/docker-compose.yml" ]; then
    echo "ERROR: docker-compose.yml not found in $CONFIG_DIR"
    exit 1
  fi

  # Write .env file for docker-compose (persists credentials for restarts)
  ENV_FILE="$CONFIG_DIR/.env"
  echo "NR_INGEST_KEY=${NR_API_KEY}" > "$ENV_FILE"
  echo "NR_ACCOUNT_ID=${NR_ACCOUNT_ID}" >> "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "Credentials written to $ENV_FILE (chmod 600)"

  # Check if container already exists
  if container_exists; then
    echo "WARNING: Container $CONTAINER_NAME already exists. Stopping it first."
    cd "$CONFIG_DIR"
    docker-compose down --timeout 30 2>/dev/null || true
  fi

  # Pull latest image
  docker pull kentik/ktranslate:v2 2>&1

  # Start container
  cd "$CONFIG_DIR"
  docker-compose up -d 2>&1

  echo "[$(date)] Container $CONTAINER_NAME created and started."
}

# ── Action: RESTART ──────────────────────────────────────────
# Used after add-devices or remove-devices updates config files on disk.
# Performs a down+up rather than restart to ensure changed volume mounts are re-read.
restart_container() {
  echo "[$(date)] Restarting container $CONTAINER_NAME to load updated config..."

  if [ ! -f "$CONFIG_DIR/snmp-base.yaml" ]; then
    echo "ERROR: snmp-base.yaml not found in $CONFIG_DIR"
    exit 1
  fi

  if [ ! -f "$CONFIG_DIR/devices.yaml" ]; then
    echo "ERROR: devices.yaml not found in $CONFIG_DIR"
    exit 1
  fi

  if [ ! -f "$CONFIG_DIR/docker-compose.yml" ]; then
    echo "ERROR: docker-compose.yml not found in $CONFIG_DIR"
    exit 1
  fi

  cd "$CONFIG_DIR"
  docker-compose down --timeout 30 2>&1
  docker-compose up -d 2>&1

  echo "[$(date)] Container $CONTAINER_NAME restarted."
}

# ── Action: STOP ─────────────────────────────────────────────
stop_container() {
  echo "[$(date)] Stopping container $CONTAINER_NAME..."

  if [ ! -d "$CONFIG_DIR" ]; then
    echo "WARNING: Config directory $CONFIG_DIR not found."
  fi

  if ! container_exists; then
    echo "WARNING: Container $CONTAINER_NAME does not exist. Nothing to stop."
    return 0
  fi

  if ! container_running; then
    echo "WARNING: Container $CONTAINER_NAME is already stopped. Nothing to do."
    return 0
  fi

  docker stop "$CONTAINER_NAME" 2>&1

  echo "[$(date)] Container $CONTAINER_NAME stopped and preserved."
}

# ── Action: START ────────────────────────────────────────────
# Starts a previously stopped container using the preserved Docker container.
# Unlike create, this does not pull a new image, recreate the container, or regenerate config files.
start_container() {
  echo "[$(date)] Starting preserved container $CONTAINER_NAME..."

  if [ ! -f "$CONFIG_DIR/snmp-base.yaml" ]; then
    echo "ERROR: snmp-base.yaml not found in $CONFIG_DIR"
    echo "       Hint: run 'create' first to initialise the container."
    exit 1
  fi

  if [ ! -f "$CONFIG_DIR/devices.yaml" ]; then
    echo "ERROR: devices.yaml not found in $CONFIG_DIR"
    echo "       Hint: run 'create' first to initialise the container."
    exit 1
  fi

  if [ ! -f "$CONFIG_DIR/docker-compose.yml" ]; then
    echo "ERROR: docker-compose.yml not found in $CONFIG_DIR"
    echo "       Hint: run 'create' first to initialise the container."
    exit 1
  fi

  if [ ! -f "$CONFIG_DIR/.env" ]; then
    echo "ERROR: .env not found in $CONFIG_DIR"
    echo "       Hint: run 'create' first to write credentials, then use 'stop'/'start' to cycle the container."
    exit 1
  fi

  if ! container_exists; then
    echo "ERROR: Container $CONTAINER_NAME does not exist."
    echo "       Hint: if the container was removed, run 'create' to provision it again."
    exit 1
  fi

  # Idempotency: skip if already running
  if container_running; then
    echo "WARNING: Container $CONTAINER_NAME is already running. Nothing to do."
    exit 0
  fi

  docker start "$CONTAINER_NAME" 2>&1

  echo "[$(date)] Container $CONTAINER_NAME started."
}

# ── Action: REMOVE ───────────────────────────────────────────
remove_container() {
  echo "[$(date)] Removing container $CONTAINER_NAME..."

  # Stop the container first
  stop_container

  if container_exists; then
    echo "Removing container: $CONTAINER_NAME"
    docker rm "$CONTAINER_NAME" 2>&1
  else
    echo "WARNING: Container $CONTAINER_NAME does not exist. Continuing with config cleanup."
  fi

  # Remove config directory (includes snmp-base.yaml, devices.yaml, docker-compose.yml)
  if [ -d "$CONFIG_DIR" ]; then
    echo "Removing config directory: $CONFIG_DIR"
    rm -rf "$CONFIG_DIR"
  else
    echo "WARNING: Config directory $CONFIG_DIR not found. Nothing to remove."
  fi

  echo "[$(date)] Container $CONTAINER_NAME and its config have been removed."
}

# ── Execute the requested action ─────────────────────────────
case "$ACTION" in
  create)  create_container ;;
  restart) restart_container ;;
  start)   start_container ;;
  stop)    stop_container ;;
  remove)  remove_container ;;
  *)
    echo "ERROR: Unknown action: $ACTION"
    echo "Valid actions: create, restart, start, stop, remove"
    exit 1
    ;;
esac

echo "[$(date)] Action '$ACTION' completed successfully."
