"""Minimal type stubs for feedparser (typeshed ships none).

Covers the surface the project uses: the weekly-selection pipeline
(parse() + entries with link/title/summary/content/date attributes) and the
digest tests (description/links).
"""

from __future__ import annotations

from typing import Any

from _typeshed import Incomplete

FeedDate = tuple[int, int, int, int, int, int, int, int, int]

class FeedParserLink:
    href: str

class FeedParserDict(dict[str, Any]):
    entries: list[FeedParserDict]
    link: str
    title: str
    summary: str
    description: str
    content: list[FeedParserDict]
    links: list[FeedParserLink]
    published_parsed: FeedDate | None
    updated_parsed: FeedDate | None

def parse(
    url_file_stream_or_string: Incomplete,
    etag: str | None = None,
    modified: str | None = None,
    agent: str | None = None,
    referrer: str | None = None,
    handlers: Incomplete = None,
    request_headers: dict[str, str] | None = None,
    response_headers: Incomplete = None,
    resolve_relative_uris: bool = True,
    sanitize_html: bool = True,
) -> FeedParserDict: ...
