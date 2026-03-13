"""Test fixtures for NHK Radio MA provider."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nhk_radio import (
    Area,
    Channel,
    Genre,
    LiveInfo,
    LiveProgram,
    OndemandProgram,
    OndemandSeries,
)

from nhk_radio_ma import NhkRadioProvider
from nhk_radio_ma.const import CONF_AREA, CONF_STORED_RADIOS


# --- SDK model fixtures ---


def _make_channel(channel_id: str = "r1", name: str = "R1") -> Channel:
    return Channel(id=channel_id, name=name, stream_url=f"https://nhk.jp/{channel_id}.m3u8")


def _make_area() -> Area:
    return Area(
        id="nagoya",
        name="名古屋",
        areakey="300",
        channels=[_make_channel("r1", "R1"), _make_channel("r2", "R2"), _make_channel("fm", "FM")],
    )


def _make_live_program(
    series_name: str = "テスト番組",
    title: str = "テストタイトル",
    channel_id: str = "r1",
    thumbnail_url: str | None = "https://nhk.jp/thumb.jpg",
) -> LiveProgram:
    return LiveProgram(
        title=title,
        description="テスト説明",
        thumbnail_url=thumbnail_url,
        series_name=series_name,
        series_site_id="TEST01",
        act="テスト出演者",
        channel_id=channel_id,
        stream_url=f"https://nhk.jp/{channel_id}.m3u8",
        start_at=datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc),
        end_at=datetime(2025, 1, 1, 1, 0, tzinfo=timezone.utc),
        event_id="evt001",
    )


def _make_live_info(channel_id: str = "r1", name: str = "R1") -> LiveInfo:
    return LiveInfo(
        channel=_make_channel(channel_id, name),
        area=_make_area(),
        previous=None,
        present=_make_live_program(channel_id=channel_id),
        following=None,
    )


def _make_ondemand_series(
    series_site_id: str = "F684",
    corner_site_id: str = "01",
    title: str = "テストシリーズ",
) -> OndemandSeries:
    return OndemandSeries(
        title=title,
        description="シリーズ説明",
        thumbnail_url="https://nhk.jp/series_thumb.jpg",
        series_site_id=series_site_id,
        series_name=title,
        radio_broadcast="R1",
        corner_site_id=corner_site_id,
    )


def _make_ondemand_program(
    episode_id: str = "ep001",
    title: str = "テストエピソード",
    thumbnail_url: str | None = "https://nhk.jp/ep_thumb.jpg",
) -> OndemandProgram:
    return OndemandProgram(
        title=title,
        description="エピソード説明",
        thumbnail_url=thumbnail_url,
        series_name="テストシリーズ",
        series_site_id="F684",
        act="出演者",
        channel_id="r1",
        stream_url="https://nhk.jp/ondemand/ep001.m3u8",
        start_at=datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc),
        end_at=datetime(2025, 1, 1, 10, 30, tzinfo=timezone.utc),
        episode_id=episode_id,
    )


# --- Provider fixture ---


@pytest.fixture
def mock_nhk_client() -> AsyncMock:
    """Create a mock NhkRadioClient with pre-loaded return values."""
    client = AsyncMock()

    # Live
    client.get_live_programs.return_value = {
        "r1": _make_live_info("r1", "R1"),
        "r2": _make_live_info("r2", "R2"),
        "fm": _make_live_info("fm", "FM"),
    }
    client.get_channels.return_value = _make_area().channels

    # On-demand
    client.get_ondemand_new_arrivals.return_value = [
        _make_ondemand_series("F684", "01", "シリーズA"),
        _make_ondemand_series("F685", "02", "シリーズB"),
    ]
    client.get_ondemand_programs.return_value = (
        _make_ondemand_series("F684", "01", "テストシリーズ"),
        [
            _make_ondemand_program("ep001", "エピソード1"),
            _make_ondemand_program("ep002", "エピソード2"),
        ],
    )
    client.search_ondemand.return_value = [
        _make_ondemand_series("F684", "01", "検索結果シリーズ"),
    ]
    client.get_genres.return_value = [
        Genre(genre="music", name="音楽"),
        Genre(genre="drama", name="ドラマ"),
    ]
    client.get_ondemand_by_genre.return_value = [
        _make_ondemand_series("F686", "01", "ジャンルシリーズ"),
    ]
    client.get_ondemand_by_kana.return_value = [
        _make_ondemand_series("F687", "01", "あいうえお番組"),
    ]

    # on_live_program_change: default to an empty async generator
    async def _empty_generator():
        return
        yield  # noqa: RET504 - makes this an async generator

    client.on_live_program_change = _empty_generator

    return client


@pytest.fixture
def provider(mock_nhk_client: AsyncMock) -> NhkRadioProvider:
    """Create an NhkRadioProvider with a mocked client."""
    stored_radios: list[str] = []

    config_values: dict[str, object] = {
        CONF_AREA: "nagoya",
        CONF_STORED_RADIOS: stored_radios,
    }

    config = SimpleNamespace(
        get_value=lambda key: config_values.get(key),
        instance_id="nhk_radio_ma",
    )
    manifest = SimpleNamespace(domain="nhk_radio_ma")
    mass = SimpleNamespace(http_session=AsyncMock())

    p = NhkRadioProvider(mass, manifest, config, set())
    p._client = mock_nhk_client
    p._live_cache = {}
    p._live_watcher_task = None

    # Track config updates
    def _update_config(key: str, value: object) -> None:
        config_values[key] = value

    p.update_config_value = _update_config  # type: ignore[assignment]

    return p
