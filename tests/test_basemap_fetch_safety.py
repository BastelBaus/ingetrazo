# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression checks for the Windows base-map crash (#327)."""
from __future__ import annotations

from PySide6.QtCore import QUrl

from georef.datum import SceneDatum
from georef.tile_fetcher import TileFetcher
from georef.tiles import PRESETS, TileCache, TileLayer
import views.viewport as viewport_module
from views.viewport import Viewport


class _QueuedTimer:
    callbacks = []

    @classmethod
    def singleShot(cls, _delay, callback):
        cls.callbacks.append(callback)


class _Fetcher:
    def __init__(self):
        self.requests = []

    def request(self, source, x, y, z):
        self.requests.append((source.id, x, y, z))
        return None


def test_missing_tiles_leave_paint_before_starting_network(monkeypatch):
    """A texture lookup during paint only queues work; it never enters QtNetwork."""
    _QueuedTimer.callbacks = []
    viewport = Viewport()
    monkeypatch.setattr(viewport_module, "QTimer", _QueuedTimer)
    layer = TileLayer(PRESETS["osm"], zoom=16)
    datum = SceneDatum(-12.0464, -77.0428)
    viewport.scene.tile_layer = layer
    viewport.scene.georef = datum
    fetcher = _Fetcher()
    monkeypatch.setattr(viewport, "_ensure_tile_fetcher", lambda: fetcher)

    x, y = layer.flat_tiles(datum)[0]
    assert viewport._tile_texture(layer, x, y) is None
    assert fetcher.requests == []
    assert len(_QueuedTimer.callbacks) == 1

    _QueuedTimer.callbacks.pop()()
    assert fetcher.requests
    assert viewport._tile_requests_scheduled is False
    viewport.deleteLater()


class _Signal:
    def connect(self, callback):
        self.callback = callback


class _Reply:
    def __init__(self):
        self.finished = _Signal()


class _NetworkManager:
    def get(self, request):
        self.request = request
        return _Reply()


def test_tile_download_passes_an_explicit_qurl_to_qt(tmp_path):
    fetcher = TileFetcher(TileCache(tmp_path))
    manager = _NetworkManager()
    fetcher._nam = manager

    fetcher._start_download(PRESETS["osm"], 1, 2, 3)

    assert isinstance(manager.request.url(), QUrl)
    assert manager.request.url().toString() == "https://tile.openstreetmap.org/3/1/2.png"


def test_a_tile_on_disk_is_read_at_once_without_the_network(tmp_path):
    """A sheet frame or an export is drawn ONCE: a tile already in the
    disk cache must come back in that same paint (deferring it left the
    base map blank in the composer), and reading it must not build the
    fetcher, whose network manager is what may not start inside paintGL."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QImage
    viewport = Viewport()
    cache = TileCache(tmp_path)
    img = QImage(4, 4, QImage.Format.Format_RGB32)
    img.fill(QColor(10, 120, 30))
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    cache.put("osm", 1, 2, 3, bytes(data))
    viewport._tile_disk_cache = cache
    got = viewport._disk_cached_tile(PRESETS["osm"], 1, 2, 3)
    assert got is not None and got.pixelColor(0, 0) == QColor(10, 120, 30)
    assert viewport._disk_cached_tile(PRESETS["osm"], 9, 9, 3) is None
    assert viewport._tile_fetcher is None, "the network manager was built"
    viewport.deleteLater()


def test_the_tile_cache_location_needs_no_network_module():
    """The viewport reads the cache location inside paintGL: the module
    that answers must not pull in QtNetwork (#327)."""
    from pathlib import Path
    import georef.tiles as tiles
    assert "PySide6.QtNetwork" not in Path(tiles.__file__).read_text(
        encoding="utf-8")
    assert tiles.default_cache_dir().name == "tiles"
