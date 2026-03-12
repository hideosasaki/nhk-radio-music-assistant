"""Tests for NHK Radio MA provider."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from music_assistant_models.enums import ContentType, MediaType, StreamType
from music_assistant_models.media_items import BrowseFolder, ProviderMapping, Radio, Track

from nhk_radio_ma import NhkRadioProvider
from nhk_radio_ma.const import CONF_STORED_RADIOS, DOMAIN


def _radio(item_id: str, name: str) -> Radio:
    """Helper to create a Radio with required fields."""
    return Radio(
        item_id=item_id,
        provider=DOMAIN,
        name=name,
        provider_mappings={
            ProviderMapping(
                item_id=item_id,
                provider_domain=DOMAIN,
                provider_instance=DOMAIN,
            )
        },
    )


# --- Browse ---


async def test_browse_root(provider: NhkRadioProvider) -> None:
    """Root returns 4 folders."""
    result = await provider.browse("")
    assert len(result) == 4
    assert all(isinstance(r, BrowseFolder) for r in result)
    assert all(r.media_type == MediaType.FOLDER for r in result)
    names = [r.name for r in result]
    assert names == ["ライブ放送", "新着番組", "ジャンル", "五十音順"]


async def test_browse_live(provider: NhkRadioProvider) -> None:
    """Live returns Radio items for each channel."""
    result = await provider.browse(f"{DOMAIN}://live")
    assert len(result) == 3
    assert all(isinstance(r, Radio) for r in result)
    item_ids = {r.item_id for r in result}
    assert item_ids == {"live:r1", "live:r2", "live:fm"}


async def test_browse_new_series_list(provider: NhkRadioProvider) -> None:
    """New arrivals returns series folders with correct paths."""
    result = await provider.browse(f"{DOMAIN}://new")
    assert len(result) == 2
    assert all(isinstance(r, BrowseFolder) for r in result)
    assert result[0].path == f"{DOMAIN}://new/F684_01"
    assert result[1].path == f"{DOMAIN}://new/F685_02"


async def test_browse_series_episodes(provider: NhkRadioProvider) -> None:
    """Series path returns episodes as Track items."""
    result = await provider.browse(f"{DOMAIN}://new/F684_01")
    assert len(result) == 2
    assert all(isinstance(r, Track) for r in result)
    assert result[0].item_id == "od:F684/01/ep001"
    assert result[1].item_id == "od:F684/01/ep002"
    assert result[0].duration == 1800  # 30 minutes


async def test_browse_genre_list(provider: NhkRadioProvider) -> None:
    """Genre root returns genre folders."""
    result = await provider.browse(f"{DOMAIN}://genre")
    assert len(result) == 2
    assert all(isinstance(r, BrowseFolder) for r in result)
    assert result[0].name == "音楽"
    assert result[1].name == "ドラマ"


async def test_browse_kana_list(provider: NhkRadioProvider) -> None:
    """Kana root returns 10 kana folders."""
    result = await provider.browse(f"{DOMAIN}://kana")
    assert len(result) == 10
    assert all(isinstance(r, BrowseFolder) for r in result)
    assert result[0].name == "あ行"


# --- Search ---


async def test_search(provider: NhkRadioProvider) -> None:
    """Search returns Radio items from on-demand results."""
    results = await provider.search("テスト", [MediaType.RADIO], limit=5)
    assert len(results.radio) == 1
    assert results.radio[0].item_id == "series:F684/01"


async def test_search_wrong_media_type(provider: NhkRadioProvider) -> None:
    """Search with non-RADIO type returns empty."""
    results = await provider.search("テスト", [MediaType.TRACK], limit=5)
    assert len(results.radio) == 0


# --- Track (on-demand) ---


async def test_get_track(provider: NhkRadioProvider) -> None:
    """get_track returns a Track for an on-demand episode."""
    track = await provider.get_track("od:F684/01/ep001")
    assert isinstance(track, Track)
    assert track.item_id == "od:F684/01/ep001"
    assert track.duration == 1800


async def test_get_track_unknown(provider: NhkRadioProvider) -> None:
    """get_track raises ValueError for unknown ID."""
    with pytest.raises(ValueError, match="Unknown track"):
        await provider.get_track("live:r1")


# --- Stream Details ---


async def test_stream_details_live(provider: NhkRadioProvider) -> None:
    """Live stream returns HLS with correct URL, metadata, and no seek."""
    details = await provider.get_stream_details("live:r1")
    assert details.stream_type == StreamType.HLS
    assert details.media_type == MediaType.RADIO
    assert details.audio_format.content_type == ContentType.AAC
    assert "r1" in details.path
    assert details.stream_metadata is not None
    assert details.stream_metadata.title == "テスト番組"
    assert details.can_seek is False
    assert details.allow_seek is False


async def test_stream_details_ondemand(provider: NhkRadioProvider) -> None:
    """On-demand stream returns CUSTOM with URL in data and seek enabled."""
    details = await provider.get_stream_details("od:F684/01/ep001")
    assert details.stream_type == StreamType.CUSTOM
    assert details.media_type == MediaType.TRACK
    assert "ondemand" in details.data
    assert details.stream_metadata is not None
    assert details.can_seek is True
    assert details.allow_seek is True
    assert details.duration == 1800


async def test_stream_details_series(provider: NhkRadioProvider) -> None:
    """Series stream returns latest episode."""
    details = await provider.get_stream_details("series:F684/01")
    assert details.stream_type == StreamType.CUSTOM
    assert details.stream_metadata is not None
    assert details.stream_metadata.title == "テストシリーズ"


async def test_stream_details_unknown(provider: NhkRadioProvider) -> None:
    """Unknown item_id raises ValueError."""
    with pytest.raises(ValueError, match="Unknown item"):
        await provider.get_stream_details("invalid:xyz")


# --- Library ---


async def test_library_add_remove(provider: NhkRadioProvider) -> None:
    """Add and remove items from library."""
    radio = _radio("live:r1", "R1")

    added = await provider.library_add(radio)
    assert added is True

    # Duplicate returns False
    added_again = await provider.library_add(radio)
    assert added_again is False

    removed = await provider.library_remove("live:r1", MediaType.RADIO)
    assert removed is True

    removed_again = await provider.library_remove("live:r1", MediaType.RADIO)
    assert removed_again is False


async def test_library_get_radios(provider: NhkRadioProvider) -> None:
    """Get library radios returns saved items."""
    # Add a series and a live channel
    radio_live = _radio("live:r1", "R1")
    radio_series = _radio("series:F684/01", "Series")
    await provider.library_add(radio_live)
    await provider.library_add(radio_series)

    radios = [r async for r in provider.get_library_radios()]
    assert len(radios) == 2


# --- Radio Parsing ---


async def test_parse_radio_no_thumbnail(
    provider: NhkRadioProvider, mock_nhk_client: AsyncMock
) -> None:
    """Radio parsing works even without thumbnail."""
    from tests.conftest import _make_live_info, _make_live_program

    # Override with no-thumbnail live info
    info = _make_live_info()
    no_thumb_program = _make_live_program(thumbnail_url=None)
    from nhk_radio import LiveInfo

    info_no_thumb = LiveInfo(
        channel=info.channel,
        area=info.area,
        previous=None,
        present=no_thumb_program,
        following=None,
    )
    mock_nhk_client.get_live_programs.return_value = {"r1": info_no_thumb}

    result = await provider.browse(f"{DOMAIN}://live")
    assert len(result) == 1
    radio = result[0]
    assert isinstance(radio, Radio)
    # metadata.images should be None when no thumbnail
    assert radio.metadata.images is None


# --- Config ---


async def test_get_config_entries() -> None:
    """get_config_entries returns valid ConfigEntry objects."""
    from nhk_radio_ma import get_config_entries
    from music_assistant_models.config_entries import ConfigEntry, ConfigEntryType

    entries = await get_config_entries(mass=None)
    assert len(entries) == 2

    area_entry = entries[0]
    assert isinstance(area_entry, ConfigEntry)
    assert area_entry.key == "area"
    assert area_entry.type == ConfigEntryType.STRING
    assert area_entry.default_value == "tokyo"
    assert len(area_entry.options) == 8

    stored_entry = entries[1]
    assert isinstance(stored_entry, ConfigEntry)
    assert stored_entry.hidden is True
