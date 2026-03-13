#!/bin/bash
# Deploy NHK Radio provider to Music Assistant Docker container.
#
# Usage: ./deploy.sh <SSH_HOST|local>
#   SSH_HOST: user@hostname for remote Docker host
#   "local": for local Docker.

set -euo pipefail

SSH_HOST="${1:?Usage: ./deploy.sh <SSH_HOST|local>}"
CONTAINER="music-assistant"
PROVIDER_DIR="nhk_radio_ma"
FILES="__init__.py manifest.json const.py _stub.py"

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
docker_exec '/app/venv/bin/python -m pip install --quiet --force-reinstall --no-deps "nhk-radio-python @ git+https://github.com/hideosasaki/nhk-radio-python.git"'

echo "Restarting container..."
run_cmd "docker restart ${CONTAINER}"

echo "Done. Check logs:"
echo "  ssh ${SSH_HOST} 'docker logs ${CONTAINER} 2>&1 | grep -i nhk'"
