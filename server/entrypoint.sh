#!/bin/sh
# Install/update nhk-radio-python SDK on every container start.
echo "Installing nhk-radio-python SDK..."
/app/venv/bin/uv pip install --quiet --reinstall --no-deps \
    "nhk-radio-python @ git+https://github.com/hideosasaki/nhk-radio-python.git" \
    && echo "SDK installed successfully." \
    || echo "WARNING: SDK install failed, using cached version."

# Delegate to the original entrypoint.
exec /usr/local/bin/entrypoint.sh "$@"
