from __future__ import annotations

from typing import Optional
from urllib.parse import parse_qs, unquote, urlsplit


ALLOWED_COMMANDS = {"deck", "search"}


def normalize_anki_url(value: str) -> Optional[str]:
    """Normalize the URL variants produced by different operating systems."""
    value = value.strip().strip("\"'")
    scheme_index = value.lower().find("anki:")
    if scheme_index == -1:
        return None

    payload = value[scheme_index + len("anki:") :]
    payload = payload.replace("\\", "/").lstrip("/")
    return f"anki://{payload}"


def parse_anki_url(value: str) -> tuple[str, tuple[str, ...]]:
    """Return the command and its path components from an anki:// URL."""
    normalized = normalize_anki_url(value)
    if normalized is None:
        raise ValueError("Not an anki:// URL")

    parsed = urlsplit(normalized)
    path_parts = [
        unquote(part) for part in parsed.path.strip("/").split("/") if part
    ]
    if parsed.netloc:
        parts = tuple([unquote(parsed.netloc)] + path_parts)
    else:
        parts = tuple(path_parts)
    if not parts or not parts[0]:
        raise ValueError("Invalid URL format")

    command = parts[0].lower()
    if command == "x-callback-url":
        if len(parts) < 2:
            raise ValueError("Missing x-callback-url action")
        action = parts[1].lower()
        if action not in ALLOWED_COMMANDS:
            raise ValueError(f"Invalid x-callback-url action: {action}")

        query = parse_qs(parsed.query).get("query", [])
        if query:
            return action, (action, query[0])
        if len(parts) >= 3:
            return action, (action, "/".join(parts[2:]))
        requirement = "Deck name" if action == "deck" else "Query"
        raise ValueError(f"{requirement} required")

    if command not in ALLOWED_COMMANDS:
        raise ValueError(f"Invalid command: {command}")
    if len(parts) < 2:
        requirement = "Deck name" if command == "deck" else "Query"
        raise ValueError(f"{requirement} required")

    return command, parts
