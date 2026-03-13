"""Stub MusicProvider base class for use without MA server installed."""

from __future__ import annotations

import logging
from typing import Any


class MusicProvider:
    """Minimal stub of music_assistant.models.music_provider.MusicProvider."""

    def __init__(
        self,
        mass: Any,
        manifest: Any,
        config: Any,
        supported_features: set[Any],
    ) -> None:
        self.mass = mass
        self.manifest = manifest
        self.config = config
        self._supported_features = supported_features
        self.logger = logging.getLogger(self.__class__.__name__)
        self.available = False

    @property
    def domain(self) -> str:
        return getattr(self.manifest, "domain", "nhk_radio_ma")

    @property
    def instance_id(self) -> str:
        return getattr(self.config, "instance_id", "nhk_radio_ma")

    def update_config_value(self, key: str, value: Any) -> None:
        pass

    async def recommendations(self) -> list:
        """Return recommendations (stub)."""
        return []
