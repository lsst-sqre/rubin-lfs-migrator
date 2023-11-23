"""Utility functions"""
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import ParseResult, urlparse


def str_bool(inp: str) -> bool:
    inp = inp.upper()
    if not inp or inp == "0" or inp.startswith("F") or inp.startswith("N"):
        return False
    return True


def path(str_path: str) -> Path:
    # Gets us syntactic validation for free, except that there's not much
    # that would be an illegal path other than 0x00 as a character in it.
    return Path(str_path)


def url(str_url: str) -> ParseResult:
    # Again, gets us syntactic validation for free
    return urlparse(str_url)


def str_now() -> str:
    return datetime.isoformat(datetime.now(timezone.utc))
