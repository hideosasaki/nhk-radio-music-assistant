#!/bin/sh
# Install/update nhk-radio-python SDK and provider files on every container start.

REPO_URL="https://github.com/hideosasaki/nhk-radio-music-assistant.git"
PROVIDER_DIR="nhk_radio_ma"
TMPDIR=$(mktemp -d)

echo "Fetching nhk-radio-music-assistant..."
if git clone --depth 1 --quiet "$REPO_URL" "$TMPDIR"; then
    # Install SDK
    echo "Installing nhk-radio-python SDK..."
    /app/venv/bin/uv pip install --quiet --reinstall --no-deps \
        "nhk-radio-python @ git+https://github.com/hideosasaki/nhk-radio-python.git" \
        && echo "SDK installed successfully." \
        || echo "WARNING: SDK install failed, using cached version."

    # Copy provider files
    DEST=$(/app/venv/bin/python -c "import music_assistant.providers as p, os; print(os.path.dirname(p.__file__))")
    DEST="${DEST}/${PROVIDER_DIR}"
    mkdir -p "$DEST"
    cp "$TMPDIR/${PROVIDER_DIR}/__init__.py" "$DEST/"
    cp "$TMPDIR/${PROVIDER_DIR}/manifest.json" "$DEST/"
    cp "$TMPDIR/${PROVIDER_DIR}/const.py" "$DEST/"
    cp "$TMPDIR/${PROVIDER_DIR}/_stub.py" "$DEST/"
    echo "Provider files installed to ${DEST}"
else
    echo "WARNING: Failed to fetch repository, using cached version."
fi

rm -rf "$TMPDIR"

# Delegate to the original entrypoint.
exec /usr/local/bin/entrypoint.sh "$@"
