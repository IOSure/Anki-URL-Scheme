import queue
import threading
import time
from collections.abc import Sequence

import aqt
from anki.utils import is_win
from aqt import mw
from aqt.qt import Qt

from .log import logger
from .url_utils import parse_anki_url


def raise_main_window() -> None:
    if is_win:
        mw.showMinimized()
        mw.setWindowState(Qt.WindowState.WindowActive)
        mw.showNormal()
    else:
        mw.activateWindow()
        mw.raise_()


def handle_url_protocol(url: str) -> None:
    """Handle anki:// URLs"""
    command, parts = parse_anki_url(url)
    logger.info("Handling %s URL with %d path component(s)", command, len(parts) - 1)
    # Queue the command for processing
    command_queue.put((command, parts))


# Add command queue to store pending commands
command_queue: queue.Queue[tuple[str, tuple[str, ...]]] = queue.Queue()


def process_command(command: str, parts: Sequence[str]) -> None:
    """Process a command"""
    try:
        # A URL can arrive while Anki is still opening a profile.
        while mw.col is None:
            time.sleep(1)

        # Raise main window first
        mw.taskman.run_on_main(raise_main_window)

        # Handle different commands
        if command == "search":
            query = "/".join(parts[1:])
            mw.taskman.run_on_main(lambda: open_browser_with_query(query))
        elif command == "deck":
            deck_name = "/".join(parts[1:])
            mw.taskman.run_on_main(lambda: select_deck(deck_name))

    except Exception as e:
        logger.error("Error processing queued command: %s", e)


def select_deck(deck_name: str) -> None:
    """Safely select a deck by name"""
    did = mw.col.decks.id(deck_name, create=False)
    if did is None:
        raise ValueError(f"Deck not found: {deck_name}")
    mw.col.decks.select(did)


def open_browser_with_query(search_query: str) -> None:
    aqt.dialogs.open("Browser", mw, search=(search_query,))


class CommandHandler(threading.Thread):
    daemon = True

    def run(self) -> None:
        while True:
            command, parts = command_queue.get()
            process_command(command, parts)
            command_queue.task_done()
