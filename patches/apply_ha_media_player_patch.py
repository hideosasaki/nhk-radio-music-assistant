"""Patch HA music_assistant media_player.py for live radio thumbnail updates.

See: https://github.com/hideosasaki/nhk-radio-music-assistant/issues/1

Idempotent: safe to run multiple times. Exits with code 0 on success/already-patched,
code 1 on error (e.g. target code not found due to HA version change).
"""

import sys

TARGET = "/usr/src/homeassistant/homeassistant/components/music_assistant/media_player.py"

# Original code block to find and replace
ORIGINAL = """\
        if queue and queue.current_item:
            # image_url is provided by an music-assistant queue
            image_url = self.mass.get_media_item_image_url(queue.current_item)
        elif player.current_media and player.current_media.image_url:
            # image_url is provided by an external source
            image_url = player.current_media.image_url
        else:
            image_url = None"""

PATCHED = """\
        if (
            player.current_media
            and player.current_media.image_url
            and player.current_media.media_type == MediaType.RADIO
        ):
            # For live radio, prefer the stream metadata image (updated per-program)
            # over the library image (frozen at favorite-add time).
            image_url = player.current_media.image_url
        elif queue and queue.current_item:
            # image_url is provided by an music-assistant queue
            image_url = self.mass.get_media_item_image_url(queue.current_item)
        elif player.current_media and player.current_media.image_url:
            # image_url is provided by an external source
            image_url = player.current_media.image_url
        else:
            image_url = None"""


def main() -> int:
    try:
        with open(TARGET, encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"ERROR: {TARGET} not found", file=sys.stderr)
        return 1

    if PATCHED in content:
        print("Already patched. Skipping.")
        return 0

    if ORIGINAL not in content:
        print(
            f"ERROR: Expected code block not found in {TARGET}. "
            "HA version may have changed.",
            file=sys.stderr,
        )
        return 1

    content = content.replace(ORIGINAL, PATCHED, 1)

    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(content)

    print("Patch applied successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
