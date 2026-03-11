"""NHK Radio provider for Music Assistant."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from typing import TYPE_CHECKING, Any

from music_assistant_models.enums import (
    ContentType,
    ImageType,
    MediaType,
    ProviderFeature,
    StreamType,
)
from music_assistant_models.media_items import (
    AudioFormat,
    BrowseFolder,
    MediaItemImage,
    MediaItemMetadata,
    ProviderMapping,
    Radio,
    SearchResults,
    UniqueList,
)
from music_assistant_models.streamdetails import StreamDetails, StreamMetadata
from nhk_radio import (
    LiveInfo,
    NhkRadioClient,
    OndemandProgram,
    OndemandSeries,
)

from .const import AREAS, CONF_AREA, CONF_STORED_RADIOS, DOMAIN, KANA_MAP

try:
    from music_assistant.models.music_provider import (
        MusicProvider,
    )
except ImportError:
    from ._stub import MusicProvider  # type: ignore[assignment]

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ConfigEntry

SUPPORTED_FEATURES = {
    ProviderFeature.BROWSE,
    ProviderFeature.SEARCH,
    ProviderFeature.LIBRARY_RADIOS,
    ProviderFeature.LIBRARY_RADIOS_EDIT,
}


async def setup(mass: Any, manifest: Any, config: Any) -> NhkRadioProvider:
    """Set up the NHK Radio provider."""
    return NhkRadioProvider(mass, manifest, config, SUPPORTED_FEATURES)


async def get_config_entries(
    mass: Any,  # noqa: ARG001
    instance_id: str | None = None,  # noqa: ARG001
    action: str | None = None,  # noqa: ARG001
    values: dict[str, Any] | None = None,  # noqa: ARG001
) -> tuple[ConfigEntry, ...]:
    """Get config entries for this provider."""
    from music_assistant_models.config_entries import (
        ConfigEntry,
        ConfigEntryType,
        ConfigValueOption,
    )

    area_options = [
        ConfigValueOption(title=name, value=area_id)
        for area_id, name in AREAS.items()
    ]

    return (
        ConfigEntry(
            key=CONF_AREA,
            type=ConfigEntryType.STRING,
            label="Area",
            default_value="tokyo",
            required=True,
            options=area_options,
        ),
        ConfigEntry(
            key=CONF_STORED_RADIOS,
            type=ConfigEntryType.STRING,
            label=CONF_STORED_RADIOS,
            default_value=[],
            hidden=True,
            multi_value=True,
        ),
    )


class NhkRadioProvider(MusicProvider):
    """NHK Radio Music Provider."""

    _client: NhkRadioClient

    async def handle_async_init(self) -> None:
        """Initialize the provider."""
        self._client = NhkRadioClient(
            self.mass.http_session,
            area=self.config.get_value(CONF_AREA),
        )
        await self._client.get_channels()
        self.available = True

    # --- Browse ---

    async def browse(self, path: str) -> Sequence[Radio | BrowseFolder]:
        """Browse NHK Radio content."""
        # Strip provider prefix if present
        if path.startswith(f"{DOMAIN}://"):
            path = path.removeprefix(f"{DOMAIN}://")

        if not path or path == "/":
            return self._browse_root()

        parts = path.strip("/").split("/")
        category = parts[0]

        if category == "live":
            return await self._browse_live()

        if category == "new":
            if len(parts) == 1:
                return await self._browse_series_list(
                    await self._client.get_ondemand_new_arrivals(),
                    path_prefix="new",
                )
            if len(parts) == 2:
                return await self._browse_episodes(*self._split_series_key(parts[1]))

        if category == "genre":
            if len(parts) == 1:
                return await self._browse_genre_list()
            if len(parts) == 2:
                return await self._browse_series_list(
                    await self._client.get_ondemand_by_genre(parts[1]),
                    path_prefix=f"genre/{parts[1]}",
                )
            if len(parts) == 3:
                return await self._browse_episodes(*self._split_series_key(parts[2]))

        if category == "kana":
            if len(parts) == 1:
                return self._browse_kana_list()
            if len(parts) == 2:
                return await self._browse_series_list(
                    await self._client.get_ondemand_by_kana(parts[1]),  # type: ignore[arg-type]
                    path_prefix=f"kana/{parts[1]}",
                )
            if len(parts) == 3:
                return await self._browse_episodes(*self._split_series_key(parts[2]))

        return []

    def _browse_root(self) -> list[BrowseFolder]:
        """Return root browse folders."""
        folders = [
            ("live", "ライブ放送"),
            ("new", "新着番組"),
            ("genre", "ジャンル"),
            ("kana", "五十音順"),
        ]
        return [
            BrowseFolder(
                item_id=f"{DOMAIN}://{fid}",
                provider=DOMAIN,
                name=label,
                path=f"{DOMAIN}://{fid}",
            )
            for fid, label in folders
        ]

    async def _browse_live(self) -> list[Radio]:
        """Return live channels as Radio items."""
        live_programs = await self._client.get_live_programs()
        return [
            self._parse_live_radio(info)
            for info in live_programs.values()
        ]

    async def _browse_genre_list(self) -> list[BrowseFolder]:
        """Return genre list as browse folders."""
        genres = await self._client.get_genres()
        return [
            BrowseFolder(
                item_id=f"{DOMAIN}://genre/{g.genre}",
                provider=DOMAIN,
                name=g.name,
                path=f"{DOMAIN}://genre/{g.genre}",
            )
            for g in genres
        ]

    def _browse_kana_list(self) -> list[BrowseFolder]:
        """Return kana list as browse folders."""
        return [
            BrowseFolder(
                item_id=f"{DOMAIN}://kana/{kana_id}",
                provider=DOMAIN,
                name=label,
                path=f"{DOMAIN}://kana/{kana_id}",
            )
            for kana_id, label in KANA_MAP.items()
        ]

    @staticmethod
    def _series_key(series_site_id: str, corner_site_id: str) -> str:
        """Combine series/corner IDs into a single path segment."""
        return f"{series_site_id}_{corner_site_id}"

    @staticmethod
    def _split_series_key(key: str) -> tuple[str, str]:
        """Split a series key back into series_site_id and corner_site_id."""
        series_site_id, corner_site_id = key.rsplit("_", 1)
        return series_site_id, corner_site_id

    async def _browse_series_list(
        self, series_list: list[OndemandSeries], path_prefix: str
    ) -> list[BrowseFolder]:
        """Return series list as browse folders."""
        return [
            BrowseFolder(
                item_id=f"{DOMAIN}://{path_prefix}/{self._series_key(s.series_site_id, s.corner_site_id)}",
                provider=DOMAIN,
                name=s.title,
                path=f"{DOMAIN}://{path_prefix}/{self._series_key(s.series_site_id, s.corner_site_id)}",
                image=MediaItemImage(
                    type=ImageType.THUMB,
                    path=s.thumbnail_url,
                    provider=DOMAIN,
                    remotely_accessible=True,
                )
                if s.thumbnail_url
                else None,
            )
            for s in series_list
        ]

    async def _browse_episodes(
        self, series_site_id: str, corner_site_id: str
    ) -> list[Radio]:
        """Return episodes as Radio items."""
        episodes = await self._client.get_ondemand_programs(
            series_site_id, corner_site_id
        )
        return [
            self._parse_ondemand_radio(ep, series_site_id, corner_site_id, i)
            for i, ep in enumerate(episodes)
        ]

    # --- Search ---

    async def search(
        self,
        search_query: str,
        media_types: list[MediaType],
        limit: int = 5,
    ) -> SearchResults:
        """Search NHK Radio on-demand content."""
        if MediaType.RADIO not in media_types:
            return SearchResults()

        series_list = await self._client.search_ondemand(search_query)
        radios: list[Radio] = [
            self._parse_series_radio(series)
            for series in series_list[:limit]
        ]
        return SearchResults(radio=radios)

    # --- Library ---

    async def get_library_radios(self) -> AsyncGenerator[Radio, None]:
        """Yield saved radio items."""
        stored: list[str] = self.config.get_value(CONF_STORED_RADIOS) or []
        for item_id in stored:
            try:
                radio = await self.get_radio(item_id)
                yield radio
            except Exception:
                self.logger.warning("Failed to load library item: %s", item_id)

    async def get_radio(self, prov_radio_id: str) -> Radio:
        """Get a single radio item by ID."""
        if prov_radio_id.startswith("live:"):
            channel_id = prov_radio_id.removeprefix("live:")
            live_programs = await self._client.get_live_programs()
            if channel_id in live_programs:
                return self._parse_live_radio(live_programs[channel_id])
            msg = f"Channel not found: {channel_id}"
            raise ValueError(msg)

        if prov_radio_id.startswith("series:"):
            rest = prov_radio_id.removeprefix("series:")
            series_site_id, corner_site_id = rest.split("/", 1)
            episodes = await self._client.get_ondemand_programs(
                series_site_id, corner_site_id
            )
            if episodes:
                radio = self._parse_ondemand_radio(
                    episodes[0], series_site_id, corner_site_id, 0
                )
                radio.item_id = prov_radio_id
                return radio
            msg = f"No episodes for series: {prov_radio_id}"
            raise ValueError(msg)

        if prov_radio_id.startswith("od:"):
            rest = prov_radio_id.removeprefix("od:")
            parts = rest.split("/")
            series_site_id, corner_site_id = parts[0], parts[1]
            episode_key = parts[2]
            episodes = await self._client.get_ondemand_programs(
                series_site_id, corner_site_id
            )
            for i, ep in enumerate(episodes):
                eid = ep.episode_id if ep.episode_id else str(i)
                if eid == episode_key:
                    return self._parse_ondemand_radio(
                        ep, series_site_id, corner_site_id, i
                    )
            msg = f"Episode not found: {prov_radio_id}"
            raise ValueError(msg)

        msg = f"Unknown radio ID: {prov_radio_id}"
        raise ValueError(msg)

    async def library_add(self, item: Radio) -> bool:
        """Add item to library."""
        stored: list[str] = list(
            self.config.get_value(CONF_STORED_RADIOS) or []
        )
        item_id = item.item_id
        if item_id in stored:
            return False
        stored.append(item_id)
        self.update_config_value(CONF_STORED_RADIOS, stored)
        return True

    async def library_remove(
        self, prov_item_id: str, media_type: MediaType
    ) -> bool:
        """Remove item from library."""
        stored: list[str] = list(
            self.config.get_value(CONF_STORED_RADIOS) or []
        )
        if prov_item_id not in stored:
            return False
        stored.remove(prov_item_id)
        self.update_config_value(CONF_STORED_RADIOS, stored)
        return True

    # --- Stream ---

    async def get_stream_details(
        self, item_id: str, media_type: MediaType = MediaType.RADIO
    ) -> StreamDetails:
        """Get stream details for playback."""
        if item_id.startswith("live:"):
            channel_id = item_id.removeprefix("live:")
            live_programs = await self._client.get_live_programs()
            info = live_programs[channel_id]
            return StreamDetails(
                provider=DOMAIN,
                item_id=item_id,
                audio_format=AudioFormat(content_type=ContentType.AAC),
                media_type=MediaType.RADIO,
                stream_type=StreamType.HLS,
                path=info.present.stream_url,
                can_seek=False,
                allow_seek=False,
                stream_metadata=StreamMetadata(
                    title=info.present.series_name,
                    description=info.present.title,
                    image_url=info.present.thumbnail_url,
                ),
            )

        # series: → play latest episode
        if item_id.startswith("series:"):
            rest = item_id.removeprefix("series:")
            series_site_id, corner_site_id = rest.split("/", 1)
            episodes = await self._client.get_ondemand_programs(
                series_site_id, corner_site_id
            )
            if not episodes:
                msg = f"No episodes for series: {item_id}"
                raise ValueError(msg)
            ep = episodes[0]
            return StreamDetails(
                provider=DOMAIN,
                item_id=item_id,
                audio_format=AudioFormat(content_type=ContentType.AAC),
                media_type=MediaType.RADIO,
                stream_type=StreamType.HLS,
                path=ep.stream_url,
                can_seek=False,
                allow_seek=False,
                stream_metadata=StreamMetadata(
                    title=ep.series_name,
                    description=ep.title,
                    image_url=ep.thumbnail_url,
                ),
            )

        # od: → play specific episode
        if item_id.startswith("od:"):
            rest = item_id.removeprefix("od:")
            parts = rest.split("/")
            series_site_id, corner_site_id = parts[0], parts[1]
            episode_key = parts[2]
            episodes = await self._client.get_ondemand_programs(
                series_site_id, corner_site_id
            )
            for i, ep in enumerate(episodes):
                eid = ep.episode_id if ep.episode_id else str(i)
                if eid == episode_key:
                    return StreamDetails(
                        provider=DOMAIN,
                        item_id=item_id,
                        audio_format=AudioFormat(content_type=ContentType.AAC),
                        media_type=MediaType.RADIO,
                        stream_type=StreamType.HLS,
                        path=ep.stream_url,
                        can_seek=False,
                        allow_seek=False,
                        stream_metadata=StreamMetadata(
                            title=ep.series_name,
                            description=ep.title,
                            image_url=ep.thumbnail_url,
                        ),
                    )
            msg = f"Episode not found: {item_id}"
            raise ValueError(msg)

        msg = f"Unknown item: {item_id}"
        raise ValueError(msg)

    # --- Radio Parsing Helpers ---

    def _parse_live_radio(self, info: LiveInfo) -> Radio:
        """Convert LiveInfo to a Radio item."""
        program = info.present
        radio = Radio(
            item_id=f"live:{info.channel.id}",
            provider=DOMAIN,
            name=f"{info.channel.name} - {program.series_name}",
            provider_mappings={
                ProviderMapping(
                    item_id=f"live:{info.channel.id}",
                    provider_domain=DOMAIN,
                    provider_instance=self.instance_id,
                )
            },
        )
        images: list[MediaItemImage] = []
        if program.thumbnail_url:
            images.append(
                MediaItemImage(
                    type=ImageType.THUMB,
                    path=program.thumbnail_url,
                    provider=DOMAIN,
                    remotely_accessible=True,
                )
            )
        radio.metadata = MediaItemMetadata(
            description=program.title,
            images=UniqueList(images) if images else None,
        )
        return radio

    def _parse_ondemand_radio(
        self,
        ep: OndemandProgram,
        series_site_id: str,
        corner_site_id: str,
        index: int,
    ) -> Radio:
        """Convert OndemandProgram to a Radio item."""
        episode_key = ep.episode_id if ep.episode_id else str(index)
        item_id = f"od:{series_site_id}/{corner_site_id}/{episode_key}"
        radio = Radio(
            item_id=item_id,
            provider=DOMAIN,
            name=ep.title,
            provider_mappings={
                ProviderMapping(
                    item_id=item_id,
                    provider_domain=DOMAIN,
                    provider_instance=self.instance_id,
                )
            },
        )
        images: list[MediaItemImage] = []
        if ep.thumbnail_url:
            images.append(
                MediaItemImage(
                    type=ImageType.THUMB,
                    path=ep.thumbnail_url,
                    provider=DOMAIN,
                    remotely_accessible=True,
                )
            )
        radio.metadata = MediaItemMetadata(
            description=ep.description,
            images=UniqueList(images) if images else None,
        )
        return radio

    def _parse_series_radio(self, series: OndemandSeries) -> Radio:
        """Convert OndemandSeries to a Radio item."""
        item_id = f"series:{series.series_site_id}/{series.corner_site_id}"
        radio = Radio(
            item_id=item_id,
            provider=DOMAIN,
            name=series.title,
            provider_mappings={
                ProviderMapping(
                    item_id=item_id,
                    provider_domain=DOMAIN,
                    provider_instance=self.instance_id,
                )
            },
        )
        images: list[MediaItemImage] = []
        if series.thumbnail_url:
            images.append(
                MediaItemImage(
                    type=ImageType.THUMB,
                    path=series.thumbnail_url,
                    provider=DOMAIN,
                    remotely_accessible=True,
                )
            )
        radio.metadata = MediaItemMetadata(
            description=series.description,
            images=UniqueList(images) if images else None,
        )
        return radio
