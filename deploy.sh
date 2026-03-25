#!/bin/bash
# Deploy NHK Radio provider to Music Assistant Docker container
# and apply HA media_player patch for live radio thumbnails.
#
# Usage: ./deploy.sh <SSH_HOST|local>
#   SSH_HOST: user@hostname for remote Docker host
#   "local": for local Docker.

set -euo pipefail

SSH_HOST="${1:?Usage: ./deploy.sh <SSH_HOST|local>}"
CONTAINER="music-assistant"
HA_CONTAINER="homeassistant"
PROVIDER_DIR="nhk_radio_ma"
FILES="__init__.py manifest.json const.py _stub.py"
HA_PATCH="patches/apply_ha_media_player_patch.py"

run_cmd() {
    if [ "$SSH_HOST" = "local" ]; then
        eval "$1"
    else
        ssh "$SSH_HOST" "$1"
    fi
}

docker_exec() {
    run_cmd "docker exec $CONTAINER $1"
}

echo "Deploying to ${SSH_HOST}:${CONTAINER}"

# Find providers path
DEST=$(docker_exec '/app/venv/bin/python -c "import music_assistant.providers as p, os; print(os.path.dirname(p.__file__))"')
DEST="${DEST}/${PROVIDER_DIR}"
echo "Target: ${DEST}"

# Create dir and copy files
docker_exec "mkdir -p ${DEST}"
for f in $FILES; do
    if [ "$SSH_HOST" = "local" ]; then
        docker cp "${PROVIDER_DIR}/${f}" "${CONTAINER}:${DEST}/${f}"
    else
        cat "${PROVIDER_DIR}/${f}" | ssh "$SSH_HOST" "docker exec -i $CONTAINER sh -c 'cat > ${DEST}/${f}'"
    fi
    echo "  Copied ${f}"
done

# Install SDK in MA's venv
echo "Installing SDK..."
docker_exec '/app/venv/bin/uv pip install --quiet --reinstall --no-deps "nhk-radio-python @ git+https://github.com/hideosasaki/nhk-radio-python.git"'

echo "Restarting container..."
run_cmd "docker restart ${CONTAINER}"

echo ""
echo "=== MA deploy done ==="
echo "  ssh ${SSH_HOST} 'docker logs ${CONTAINER} 2>&1 | grep -i nhk'"

# --- HA media_player patch for live radio thumbnails (issue #1) ---
echo ""
echo "=== Applying HA media_player patch ==="

ha_docker_exec() {
    run_cmd "docker exec $HA_CONTAINER $1"
}

# Check if HA container exists
if ! run_cmd "docker inspect $HA_CONTAINER" > /dev/null 2>&1; then
    echo "  WARN: ${HA_CONTAINER} container not found. Skipping HA patch."
    exit 0
fi

# Copy patch script into HA container and run it
HA_PATCH_DEST="/tmp/apply_ha_media_player_patch.py"
if [ "$SSH_HOST" = "local" ]; then
    docker cp "${HA_PATCH}" "${HA_CONTAINER}:${HA_PATCH_DEST}"
else
    cat "${HA_PATCH}" | ssh "$SSH_HOST" "docker exec -i $HA_CONTAINER sh -c 'cat > ${HA_PATCH_DEST}'"
fi

PATCH_OUTPUT=$(ha_docker_exec "python ${HA_PATCH_DEST}" 2>&1) || true
echo "  ${PATCH_OUTPUT}"

if echo "${PATCH_OUTPUT}" | grep -q "applied successfully"; then
    # Clear pyc cache so HA picks up the patched file
    ha_docker_exec "find /usr/src/homeassistant/homeassistant/components/music_assistant/__pycache__ -name 'media_player.cpython-*.pyc' -delete" 2>/dev/null
    echo "Restarting ${HA_CONTAINER}..."
    run_cmd "docker restart ${HA_CONTAINER}"
    echo "=== HA patch done ==="
elif echo "${PATCH_OUTPUT}" | grep -q "Already patched"; then
    echo "=== HA patch skipped (already applied) ==="
else
    echo "  WARN: HA patch failed. See error above."
fi
