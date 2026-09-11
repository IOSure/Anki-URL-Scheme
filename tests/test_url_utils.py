import pytest

from src.url_utils import normalize_anki_url, parse_anki_url


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("anki://search/tag%3Afoo", ("search", ("search", "tag:foo"))),
        ("anki:deck/Chinese%2FHSK", ("deck", ("deck", "Chinese", "HSK"))),
        ("anki:\\\\search\\tag%3Afoo", ("search", ("search", "tag:foo"))),
        ('"anki://deck/Default"', ("deck", ("deck", "Default"))),
        (
            "anki://x-callback-url/search?query=cid%3A1692469068390",
            ("search", ("search", "cid:1692469068390")),
        ),
    ],
)
def test_parse_anki_url(value: str, expected: tuple[str, tuple[str, ...]]) -> None:
    assert parse_anki_url(value) == expected


def test_normalize_non_anki_url() -> None:
    assert normalize_anki_url("raise") is None


@pytest.mark.parametrize(
    "value",
    [
        "anki://",
        "anki://unknown/value",
        "anki://search",
        "anki://deck",
    ],
)
def test_invalid_anki_url(value: str) -> None:
    with pytest.raises(ValueError):
        parse_anki_url(value)
