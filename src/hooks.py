from __future__ import annotations

from collections.abc import Callable
from typing import Any, Optional

from aqt import mw
from aqt.qt import QEvent, QFileOpenEvent, QObject

from .handler import handle_url_protocol
from .log import logger
from .url_utils import normalize_anki_url


def _handle_anki_url(value: str) -> bool:
    normalized = normalize_anki_url(value)
    if normalized is None:
        return False

    try:
        handle_url_protocol(normalized)
    except ValueError as exc:
        logger.warning("Invalid anki:// URL %r: %s", value, exc)
    return True


class MacosUrlHandler(QObject):
    def eventFilter(self, obj: Any, event: QEvent) -> bool:
        if event.type() == QEvent.Type.FileOpen and isinstance(
            event, QFileOpenEvent
        ):
            url = event.url()
            if url.isValid() and url.scheme().lower() == "anki":
                _handle_anki_url(url.toString())
                return True

        return super().eventFilter(obj, event)


_macos_url_handler: Optional[MacosUrlHandler] = None


def setup_app_hook() -> None:
    global _macos_url_handler

    original_on_app_msg: Callable[[str], None] = mw.onAppMsg
    was_connected = True
    try:
        mw.app.appMsg.disconnect(original_on_app_msg)
    except (TypeError, RuntimeError):
        was_connected = False

    def on_app_msg_hk(buf: str) -> None:
        if _handle_anki_url(buf):
            return
        original_on_app_msg(buf)

    mw.onAppMsg = on_app_msg_hk  # type: ignore[method-assign]
    if was_connected:
        mw.app.appMsg.connect(mw.onAppMsg)

    _macos_url_handler = MacosUrlHandler(mw)
    mw.app.installEventFilter(_macos_url_handler)
