"""NHK Radio provider for Music Assistant."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncGenerator, Sequence
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

import aiohttp
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from music_assistant_models.enums import (
    ContentType,
    ImageType,
    LinkType,
    MediaType,
    ProviderFeature,
    StreamType,
)
from music_assistant_models.media_items import (
    Artist,
    AudioFormat,
    BrowseFolder,
    ItemMapping,
    MediaItemImage,
    MediaItemLink,
    MediaItemMetadata,
    Podcast,
    PodcastEpisode,
    ProviderMapping,
    Radio,
    SearchResults,
    UniqueList,
)
from music_assistant_models.streamdetails import StreamDetails, StreamMetadata
from nhk_radio import (
    LiveInfo,
    NhkRadioClient,
    OndemandEpisode,
    OndemandSeries,
)

from .const import (
    AREAS,
    CONF_AREA,
    CONF_STORED_PODCASTS,
    CONF_STORED_RADIOS,
    DOMAIN,
    KANA_MAP,
)

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
    ProviderFeature.LIBRARY_PODCASTS,
    ProviderFeature.LIBRARY_PODCASTS_EDIT,
}

_HLS_TIMEOUT = aiohttp.ClientTimeout(total=30)


async def setup(mass: Any, manifest: Any, config: Any) -> NhkRadioProvider:
    """Set up the NHK Radio provider."""
    return NhkRadioProvider(mass, manifest, config, SUPPORTED_FEATURES)


async def get_config_entries(
    mass: Any,
    instance_id: str | None = None,
    action: str | None = None,
    values: dict[str, Any] | None = None,
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
        ConfigEntry(
            key=CONF_STORED_PODCASTS,
            type=ConfigEntryType.STRING,
            label=CONF_STORED_PODCASTS,
            default_value=[],
            hidden=True,
            multi_value=True,
        ),
    )


class NhkRadioProvider(MusicProvider):
    """NHK Radio Music Provider."""

    _client: NhkRadioClient
    _live_cache: dict[str, LiveInfo]
    _live_watcher_task: asyncio.Task | None

    async def handle_async_init(self) -> None:
        """Initialize the provider."""
        self._client = NhkRadioClient(
            self.mass.http_session,
            area=self.config.get_value(CONF_AREA),
        )
        self._live_cache = {}
        self._live_watcher_task = None
        await self._client.get_channels()
        self.available = True

    # --- ID parsing helpers ---

    @staticmethod
    def _parse_od_id(item_id: str) -> tuple[str, str, str]:
        """Parse 'od:series/corner/episode' into components."""
        rest = item_id.removeprefix("od:")
        parts = rest.split("/")
        return parts[0], parts[1], parts[2]

    @staticmethod
    def _parse_series_id(item_id: str) -> tuple[str, str]:
        """Parse 'series:series_site_id/corner_site_id' into components."""
        rest = item_id.removeprefix("series:")
        return tuple(rest.split("/", 1))  # type: ignore[return-value]

    # --- Metadata helpers ---

    def _build_metadata(
        self, description: str, thumbnail_url: str | None
    ) -> MediaItemMetadata:
        """Build MediaItemMetadata with optional thumbnail."""
        images = None
        if thumbnail_url:
            images = UniqueList([
                MediaItemImage(
                    type=ImageType.THUMB,
                    path=thumbnail_url,
                    provider=DOMAIN,
                    remotely_accessible=True,
                )
            ])
        return MediaItemMetadata(description=description, images=images)

    # --- Browse ---

    async def browse(
        self, path: str
    ) -> Sequence[Radio | Podcast | PodcastEpisode | BrowseFolder]:
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
                item_id=(
                    f"{DOMAIN}://{path_prefix}"
                    f"/{self._series_key(s.series_site_id, s.corner_site_id)}"
                ),
                provider=DOMAIN,
                name=s.title,
                path=(
                    f"{DOMAIN}://{path_prefix}"
                    f"/{self._series_key(s.series_site_id, s.corner_site_id)}"
                ),
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
    ) -> list[Podcast | PodcastEpisode]:
        """Return series Podcast, plus PodcastEpisodes."""
        series, episodes = await self._client.get_ondemand_programs(
            series_site_id, corner_site_id
        )
        if not episodes:
            return []
        podcast = self._parse_podcast(series)
        result: list[Podcast | PodcastEpisode] = [podcast]
        result.extend(
            self._parse_podcast_episode(
                ep, series_site_id, corner_site_id, i, series
            )
            for i, ep in enumerate(episodes)
        )
        return result

    # --- Search ---

    async def search(
        self,
        search_query: str,
        media_types: list[MediaType],
        limit: int = 5,
    ) -> SearchResults:
        """Search NHK Radio on-demand content."""
        if MediaType.PODCAST not in media_types:
            return SearchResults()

        series_list = await self._client.search_ondemand(search_query)
        podcasts: list[Podcast] = [
            self._parse_podcast(series)
            for series in series_list[:limit]
        ]
        return SearchResults(podcasts=podcasts)

    # --- Podcast Episode (on-demand) ---

    async def _find_episode(
        self, series_site_id: str, corner_site_id: str, episode_key: str
    ) -> tuple[OndemandEpisode, int, OndemandSeries] | None:
        """Find an episode by key, returning (episode, index, series) or None."""
        series, episodes = await self._client.get_ondemand_programs(
            series_site_id, corner_site_id
        )
        for i, ep in enumerate(episodes):
            eid = ep.episode_id if ep.episode_id else str(i)
            if eid == episode_key:
                return ep, i, series
        return None

    async def get_podcast(self, prov_podcast_id: str) -> Podcast:
        """Get a single podcast by ID."""
        if prov_podcast_id.startswith("series:"):
            series_site_id, corner_site_id = self._parse_series_id(
                prov_podcast_id
            )
            series, _episodes = await self._client.get_ondemand_programs(
                series_site_id, corner_site_id
            )
            return self._parse_podcast(series)

        msg = f"Unknown podcast ID: {prov_podcast_id}"
        raise ValueError(msg)

    async def get_podcast_episodes(
        self, prov_podcast_id: str
    ) -> AsyncGenerator[PodcastEpisode, None]:
        """Get all episodes for a podcast."""
        series_site_id, corner_site_id = self._parse_series_id(prov_podcast_id)
        series, episodes = await self._client.get_ondemand_programs(
            series_site_id, corner_site_id
        )
        for i, ep in enumerate(episodes):
            yield self._parse_podcast_episode(
                ep, series_site_id, corner_site_id, i, series
            )

    async def get_podcast_episode(
        self, prov_episode_id: str
    ) -> PodcastEpisode:
        """Get a single podcast episode by ID."""
        if prov_episode_id.startswith("od:"):
            series_site_id, corner_site_id, episode_key = self._parse_od_id(
                prov_episode_id
            )
            result = await self._find_episode(
                series_site_id, corner_site_id, episode_key
            )
            if result is not None:
                ep, i, series = result
                return self._parse_podcast_episode(
                    ep, series_site_id, corner_site_id, i, series
                )
            msg = f"Episode not found: {prov_episode_id}"
            raise ValueError(msg)

        msg = f"Unknown episode ID: {prov_episode_id}"
        raise ValueError(msg)

    async def get_artist(self, prov_artist_id: str) -> Artist:
        """Get artist details by id."""
        return Artist(
            item_id=prov_artist_id,
            provider=DOMAIN,
            name=prov_artist_id,
            provider_mappings={
                ProviderMapping(
                    item_id=prov_artist_id,
                    provider_domain=DOMAIN,
                    provider_instance=self.instance_id,
                )
            },
        )

    # --- Library ---

    async def get_library_radios(self) -> AsyncGenerator[Radio, None]:
        """Yield saved live radio items."""
        stored: list[str] = self.config.get_value(CONF_STORED_RADIOS) or []
        for item_id in stored:
            if not item_id.startswith("live:"):
                continue
            try:
                radio = await self.get_radio(item_id)
                yield radio
            except (ValueError, KeyError):
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

        msg = f"Unknown radio ID: {prov_radio_id}"
        raise ValueError(msg)

    async def get_library_podcasts(self) -> AsyncGenerator[Podcast, None]:
        """Yield saved podcast items."""
        stored: list[str] = self.config.get_value(CONF_STORED_PODCASTS) or []
        for item_id in stored:
            try:
                podcast = await self.get_podcast(item_id)
                yield podcast
            except (ValueError, KeyError):
                self.logger.warning(
                    "Failed to load library podcast: %s", item_id
                )

    async def library_add(self, item: Radio | Podcast) -> bool:
        """Add item to library."""
        if isinstance(item, Podcast):
            stored: list[str] = list(
                self.config.get_value(CONF_STORED_PODCASTS) or []
            )
            if item.item_id in stored:
                return False
            stored.append(item.item_id)
            self.update_config_value(CONF_STORED_PODCASTS, stored)
            return True

        stored = list(self.config.get_value(CONF_STORED_RADIOS) or [])
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
        if media_type == MediaType.PODCAST:
            stored: list[str] = list(
                self.config.get_value(CONF_STORED_PODCASTS) or []
            )
            if prov_item_id not in stored:
                return False
            stored.remove(prov_item_id)
            self.update_config_value(CONF_STORED_PODCASTS, stored)
            return True

        stored = list(self.config.get_value(CONF_STORED_RADIOS) or [])
        if prov_item_id not in stored:
            return False
        stored.remove(prov_item_id)
        self.update_config_value(CONF_STORED_RADIOS, stored)
        return True

    # --- Stream ---

    # --- Live watcher ---

    def _start_live_watcher(self) -> None:
        """Start background task to watch for live program changes."""
        if self._live_watcher_task and not self._live_watcher_task.done():
            return
        self._live_watcher_task = asyncio.create_task(self._watch_live_programs())

    async def _watch_live_programs(self) -> None:
        """Watch for live program changes and update cache."""
        try:
            async for info in self._client.on_live_program_change():
                self._live_cache[info.channel.id] = info
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger.warning("Live watcher stopped", exc_info=True)

    async def _update_live_metadata(
        self, streamdetails: StreamDetails, elapsed_time: int
    ) -> None:
        """Update live stream metadata from cache."""
        channel_id = streamdetails.item_id.removeprefix("live:")
        info = self._live_cache.get(channel_id)
        if info is None:
            return
        program = info.present
        streamdetails.stream_metadata = StreamMetadata(
            title=program.title,
            album=program.series_name,
            artist=program.description,
            image_url=program.thumbnail_url,
        )

    async def unload(self) -> None:
        """Clean up on provider unload."""
        if self._live_watcher_task and not self._live_watcher_task.done():
            self._live_watcher_task.cancel()

    # NHK on-demand uses AES-128 encrypted HE-AAC HLS at 48kbps.
    # ffmpeg's HLS demuxer produces intermittent decode errors causing audible
    # glitches.  We use StreamType.CUSTOM to download and decrypt HLS segments
    # ourselves, yielding raw ADTS/AAC bytes so ffmpeg only needs to decode
    # a plain byte stream (no HLS protocol handling).

    async def get_stream_details(
        self, item_id: str, media_type: MediaType = MediaType.RADIO
    ) -> StreamDetails:
        """Get stream details for playback."""
        if item_id.startswith("live:"):
            channel_id = item_id.removeprefix("live:")
            live_programs = await self._client.get_live_programs()
            info = live_programs[channel_id]
            self._live_cache[channel_id] = info
            self._start_live_watcher()
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
                    title=info.present.title,
                    album=info.present.series_name,
                    artist=info.present.description,
                    image_url=info.present.thumbnail_url,
                ),
                stream_metadata_update_callback=self._update_live_metadata,
                stream_metadata_update_interval=10,
            )

        # series: → play latest episode
        if item_id.startswith("series:"):
            series_site_id, corner_site_id = self._parse_series_id(item_id)
            series, episodes = await self._client.get_ondemand_programs(
                series_site_id, corner_site_id
            )
            if not episodes:
                msg = f"No episodes for series: {item_id}"
                raise ValueError(msg)
            ep = episodes[0]
            return self._ondemand_stream_details(
                item_id, ep, series.description
            )

        # od: → play specific episode
        if item_id.startswith("od:"):
            series_site_id, corner_site_id, episode_key = self._parse_od_id(item_id)
            result = await self._find_episode(
                series_site_id, corner_site_id, episode_key
            )
            if result is not None:
                ep, _i, _series = result
                return self._ondemand_stream_details(item_id, ep)
            msg = f"Episode not found: {item_id}"
            raise ValueError(msg)

        msg = f"Unknown item: {item_id}"
        raise ValueError(msg)

    # --- Stream Helpers ---

    def _ondemand_stream_details(
        self,
        item_id: str,
        ep: OndemandEpisode,
        series_description: str = "",
    ) -> StreamDetails:
        """Build StreamDetails for an on-demand episode."""
        duration = int((ep.end_at - ep.start_at).total_seconds())
        return StreamDetails(
            provider=DOMAIN,
            item_id=item_id,
            audio_format=AudioFormat(content_type=ContentType.AAC),
            media_type=MediaType.PODCAST_EPISODE,
            stream_type=StreamType.CUSTOM,
            duration=duration if duration > 0 else None,
            data=ep.stream_url,
            can_seek=True,
            allow_seek=True,
            stream_metadata=StreamMetadata(
                title=ep.title,
                album=ep.series_name,
                artist=ep.description,
                description=series_description or None,
                image_url=ep.thumbnail_url,
            ),
        )

    # --- HLS stream handling ---

    async def _resolve_hls_segments(
        self, master_url: str, session: aiohttp.ClientSession
    ) -> tuple[bytes | None, bytes | None, list[tuple[float, str]]]:
        """Resolve HLS playlists and return (key, iv, segments).

        Fetches the master playlist, resolves the sub-playlist,
        parses encryption info and segment URLs.
        """
        # 1. Resolve master playlist → sub-playlist URL
        async with session.get(master_url, timeout=_HLS_TIMEOUT) as resp:
            resp.raise_for_status()
            master_text = await resp.text()

        sub_url: str | None = None
        for line in master_text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                sub_url = urljoin(master_url, line)
                break
        if not sub_url:
            msg = f"No sub-playlist found in master: {master_url}"
            raise ValueError(msg)

        # 2. Fetch sub-playlist
        async with session.get(sub_url, timeout=_HLS_TIMEOUT) as resp:
            resp.raise_for_status()
            playlist_text = await resp.text()

        # 3. Parse encryption key, segment durations, and segment URLs
        key_url: str | None = None
        iv: bytes | None = None
        segments: list[tuple[float, str]] = []
        pending_duration: float = 0.0

        for line in playlist_text.splitlines():
            line = line.strip()
            if line.startswith("#EXT-X-KEY:"):
                m = re.search(r'URI="([^"]+)"', line)
                if m:
                    key_url = urljoin(sub_url, m.group(1))
                m_iv = re.search(r"IV=0x([0-9a-fA-F]+)", line)
                iv = bytes.fromhex(m_iv.group(1)) if m_iv else None
            elif line.startswith("#EXTINF:"):
                try:
                    pending_duration = float(line.split(":")[1].split(",")[0])
                except (IndexError, ValueError):
                    pending_duration = 0.0
            elif line and not line.startswith("#"):
                segments.append((pending_duration, urljoin(sub_url, line)))
                pending_duration = 0.0

        # 4. Fetch decryption key
        key: bytes | None = None
        if key_url:
            async with session.get(key_url, timeout=_HLS_TIMEOUT) as resp:
                resp.raise_for_status()
                key = await resp.read()

        return key, iv, segments

    @staticmethod
    def _decrypt_segment(
        data: bytes, key: bytes, iv: bytes | None, seq: int
    ) -> bytes:
        """Decrypt an AES-128-CBC encrypted HLS segment."""
        seg_iv = iv if iv else seq.to_bytes(16, "big")
        cipher = Cipher(algorithms.AES(key), modes.CBC(seg_iv))
        decryptor = cipher.decryptor()
        data = decryptor.update(data) + decryptor.finalize()
        # Remove PKCS#7 padding
        if data:
            pad_len = data[-1]
            if 0 < pad_len <= 16:
                data = data[:-pad_len]
        return data

    async def get_audio_stream(
        self, streamdetails: StreamDetails, seek_position: int = 0
    ) -> AsyncGenerator[bytes, None]:
        """Yield raw AAC bytes from NHK on-demand HLS stream.

        Downloads the HLS playlist, fetches the AES-128 key, then
        downloads and decrypts each segment, yielding raw bytes.
        """
        master_url: str = streamdetails.data
        session = self.mass.http_session

        key, iv, segments = await self._resolve_hls_segments(master_url, session)

        # Skip segments before seek position
        start_index = 0
        if seek_position > 0:
            cumulative = 0.0
            for i, (dur, _) in enumerate(segments):
                if cumulative + dur > seek_position:
                    start_index = i
                    break
                cumulative += dur
            else:
                start_index = len(segments)

        # Download, decrypt, and yield each segment
        for seq, (_dur, seg_url) in enumerate(
            segments[start_index:], start=start_index
        ):
            try:
                async with session.get(seg_url, timeout=_HLS_TIMEOUT) as resp:
                    resp.raise_for_status()
                    data = await resp.read()
            except aiohttp.ClientError:
                self.logger.warning("Failed to download segment %d", seq)
                continue

            if key:
                data = self._decrypt_segment(data, key, iv, seq)

            yield data

    # --- Radio Parsing Helpers ---

    def _parse_live_radio(self, info: LiveInfo) -> Radio:
        """Convert LiveInfo to a Radio item."""
        program = info.present
        radio = Radio(
            item_id=f"live:{info.channel.id}",
            provider=DOMAIN,
            name=f"NHK {info.area.name} {info.channel.name}",
            provider_mappings={
                ProviderMapping(
                    item_id=f"live:{info.channel.id}",
                    provider_domain=DOMAIN,
                    provider_instance=self.instance_id,
                )
            },
        )
        radio.metadata = self._build_metadata(program.title, thumbnail_url=None)
        return radio

    # --- Podcast Parsing Helpers ---

    def _parse_podcast(self, series: OndemandSeries) -> Podcast:
        """Convert OndemandSeries to a Podcast item."""
        item_id = f"series:{series.series_site_id}/{series.corner_site_id}"
        podcast = Podcast(
            item_id=item_id,
            provider=DOMAIN,
            name=series.title,
            publisher=f"NHK {series.radio_broadcast}",
            provider_mappings={
                ProviderMapping(
                    item_id=item_id,
                    provider_domain=DOMAIN,
                    provider_instance=self.instance_id,
                )
            },
        )
        podcast.metadata = self._build_metadata(
            series.description, series.thumbnail_url
        )
        if series.series_url:
            podcast.metadata.links = {
                MediaItemLink(type=LinkType.WEBSITE, url=series.series_url)
            }
        return podcast

    def _parse_podcast_episode(
        self,
        ep: OndemandEpisode,
        series_site_id: str,
        corner_site_id: str,
        index: int,
        series: OndemandSeries,
    ) -> PodcastEpisode:
        """Convert OndemandEpisode to a PodcastEpisode item."""
        episode_key = ep.episode_id if ep.episode_id else str(index)
        item_id = f"od:{series_site_id}/{corner_site_id}/{episode_key}"
        duration = int((ep.end_at - ep.start_at).total_seconds())
        podcast_item_id = f"series:{series_site_id}/{corner_site_id}"
        episode = PodcastEpisode(
            item_id=item_id,
            provider=DOMAIN,
            name=ep.title,
            duration=max(duration, 0),
            position=index,
            podcast=ItemMapping(
                media_type=MediaType.PODCAST,
                item_id=podcast_item_id,
                provider=DOMAIN,
                name=series.title,
            ),
            provider_mappings={
                ProviderMapping(
                    item_id=item_id,
                    provider_domain=DOMAIN,
                    provider_instance=self.instance_id,
                )
            },
        )
        episode.metadata = self._build_metadata(ep.description, ep.thumbnail_url)
        if ep.act:
            episode.metadata.performers = {ep.act}
        episode.metadata.release_date = ep.start_at
        return episode
