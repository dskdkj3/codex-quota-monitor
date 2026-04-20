import functools
import json
from importlib import resources


ASSET_CONTENT_TYPES = {
    "monitor.css": "text/css; charset=utf-8",
    "monitor.js": "application/javascript; charset=utf-8",
}


@functools.lru_cache(maxsize=None)
def _read_asset_text(name):
    return resources.files("codex_quota_monitor.assets").joinpath(name).read_text(encoding="utf-8")


@functools.lru_cache(maxsize=None)
def _read_asset_bytes(name):
    return resources.files("codex_quota_monitor.assets").joinpath(name).read_bytes()


def render_page(snapshot, refresh_seconds):
    initial_snapshot = json.dumps(snapshot, separators=(",", ":")).replace("</", "<\\/")
    page = _read_asset_text("index.html")
    page = page.replace("__META_REFRESH__", str(max(refresh_seconds * 4, 60)))
    page = page.replace("__INITIAL_SNAPSHOT__", initial_snapshot)
    page = page.replace("__REFRESH_MS__", str(refresh_seconds * 1000))
    return page


def load_asset_payload(name):
    if name not in ASSET_CONTENT_TYPES:
        raise KeyError(name)
    return _read_asset_bytes(name), ASSET_CONTENT_TYPES[name]
